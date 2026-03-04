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


def _print_pdf_with_printer(
    pdf_path: str,
    printer: Optional[str],
    print_settings: Optional[str] = None,
) -> bool:
    """print_settings: noscale (100%), shrink, fit — для этикеток 58/80 мм используйте noscale."""
    sumatra = _find_sumatra()
    if not sumatra:
        return False
    abs_path = os.path.abspath(pdf_path)
    cmd = [sumatra, "-silent"]
    if printer:
        cmd.extend(["-print-to", printer])
    else:
        cmd.append("-print-to-default")
    if print_settings in ("noscale", "shrink", "fit"):
        cmd.extend(["-print-settings", print_settings])
    cmd.append(abs_path)
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
