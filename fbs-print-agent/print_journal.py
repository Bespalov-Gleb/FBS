"""
Журнал печати — запись каждого задания для проверки перехвата.
Хранится в APPDATA/fbs-print-agent/print_journal.json
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional

MAX_ENTRIES = 500


def _journal_path() -> str:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    dir_path = os.path.join(base, "fbs-print-agent")
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, "print_journal.json")


_lock = threading.Lock()


def _load_entries() -> list:
    path = _journal_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("entries", [])
    except Exception:
        return []


def _save_entries(entries: list) -> None:
    path = _journal_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=0)


def log_print(
    printer: Optional[str],
    mime: str,
    size_bytes: int,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """Добавить запись в журнал печати."""
    entry = {
        "ts": datetime.now().isoformat(),
        "printer": printer or "(по умолчанию)",
        "mime": mime,
        "size_bytes": size_bytes,
        "success": success,
        "error": error,
    }
    with _lock:
        entries = _load_entries()
        entries.append(entry)
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        _save_entries(entries)


def get_entries(limit: int = 100) -> list:
    """Получить последние записи журнала (новые сверху)."""
    with _lock:
        entries = _load_entries()
        return list(reversed(entries[-limit:]))
