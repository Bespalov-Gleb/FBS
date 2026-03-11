"""
Логика печати: PDF и PNG через SumatraPDF (PDF напрямую, PNG через конвертацию в PDF)
"""
import os
import subprocess
import tempfile
from typing import Optional

import img2pdf


def _find_sumatra() -> Optional[str]:
    from config import SUMATRA_PDF_PATHS

    for p in SUMATRA_PDF_PATHS:
        if p and os.path.isfile(p):
            return p
    return None


def get_sumatra_path() -> Optional[str]:
    """Путь к SumatraPDF (для диагностики)."""
    return _find_sumatra()


def _image_to_pdf(img_path: str, pdf_path: str) -> None:
    """Конвертировать изображение в PDF"""
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(img_path))


def _print_pdf_with_printer(
    pdf_path: str,
    printer: Optional[str],
    print_settings: Optional[str] = None,
) -> bool:
    """print_settings: fit (рекомендуется для этикеток), shrink, noscale.
    noscale на термо-принтерах часто даёт искажения — используйте fit."""
    sumatra = _find_sumatra()
    if not sumatra:
        _log_print_error("SumatraPDF не найден. Положите портативную версию в папку агента или %APPDATA%\\fbs-print-agent\\")
        return False
    abs_path = os.path.abspath(pdf_path)
    cmd = [sumatra, "-silent"]
    if printer:
        cmd.extend(["-print-to", printer])
    else:
        cmd.append("-print-to-default")
    # fit | shrink | noscale. По умолчанию fit. noscale = 100% (фактический размер) — для этикеток 58×40
    settings = print_settings if print_settings in ("noscale", "shrink", "fit") else "fit"
    cmd.extend(["-print-settings", settings])
    cmd.append(abs_path)
    from config import PRINT_TIMEOUT
    timeout = PRINT_TIMEOUT
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or b"").decode("utf-8", errors="ignore").strip()
            _log_print_error(
                f"SumatraPDF вернул {result.returncode}. SumatraPDF: {sumatra}. "
                f"PDF-файл: {abs_path}. stderr: {err}"
            )
        return result.returncode == 0
    except subprocess.TimeoutExpired as e:
        _log_print_error(
            f"SumatraPDF таймаут ({timeout} с). Путь: {sumatra}. PDF: {abs_path}. "
            "Проверьте принтер, драйвер. Увеличьте FBS_PRINT_AGENT_TIMEOUT."
        )
        return False
    except Exception as e:
        _log_print_error(f"SumatraPDF исключение: {e}. Путь: {sumatra}")
        return False


def _log_print_error(msg: str) -> None:
    """Записать ошибку печати в лог для диагностики."""
    try:
        log_dir = os.path.join(os.environ.get("APPDATA", ""), "fbs-print-agent")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "print_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


def print_document(
    data: bytes,
    mime: str,
    printer: Optional[str] = None,
    print_settings: Optional[str] = None,
) -> bool:
    """
    Печать документа. Поддерживает application/pdf и image/png.
    print_settings: noscale (100% для этикеток), shrink, fit.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        try:
            if mime in ("application/pdf", "application/octet-stream"):
                f.write(data)
                f.flush()
                os.fsync(f.fileno())  # гарантировать запись на диск до вызова SumatraPDF
                return _print_pdf_with_printer(f.name, printer, print_settings)
            elif mime in ("image/png", "image/jpeg", "image/jpg"):
                ext = ".png" if "png" in mime else ".jpg"
                img_path = f.name.replace(".pdf", ext)
                with open(img_path, "wb") as img_f:
                    img_f.write(data)
                pdf_path = f.name
                _image_to_pdf(img_path, pdf_path)
                try:
                    os.unlink(img_path)
                except OSError:
                    pass
                return _print_pdf_with_printer(pdf_path, printer, print_settings)
            else:
                return False
        finally:
            try:
                os.unlink(f.name)
            except OSError:
                pass
