#!/usr/bin/env python3
"""
Скрипт начального наполнения базы данных (Seed Data).
Создает 5 тестовых пациентов клиники репродуктивной медицины (ЭКО / ВРТ)
и несколько базовых лабораторных заказов.
"""
from datetime import date, datetime, timedelta
from loguru import logger
from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models import LabOrder, LabTestResult, Patient


def seed_database():
    logger.info("Запуск сидирования тестовых данных...")
    init_db()

    db = SessionLocal()
    try:
        # Проверяем, есть ли уже пациенты
        existing_count = db.execute(select(Patient)).scalars().all()
        if existing_count:
            logger.info("База данных уже содержит {} пациентов. Очистка или пропуск.", len(existing_count))
            return

        # 1. Создаем 5 пациентов клиники
        patients_data = [
            {
                "external_id": "MED-100234",
                "full_name": "Иванова Анна Сергеевна",
                "birth_date": date(1991, 4, 12),
                "gender": "female",
            },
            {
                "external_id": "MED-100235",
                "full_name": "Смирнова Елена Владимировна",
                "birth_date": date(1988, 9, 23),
                "gender": "female",
            },
            {
                "external_id": "MED-100236",
                "full_name": "Кузнецова Мария Дмитриевна",
                "birth_date": date(1996, 11, 5),
                "gender": "female",
            },
            {
                "external_id": "MED-100237",
                "full_name": "Васильева Татьяна Андреевна",
                "birth_date": date(1985, 2, 18),
                "gender": "female",
            },
            {
                "external_id": "MED-100238",
                "full_name": "Морозов Алексей Игоревич",
                "birth_date": date(1987, 7, 30),
                "gender": "male",
            },
        ]

        patient_objs = []
        for p in patients_data:
            patient = Patient(**p)
            db.add(patient)
            patient_objs.append(patient)

        db.flush()
        logger.info("Успешно добавлено 5 пациентов в базу данных.")

        # 2. Добавляем исторические анализы для пациентки Ивановой А.С. (MED-100234)
        p1 = patient_objs[0]
        order1 = LabOrder(
            order_barcode="INV-2026-881001",
            patient_id=p1.id,
            lab_name="Invitro",
            order_date=datetime.now() - timedelta(days=5),
            status="COMPLETED",
        )
        db.add(order1)
        db.flush()

        results_p1 = [
            LabTestResult(
                order_id=order1.id,
                test_code="AMH",
                test_name="Антимюллеров гормон (АМГ)",
                value="0.75",
                numeric_value=0.75,
                unit="нг/мл",
                reference_range="1.20 - 4.50",
                is_abnormal=True,  # Снижен овариальный резерв
                sample_date=datetime.now() - timedelta(days=5, hours=3),
            ),
            LabTestResult(
                order_id=order1.id,
                test_code="FSH",
                test_name="Фолликулостимулирующий гормон (ФСГ)",
                value="11.8",
                numeric_value=11.8,
                unit="мМЕ/мл",
                reference_range="3.5 - 12.5",
                is_abnormal=False,
                sample_date=datetime.now() - timedelta(days=5, hours=3),
            ),
        ]
        db.add_all(results_p1)

        # 3. Добавляем заказ для пациентки Смирновой Е.В. (MED-100235) - мониторинг после переноса
        p2 = patient_objs[1]
        order2 = LabOrder(
            order_barcode="HLX-2026-773012",
            patient_id=p2.id,
            lab_name="Helix",
            order_date=datetime.now() - timedelta(days=2),
            status="COMPLETED",
        )
        db.add(order2)
        db.flush()

        results_p2 = [
            LabTestResult(
                order_id=order2.id,
                test_code="HCG",
                test_name="ХГЧ общий (b-ХГЧ)",
                value="185.4",
                numeric_value=185.4,
                unit="мМЕ/мл",
                reference_range="< 5.0",
                is_abnormal=True,  # Клинически ожидаемое подтверждение имплантации в криопротоколе
                sample_date=datetime.now() - timedelta(days=2, hours=4),
            ),
            LabTestResult(
                order_id=order2.id,
                test_code="PROG",
                test_name="Прогестерон",
                value="45.2",
                numeric_value=45.2,
                unit="нмоль/л",
                reference_range="29.0 - 105.0",
                is_abnormal=False,
                sample_date=datetime.now() - timedelta(days=2, hours=4),
            ),
        ]
        db.add_all(results_p2)

        db.commit()
        logger.info("Начальные лабораторные заказы и результаты успешно созданы.")

    except Exception as exc:
        db.rollback()
        logger.error("Ошибка при сидировании данных: {}", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
