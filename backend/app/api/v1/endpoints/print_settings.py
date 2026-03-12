"""
API endpoints для настроек печати (Диспетчер печати)
"""
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.models.print_settings import PrintSettings
from app.models.user import User

router = APIRouter(prefix="/print-settings", tags=["Print Settings"])


class OzonLabelsSchema(BaseModel):
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    rotate: Optional[int] = None  # 0 / 90 / 180 / 270


class WbLabelsSchema(BaseModel):
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    rotate: Optional[int] = None  # 0 / 90 / 180 / 270


class KizLabelsSchema(BaseModel):
    width_mm: Optional[int] = None
    height_mm: Optional[int] = None
    rotate: Optional[int] = None  # 0 / 90 / 180 / 270


class BarcodeLabelsSchema(BaseModel):
    rotate: Optional[int] = None  # 0 / 90 / 180 / 270


class PrintSettingsResponse(BaseModel):
    """Настройки печати"""
    default_printer: Optional[str] = None
    label_format: Optional[str] = None
    label_template: Optional[str] = None
    auto_print_on_click: Optional[bool] = None
    auto_print_kiz_duplicate: Optional[bool] = None
    printer_dpi: Optional[int] = None  # 203 или 300 — DPI принтера
    print_scale: Optional[str] = None  # fit | shrink | noscale — для SumatraPDF
    ozon_labels: Optional[dict] = None     # {width_mm, height_mm, rotate}
    wb_labels: Optional[dict] = None       # {width_mm, height_mm, rotate}
    kiz_labels: Optional[dict] = None      # {width_mm, height_mm, rotate}
    barcode_labels: Optional[dict] = None  # {rotate}


class PrintSettingsUpdate(BaseModel):
    """Обновление настроек"""
    default_printer: Optional[str] = None
    label_format: Optional[str] = None
    label_template: Optional[str] = None
    auto_print_on_click: Optional[bool] = None
    auto_print_kiz_duplicate: Optional[bool] = None
    printer_dpi: Optional[int] = None  # 203 или 300
    print_scale: Optional[str] = None  # fit | shrink | noscale
    ozon_labels: Optional[OzonLabelsSchema] = None
    wb_labels: Optional[WbLabelsSchema] = None
    kiz_labels: Optional[KizLabelsSchema] = None
    barcode_labels: Optional[BarcodeLabelsSchema] = None


def _ozon_labels_from_ps(ps: PrintSettings) -> dict:
    return {
        "width_mm": ps.ozon_width_mm or 58,
        "height_mm": ps.ozon_height_mm or 40,
        "rotate": ps.ozon_label_rotate if ps.ozon_label_rotate is not None else 90,
    }


def _wb_labels_from_ps(ps: PrintSettings) -> dict:
    return {
        "width_mm": ps.wb_width_mm or 58,
        "height_mm": ps.wb_height_mm or 40,
        "rotate": ps.wb_label_rotate if ps.wb_label_rotate is not None else 90,
    }


def _kiz_labels_from_ps(ps: PrintSettings) -> dict:
    return {
        "width_mm": ps.kiz_width_mm or 40,
        "height_mm": ps.kiz_height_mm or 35,
        "rotate": ps.kiz_rotate or 0,
    }


def _barcode_labels_from_ps(ps: PrintSettings) -> dict:
    return {
        "rotate": ps.barcode_rotate or 0,
    }


