"""
Конфигурация FBS Print Agent
"""
import os
import sys

__version__ = "0.1.0"

PORT = int(os.environ.get("FBS_PRINT_AGENT_PORT", "9199"))
HOST = "127.0.0.1"
DEFAULT_PRINTER = os.environ.get("FBS_PRINT_AGENT_PRINTER", "")
# Таймаут печати SumatraPDF (секунды). Некоторые принтеры/драйверы отвечают медленно.
PRINT_TIMEOUT = int(os.environ.get("FBS_PRINT_AGENT_TIMEOUT", "90"))


def _get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _get_base_dir()
# Корень проекта FBS (родитель fbs-print-agent)
PROJECT_ROOT = os.path.dirname(BASE_DIR)
# Только портативная версия! Program Files исключён — установленная даёт "corrupted installation"
# (требует libmupdf.dll, при несовпадении версий — ошибка).
SUMATRA_PDF_PATHS = [
    os.path.join(BASE_DIR, "SumatraPDF.exe"),  # рядом с агентом (из установщика)
    os.path.join(os.environ.get("APPDATA", ""), "fbs-print-agent", "SumatraPDF.exe"),  # пользователь может положить сюда
    os.path.join(PROJECT_ROOT, "SumatraPDF.exe"),  # FBS/SumatraPDF.exe (разработка)
]
