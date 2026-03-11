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
    db.commit()
    db.refresh(ps)
    return PrintSettingsResponse(
        default_printer=ps.default_printer,
        label_format=ps.label_format,
        label_template=ps.label_template,
        auto_print_on_click=ps.auto_print_on_click == "true" if ps.auto_print_on_click else None,
        auto_print_kiz_duplicate=ps.auto_print_kiz_duplicate == "true" if ps.auto_print_kiz_duplicate else None,
        ozon_labels=_ozon_labels_from_ps(ps),
        wb_labels=_wb_labels_from_ps(ps),
        kiz_labels=_kiz_labels_from_ps(ps),
        barcode_labels=_barcode_labels_from_ps(ps),
    )


@router.get("/test-label")
def get_test_label(
    current_user: User = CurrentUser,
):
    """
    Тестовая этикетка для проверки печати.
    Возвращает PNG с QR-кодом «ТЕСТ».
    """
    import io
    import qrcode

    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data("ТЕСТ")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": "inline; filename=test-label.png"},
    )
