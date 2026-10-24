import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from fastapi import Depends, FastAPI, Response, status
from fastapi.responses import HTMLResponse
from loguru import logger
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.schemas import (
    LabResultPayload,
    LabResultResponse,
    PatientLabHistoryResponse,
    PatientListItem,
)
from app.service import (
    get_all_patients,
    get_patient_lab_history,
    process_lab_result,
)

# Настройка директории и файлов логирования аудита Loguru
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
AUDIT_LOG_FILE = LOG_DIR / "lab_audit.log"

logger.remove()  # Удаляем дефолтный обработчик

# 1. Консольный вывод (красивый и информативный)
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level> {extra}",
    level="INFO",
)

# 2. Файловый структурированный аудит лог с ротацией
logger.add(
    AUDIT_LOG_FILE,
    rotation="10 MB",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} | {message} | context={extra}",
    level="INFO",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: инициализация БД при старте."""
    logger.info("Инициализация лабораторного микросервиса и базы данных SQLite...")
    init_db()
    logger.info("Схема базы данных успешно создана / проверена.")
    yield
    logger.info("Завершение работы микросервиса интеграции анализов.")


app = FastAPI(
    title="МИС Клиники: Микросервис интеграции лабораторных исследований",
    description=(
        "Микросервис автоматического приема, валидации, обеспечения идемпотентности "
        "и транзакционного сохранения результатов лабораторных исследований "
        "(ВРТ / ЭКО, общая биохимия, гормональные панели) с логированием аудита."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse, tags=["Веб-интерфейс"])
def get_web_ui():
    """Интерактивный графический интерфейс для демонстрации и ручного ввода анализов."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Интерфейс не найден. Перейдите на /docs</h1>", status_code=404)


@app.get("/health", tags=["Служебные"])
def health_check():
    """Проверка жизнеспособности сервиса."""
    return {"status": "ok", "service": "lab-integration-service", "version": "1.0.0"}


@app.get(
    "/api/v1/patients",
    response_model=List[PatientListItem],
    summary="Список пациентов клиники",
    tags=["Справочники"],
)
def list_patients(db: Session = Depends(get_db)):
    """Получение списка зарегистрированных пациентов клиники для выпадающих меню."""
    return get_all_patients(db)


@app.get(
    "/api/v1/audit-logs",
    response_model=List[str],
    summary="Последние записи журнала аудита",
    tags=["Служебные"],
)
def get_audit_logs():
    """Выгрузка последних строк из лога аудита (logs/lab_audit.log) для визуализации в интерфейсе."""
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        lines = AUDIT_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
        return lines[-40:]  # Последние 40 записей
    except Exception as exc:
        logger.error("Ошибка чтения файла логов аудита: {}", exc)
        return [f"Ошибка чтения логов: {exc}"]


@app.post(
    "/api/v1/lab-results",
    response_model=LabResultResponse,
    summary="Прием результатов анализов от внешней лаборатории",
    tags=["Лабораторные исследования"],
    responses={
        201: {"description": "Результат успешно записан в БД"},
        200: {"description": "Результат уже был записан ранее (идемпотентный ответ)"},
        400: {"description": "Ошибка валидации или несоответствие данных"},
        404: {"description": "Пациент не найден в МИС"},
    },
)
def receive_lab_result(
    payload: LabResultPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Прием лабораторного анализа от внешней лаборатории (Инвитро, Хеликс, ЦМД и др.):
    - Валидация медицинских параметров;
    - Обеспечение строгой идемпотентности по связке (order_id + test_code);
    - Выявление и аудит-логирование аномальных значений (is_abnormal);
    - Транзакционная запись в БД.
    """
    result_dto, status_code = process_lab_result(db, payload)
    response.status_code = status_code
    return result_dto


@app.get(
    "/api/v1/patients/{patient_id}/lab-history",
    response_model=PatientLabHistoryResponse,
    summary="История лабораторных исследований пациента",
    tags=["Лабораторные исследования"],
    responses={
        200: {"description": "Хронологическая история анализов пациента"},
        404: {"description": "Пациент не найден"},
    },
)
def get_patient_history(
    patient_id: str,
    db: Session = Depends(get_db),
):
    """
    Получение хронологической выгрузки лабораторных исследований пациента
    с подсчетом отклонений от нормы и референсными интервалами.
    Поддерживает поиск как по внутреннему ID, так и по номеру карты в МИС (например, MED-100234).
    """
    return get_patient_lab_history(db, patient_id)
