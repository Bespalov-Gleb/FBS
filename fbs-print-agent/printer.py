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


def _image_to_pdf(img_path: str, pdf_path: str) -> None:
    """Конвертировать изображение в PDF"""
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(img_path))


def _print_pdf_with_printer(pdf_path: str, printer: Optional[str]) -> bool:
    sumatra = _find_sumatra()
    if not sumatra:
        return False
    abs_path = os.path.abspath(pdf_path)
    if printer:
        cmd = [sumatra, "-silent", "-print-to", printer, abs_path]
    else:
        cmd = [sumatra, "-silent", "-print-to-default", abs_path]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return result.returncode == 0
    except Exception:
        return False


def print_document(data: bytes, mime: str, printer: Optional[str] = None) -> bool:
    """
    Печать документа. Поддерживает application/pdf и image/png.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        try:
            if mime in ("application/pdf", "application/octet-stream"):
                f.write(data)
                f.flush()
                return _print_pdf_with_printer(f.name, printer)
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
                return _print_pdf_with_printer(pdf_path, printer)
            else:
                return False
        finally:
            try:
                os.unlink(f.name)
            except OSError:
                pass
