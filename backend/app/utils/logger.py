"""
Настройка логирования
"""
import logging
import sys
from pathlib import Path
from typing import Any

from app.config import settings


class StructuredFormatter(logging.Formatter):
    """Форматтер для структурированных логов"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Базовые поля
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Добавление контекста из extra
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        # Добавление всех дополнительных полей из extra
        for key, value in record.__dict__.items():
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "thread", "threadName", "exc_info",
                "exc_text", "stack_info", "trace_id", "user_id"
            ]:
                log_data[key] = value
        
        # Форматирование в строку
        log_parts = [f"{k}={v}" for k, v in log_data.items()]
        result = " | ".join(log_parts)
        
        # Добавление исключения, если есть
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)
        
        return result


def setup_logging() -> logging.Logger:
    """
    Настройка логирования
    
    Returns:
        logging.Logger: Настроенный логгер
    """
    # Создание директории для логов
    log_path = Path(settings.LOG_FILE_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Настройка корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Удаление существующих handlers
    root_logger.handlers = []
    
    # Форматтер
    formatter = StructuredFormatter(
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler (всегда)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handlers — опционально (если Permission denied — только stdout)
    try:
        file_handler = logging.FileHandler(settings.LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        error_log_path = log_path.parent / "error.log"
        error_handler = logging.FileHandler(error_log_path, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)
    except (PermissionError, OSError):
        pass  # логи только в stdout
    
    # Создание логгера приложения
    app_logger = logging.getLogger("app")
    
    return app_logger


# Глобальный логгер
logger = setup_logging()