@router.get("", response_model=PrintSettingsResponse)
def get_print_settings(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Получить настройки печати"""
    ps = db.query(PrintSettings).filter(
        PrintSettings.user_id == current_user.id,
    ).first()
    if not ps:
        return PrintSettingsResponse(
            printer_dpi=203,
            print_scale="fit",
            ozon_labels={"width_mm": 58, "height_mm": 40, "rotate": 90},
            wb_labels={"width_mm": 58, "height_mm": 40, "rotate": 90},
            kiz_labels={"width_mm": 40, "height_mm": 35, "rotate": 0},
            barcode_labels={"rotate": 0},
        )
    return PrintSettingsResponse(
        default_printer=ps.default_printer,
        label_format=ps.label_format,
        label_template=ps.label_template,
        auto_print_on_click=ps.auto_print_on_click == "true" if ps.auto_print_on_click else None,
        auto_print_kiz_duplicate=ps.auto_print_kiz_duplicate == "true" if ps.auto_print_kiz_duplicate else None,
        printer_dpi=ps.printer_dpi or 203,
        print_scale=ps.print_scale or "fit",
        ozon_labels=_ozon_labels_from_ps(ps),
        wb_labels=_wb_labels_from_ps(ps),
        kiz_labels=_kiz_labels_from_ps(ps),
        barcode_labels=_barcode_labels_from_ps(ps),
    )


@router.patch("", response_model=PrintSettingsResponse)
def update_print_settings(
    data: PrintSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Обновить настройки печати"""
    ps = db.query(PrintSettings).filter(
        PrintSettings.user_id == current_user.id,
    ).first()
    if not ps:
        ps = PrintSettings(user_id=current_user.id)
        db.add(ps)
        db.flush()
    if data.default_printer is not None:
        ps.default_printer = data.default_printer
    if data.label_format is not None:
        ps.label_format = data.label_format
    if data.label_template is not None:
        ps.label_template = data.label_template
    if data.auto_print_on_click is not None:
        ps.auto_print_on_click = "true" if data.auto_print_on_click else "false"
    if data.auto_print_kiz_duplicate is not None:
        ps.auto_print_kiz_duplicate = "true" if data.auto_print_kiz_duplicate else "false"
    if data.ozon_labels is not None:
        if data.ozon_labels.width_mm is not None:
            ps.ozon_width_mm = max(40, min(data.ozon_labels.width_mm, 120))
        if data.ozon_labels.height_mm is not None:
            ps.ozon_height_mm = max(30, min(data.ozon_labels.height_mm, 120))
        if data.ozon_labels.rotate is not None:
            ps.ozon_label_rotate = data.ozon_labels.rotate if data.ozon_labels.rotate in (0, 90, 180, 270) else 0
    if data.wb_labels is not None:
        if data.wb_labels.width_mm is not None:
            ps.wb_width_mm = max(40, min(data.wb_labels.width_mm, 120))
        if data.wb_labels.height_mm is not None:
            ps.wb_height_mm = max(30, min(data.wb_labels.height_mm, 120))
        if data.wb_labels.rotate is not None:
            ps.wb_label_rotate = data.wb_labels.rotate if data.wb_labels.rotate in (0, 90, 180, 270) else 0
    if data.kiz_labels is not None:
        if data.kiz_labels.width_mm is not None:
            ps.kiz_width_mm = max(20, min(data.kiz_labels.width_mm, 100))
        if data.kiz_labels.height_mm is not None:
            ps.kiz_height_mm = max(20, min(data.kiz_labels.height_mm, 100))
        if data.kiz_labels.rotate is not None:
            ps.kiz_rotate = data.kiz_labels.rotate if data.kiz_labels.rotate in (0, 90, 180, 270) else 0
    if data.barcode_labels is not None:
        if data.barcode_labels.rotate is not None:
            ps.barcode_rotate = data.barcode_labels.rotate if data.barcode_labels.rotate in (0, 90, 180, 270) else 0
    if data.printer_dpi is not None:
        if data.printer_dpi in (203, 300):
            ps.printer_dpi = data.printer_dpi
    if data.print_scale is not None:
        if data.print_scale in ("fit", "shrink", "noscale"):
            ps.print_scale = data.print_scale
    db.commit()
    db.refresh(ps)
    return PrintSettingsResponse(
        default_printer=ps.default_printer,
        label_format=ps.label_format,
        label_template=ps.label_template,
        auto_print_on_click=ps.auto_print_on_click == "true" if ps.auto_print_on_click else None,
        auto_print_kiz_duplicate=ps.auto_print_kiz_duplicate == "true" if ps.auto_print_kiz_duplicate else None,
        printer_dpi=ps.printer_dpi or 203,
        print_scale=ps.print_scale or "fit",
        ozon_labels=_ozon_labels_from_ps(ps),
        wb_labels=_wb_labels_from_ps(ps),
        kiz_labels=_kiz_labels_from_ps(ps),
        barcode_labels=_barcode_labels_from_ps(ps),
    )


@router.get("/test-label")
def get_test_label(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Тестовая этикетка 58×40 мм для калибровки печати.
    PDF: рамка по периметру, подписи «верх/низ/лево/право», текст ТЕСТ.
    """
    import io

    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
    w_mm = (ps.wb_width_mm or 58) if ps else 58
    h_mm = (ps.wb_height_mm or 40) if ps else 40

    label_w = w_mm * mm
    label_h = h_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))

    # Рамка 1 мм от краёв
    margin = 1 * mm
    c.rect(margin, margin, label_w - 2 * margin, label_h - 2 * margin)

    # Подписи сторон
    c.setFont("Helvetica", 6)
    c.drawCentredString(label_w / 2, label_h - margin - 2 * mm, "ВЕРХ")
    c.drawCentredString(label_w / 2, margin + 2 * mm, "НИЗ")
    c.drawString(margin + 1 * mm, label_h / 2 - 2 * mm, "Л")
    c.drawRightString(label_w - margin - 1 * mm, label_h / 2 - 2 * mm, "П")

    # Центральный текст
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(label_w / 2, label_h / 2 - 4 * mm, "ТЕСТ")
    c.setFont("Helvetica", 8)
    c.drawCentredString(label_w / 2, label_h / 2 - 8 * mm, f"{w_mm}×{h_mm} мм")

    c.save()
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=test-label.pdf"},
    )
