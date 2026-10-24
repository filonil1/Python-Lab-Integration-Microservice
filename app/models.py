from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Patient(Base):
    """Модель пациента клиники (синхронизируется с МИС Медиалог)."""
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="Номер амбулаторной карты МИС (PAT_ID)"
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False, default="female")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Связи
    orders: Mapped[List["LabOrder"]] = relationship(
        "LabOrder", back_populates="patient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, ext_id='{self.external_id}', name='{self.full_name}')>"


class LabOrder(Base):
    """Лабораторный заказ / пробирка с уникальным штрихкодом (order_id)."""
    __tablename__ = "lab_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_barcode: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="Штрихкод заказа лаборатории / вакутейнера"
    )
    patient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lab_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Наименование лаборатории (Инвитро, Хеликс, ЦМД и др.)"
    )
    order_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="COMPLETED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Связи
    patient: Mapped["Patient"] = relationship("Patient", back_populates="orders")
    results: Mapped[List["LabTestResult"]] = relationship(
        "LabTestResult", back_populates="order", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LabOrder(id={self.id}, barcode='{self.order_barcode}', lab='{self.lab_name}')>"


class LabTestResult(Base):
    """Результат конкретного биохимического / гормонального теста."""
    __tablename__ = "lab_test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lab_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_code: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="Код анализа (например, AMH, HCG, E2, LH)"
    )
    test_name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Строковое значение результата (включая <0.1, Не обнаружено)"
    )
    numeric_value: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Числовое представление для фильтрации и графиков"
    )
    unit: Mapped[str] = mapped_column(String(64), nullable=False, comment="Единица измерения (нг/мл, мМЕ/мл)")
    reference_range: Mapped[str] = mapped_column(String(128), nullable=False, comment="Референсный интервал")
    is_abnormal: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True, comment="Флаг выхода за пределы нормы"
    )
    sample_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="Дата и время забора биоматериала"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="Время приема микросервисом"
    )

    # Связи
    order: Mapped["LabOrder"] = relationship("LabOrder", back_populates="results")

    # Идемпотентность на уровне схемы БД: в одном заказе один тест может быть только единожды
    __table_args__ = (
        UniqueConstraint("order_id", "test_code", name="uq_order_test_code"),
        Index("ix_test_results_order_test", "order_id", "test_code"),
    )

    def __repr__(self) -> str:
        return f"<LabTestResult(id={self.id}, code='{self.test_code}', val='{self.value}', abnormal={self.is_abnormal})>"
