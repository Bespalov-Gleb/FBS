"""
Конфигурация FBS Print Agent
"""
import os
import sys

__version__ = "0.1.0"

PORT = int(os.environ.get("FBS_PRINT_AGENT_PORT", "9199"))
HOST = "127.0.0.1"
DEFAULT_PRINTER = os.environ.get("FBS_PRINT_AGENT_PRINTER", "")


def _get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _get_base_dir()
# Корень проекта FBS (родитель fbs-print-agent)
PROJECT_ROOT = os.path.dirname(BASE_DIR)
SUMATRA_PDF_PATHS = [
    os.path.join(BASE_DIR, "SumatraPDF.exe"),
    os.path.join(PROJECT_ROOT, "SumatraPDF.exe"),  # FBS/SumatraPDF.exe
    os.path.join(os.environ.get("APPDATA", ""), "fbs-print-agent", "SumatraPDF.exe"),
    r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
    r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
]
