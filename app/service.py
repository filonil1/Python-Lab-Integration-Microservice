import re
from typing import Optional, Tuple
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from app.models import LabOrder, LabTestResult, Patient
from app.schemas import (
    LabResultPayload,
    LabResultResponse,
    PatientHistoryItem,
    PatientLabHistoryResponse,
)


def _try_parse_numeric(value_str: str) -> Optional[float]:
    """Парсинг числового значения из строки (убирая запятые, лишние символы)."""
    try:
        clean_str = value_str.replace(",", ".").strip()
        # Извлекаем первое валидное число
        match = re.search(r"[-+]?\d*\.?\d+", clean_str)
        if match:
            return float(match.group())
    except (ValueError, TypeError):
        pass
    return None


def find_patient_by_id_or_external(db: Session, patient_ref: str | int) -> Optional[Patient]:
    """Поиск пациента по внутреннему PK (id) или номеру карты МИС (external_id)."""
    # Если передан int или строка, состоящая только из цифр, пробуем найти по ID
    if isinstance(patient_ref, int) or (isinstance(patient_ref, str) and patient_ref.isdigit()):
        patient = db.execute(select(Patient).where(Patient.id == int(patient_ref))).scalar_one_or_none()
        if patient:
            return patient

    # Поиск по external_id (номер карты МИС)
    return db.execute(
        select(Patient).where(Patient.external_id == str(patient_ref).strip())
    ).scalar_one_or_none()


def process_lab_result(db: Session, payload: LabResultPayload) -> Tuple[LabResultResponse, int]:
    """
    Транзакционная обработка и запись входящего анализа.
    Реализует строгую идемпотентность по составному ключу (order_id + test_code).
    
    Возвращает:
        (LabResultResponse, http_status_code)
    """
    audit_logger = logger.bind(
        order_barcode=payload.order_id,
        test_code=payload.test_code,
        lab_name=payload.lab_name,
        patient_ref=payload.patient_id,
    )

    audit_logger.info(
        "Получен входящий лабораторный результат: test='{}', val='{} {}', abnormal={}",
        payload.test_name,
        payload.value,
        payload.unit,
        payload.is_abnormal,
    )

    # 1. Валидация привязки к пациенту клиники
    patient = find_patient_by_id_or_external(db, payload.patient_id)
    if not patient:
        audit_logger.error(
            "Отклонено: пациент '{}' не найден в базе МИС клиники", payload.patient_id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пациент с идентификатором '{payload.patient_id}' не зарегистрирован в МИС",
        )

    # 2. Логирование аномального значения в аудит (клинически значимые маркеры)
    if payload.is_abnormal:
        audit_logger.warning(
            "[AUDIT-ALERT] ВНИМАНИЕ! Зафиксировано критическое/аномальное значение! "
            "Пациент: {} (карта: {}), Тест: {} ({}), Результат: {} {}, Норма: '{}'",
            patient.full_name,
            patient.external_id,
            payload.test_code,
            payload.test_name,
            payload.value,
            payload.unit,
            payload.reference_range,
        )

    # 3. Поиск или создание заказа (LabOrder)
    order = db.execute(
        select(LabOrder).where(LabOrder.order_barcode == payload.order_id)
    ).scalar_one_or_none()

    if not order:
        order = LabOrder(
            order_barcode=payload.order_id,
            patient_id=patient.id,
            lab_name=payload.lab_name,
            order_date=payload.sample_date,
            status="COMPLETED",
        )
        db.add(order)
        db.flush()  # Получаем order.id в рамках текущей транзакции
        audit_logger.info(
            "Создан новый лабораторный заказ ID={} для штрихкода '{}'",
            order.id,
            payload.order_id,
        )
    else:
        # Проверка целостности: не подменили ли пациента в существующем заказе
        if order.patient_id != patient.id:
            audit_logger.error(
                "Конфликт целостности данных: заказ '{}' уже привязан к пациенту ID={}, а передан patient_id={}",
                payload.order_id,
                order.patient_id,
                patient.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Заказ '{payload.order_id}' уже зарегистрирован на другого пациента в МИС",
            )

    # 4. Проверка идемпотентности: результат по этому тесту в этом заказе уже существует?
    existing_result = db.execute(
        select(LabTestResult).where(
            LabTestResult.order_id == order.id,
            LabTestResult.test_code == payload.test_code,
        )
    ).scalar_one_or_none()

    if existing_result:
        audit_logger.warning(
            "[IDEMPOTENCY] Дубликат: результат теста '{}' для заказа '{}' уже обработан (result_id={}). "
            "Повторная запись пропущена.",
            payload.test_code,
            payload.order_id,
            existing_result.id,
        )
        # Возвращаем 200 OK со статусом "already_processed" без дублирования записи
        response = LabResultResponse(
            status="already_processed",
            message="Результат данного исследования уже был сохранен ранее",
            order_id=payload.order_id,
            test_code=payload.test_code,
            result_id=existing_result.id,
            is_abnormal=existing_result.is_abnormal,
        )
        return response, status.HTTP_200_OK

    # 5. Сохранение нового результата в транзакции
    numeric_val = _try_parse_numeric(payload.value)
    new_result = LabTestResult(
        order_id=order.id,
        test_code=payload.test_code,
        test_name=payload.test_name,
        value=payload.value,
        numeric_value=numeric_val,
        unit=payload.unit,
        reference_range=payload.reference_range,
        is_abnormal=payload.is_abnormal,
        sample_date=payload.sample_date,
    )

    try:
        db.add(new_result)
        db.commit()
        db.refresh(new_result)
    except IntegrityError as exc:
        db.rollback()
        audit_logger.error("Ошибка уникальности/целостности при вставке: {}", exc)
        # Обработка конкурентной гонки за один и тот же тест
        existing = db.execute(
            select(LabTestResult).where(
                LabTestResult.order_id == order.id,
                LabTestResult.test_code == payload.test_code,
            )
        ).scalar_one_or_none()
        if existing:
            return LabResultResponse(
                status="already_processed",
                message="Результат был сохранен параллельным запросом",
                order_id=payload.order_id,
                test_code=payload.test_code,
                result_id=existing.id,
                is_abnormal=existing.is_abnormal,
            ), status.HTTP_200_OK
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт сохранения лабораторного результата",
        )

    audit_logger.info(
        "[AUDIT-SUCCESS] Успешно сохранен результат анализа ID={} для пациента '{}'",
        new_result.id,
        patient.full_name,
    )

    response = LabResultResponse(
        status="created",
        message="Результат исследования успешно принят и сохранен",
        order_id=payload.order_id,
        test_code=payload.test_code,
        result_id=new_result.id,
        is_abnormal=new_result.is_abnormal,
    )
    return response, status.HTTP_201_CREATED


