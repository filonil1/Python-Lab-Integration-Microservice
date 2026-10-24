from datetime import datetime
from typing import Any, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LabResultPayload(BaseModel):
    """
    Входящий payload с результатом лабораторного исследования.
    Поддерживает валидацию медицинских параметров и приведение типов.
    """
    order_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Уникальный номер/штрихкод заказа или пробирки",
        examples=["INV-2026-992384"]
    )
    patient_id: Union[int, str] = Field(
        ...,
        description="Идентификатор пациента (внутренний ID в базе или номер карты в МИС)",
        examples=["MED-100234", 1]
    )
    lab_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Наименование внешней лаборатории",
        examples=["Invitro", "Helix", "CMD"]
    )
    test_code: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Код лабораторного теста",
        examples=["AMH", "HCG", "E2", "PROG"]
    )
    test_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Полное наименование теста",
        examples=["Антимюллеров гормон (АМГ)", "Хорионический гонадотропин человека (ХГЧ)"]
    )
    value: Union[float, int, str] = Field(
        ...,
        description="Значение результата (числовое или строковое качественное)",
        examples=["4.85", 4.85, "< 0.1", "Положительно"]
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Единица измерения",
        examples=["нг/мл", "мМЕ/мл", "пмоль/л", "нмоль/л"]
    )
    reference_range: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Референсные границы нормы",
        examples=["1.20 - 4.50", "0.00 - 5.00", "Отрицательно"]
    )
    is_abnormal: bool = Field(
        ...,
        description="Флаг отклонения от референсных значений",
        examples=[True, False]
    )
    sample_date: datetime = Field(
        ...,
        description="Дата и время взятия биоматериала (ISO 8601)",
        examples=["2026-10-23T08:30:00"]
    )

    @field_validator("order_id", "lab_name", "test_code", "test_name", "unit", "reference_range")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Поле не может быть пустым или содержать одни пробелы")
        return cleaned

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Значение анализа не может быть null")
        str_val = str(v).strip()
        if not str_val:
            raise ValueError("Значение анализа не может быть пустой строкой")
        return str_val

    @field_validator("sample_date")
    @classmethod
    def validate_sample_date(cls, v: datetime) -> datetime:
        # Проверка на адекватность даты: не старше 2000 года и не в далеком будущем
        if v.year < 2000:
            raise ValueError("Дата забора биоматериала не может быть ранее 2000 года")
        return v

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class LabResultResponse(BaseModel):
    """Ответ на прием лабораторного результата."""
    status: str = Field(
        ...,
        description="'created' для новой записи, 'already_processed' для дубля",
        examples=["created", "already_processed"]
    )
    message: str = Field(..., description="Поясняющее сообщение сервиса")
    order_id: str
    test_code: str
    result_id: Optional[int] = None
    is_abnormal: bool

    model_config = ConfigDict(from_attributes=True)


class PatientHistoryItem(BaseModel):
    """Элемент хронологической истории анализов пациента."""
    result_id: int
    order_id: str
    lab_name: str
    test_code: str
    test_name: str
    value: str
    numeric_value: Optional[float]
    unit: str
    reference_range: str
    is_abnormal: bool
    sample_date: datetime
    received_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PatientLabHistoryResponse(BaseModel):
    """Полная история исследований пациента."""
    patient_id: int
    external_id: str
    full_name: str
    total_results: int
    abnormal_count: int
    history: List[PatientHistoryItem]

    model_config = ConfigDict(from_attributes=True)


class PatientListItem(BaseModel):
    """Краткая информация о пациенте для выпадающих списков."""
    id: int
    external_id: str
    full_name: str
    birth_date: Any
    gender: str

    model_config = ConfigDict(from_attributes=True)