def get_patient_lab_history(db: Session, patient_ref: str | int) -> PatientLabHistoryResponse:
    """
    Выгрузка полной хронологической истории лабораторных анализов пациента.
    Сортировка: от свежих к старым.
    """
    patient = find_patient_by_id_or_external(db, patient_ref)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пациент с идентификатором '{patient_ref}' не найден",
        )

    # Запрос с соединением через orders
    query = (
        select(LabTestResult, LabOrder)
        .join(LabOrder, LabTestResult.order_id == LabOrder.id)
        .where(LabOrder.patient_id == patient.id)
        .order_by(LabTestResult.sample_date.desc(), LabTestResult.received_at.desc())
    )
    rows = db.execute(query).all()

    items = []
    abnormal_count = 0

    for result, order in rows:
        if result.is_abnormal:
            abnormal_count += 1

        items.append(
            PatientHistoryItem(
                result_id=result.id,
                order_id=order.order_barcode,
                lab_name=order.lab_name,
                test_code=result.test_code,
                test_name=result.test_name,
                value=result.value,
                numeric_value=result.numeric_value,
                unit=result.unit,
                reference_range=result.reference_range,
                is_abnormal=result.is_abnormal,
                sample_date=result.sample_date,
                received_at=result.received_at,
            )
        )

    return PatientLabHistoryResponse(
        patient_id=patient.id,
        external_id=patient.external_id,
        full_name=patient.full_name,
        total_results=len(items),
        abnormal_count=abnormal_count,
        history=items,
    )


def get_all_patients(db: Session) -> list[Patient]:
    """Список всех пациентов для выпадающих меню интерфейса."""
    return list(db.execute(select(Patient).order_by(Patient.id)).scalars().all())

