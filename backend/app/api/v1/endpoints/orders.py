"""
API endpoints для заказов и синхронизации
"""
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.utils.logger import logger
from app.core.dependencies import CurrentAdminUser, CurrentUser
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.order import Order, OrderStatus
from app.models.scanned_kiz import ScannedKiz
from app.models.print_settings import PrintSettings
from app.models.user import User, UserRole
from app.models.user_marketplace_access import UserMarketplaceAccess
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCompleteRequest, OrderProductItem, OrderResponse, OrdersListResponse
from app.services.marketplace.wildberries import WildberriesClient
from app.services.order_complete_service import OrderCompleteService
from app.services.order_sync_service import OrderSyncService

router = APIRouter(prefix="/orders", tags=["Orders"])


def _get_effective_user_and_access(
    current_user: User, db: Session
) -> tuple[int, Optional[List[int]]]:
    """
    Для упаковщика (packer) с owner_id возвращает ID владельца-администратора
    и список разрешённых marketplace_id (None = все).
    Для администратора возвращает его собственный ID и None (без ограничений).
    """
    if current_user.role == UserRole.PACKER and current_user.owner_id:
        effective_user_id = current_user.owner_id
        rows = (
            db.query(UserMarketplaceAccess)
            .filter(UserMarketplaceAccess.user_id == current_user.id)
            .all()
        )
        allowed = [r.marketplace_id for r in rows] if rows else None
        return effective_user_id, allowed
    return current_user.id, None


def _product_image_url_for_order(o: Order) -> Optional[str]:
    """URL фото: из extra_data (Content API или CDN), fallback — прокси по nm_id."""
    ed = o.extra_data or {}
    url = ed.get("product_image_url")
    if url and isinstance(url, str) and url.strip():
        return url  # Прямой URL от Content API или CDN
    if o.marketplace and o.marketplace.type.value == "wildberries":
        nm_id = ed.get("nm_id")
        if nm_id is not None:
            return f"/orders/product-image?nm_id={nm_id}"  # Прокси fallback
    return None


def _sanitize_size(s: Optional[str]) -> Optional[str]:
    """Убрать сырую размерную сетку / JSON — оставить только читаемый размер."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) > 80:
        return None
    if "widgetName" in s or "tcTable" in s or "IcTable" in s or "Размерная сетка" in s:
        return None
    if s.startswith("{") or s.startswith("["):
        return None
    return s if s else None


def _ozon_product_size(
    p: dict, order_id: Optional[int] = None, offer_id: str = "", order_size: Optional[str] = None
) -> Optional[str]:
    """
    Размер товара Ozon из product dict.
    Приоритет: p.size → dimensions → size_name → order_size (размер на уровне заказа).
    """
    raw = p.get("size")
    if raw:
        return _sanitize_size(raw)
    dims = p.get("dimensions")
    if isinstance(dims, dict):
        raw = dims.get("size_name") or dims.get("size")
    else:
        raw = p.get("size_name")
    result = _sanitize_size(raw)
    if result:
        return result
    if order_size:
        return _sanitize_size(order_size)
    logger.debug(
        "Ozon size MISSING: order_id=%s offer_id=%s tried: p.size=%r dims=%r p.size_name=%r product_keys=%s",
        order_id, offer_id or p.get("offer_id"),
        p.get("size"), p.get("dimensions"), p.get("size_name"),
        list(p.keys()),
    )
    return None


def _order_products(o: Order) -> list[OrderProductItem]:
    """Список товаров в заказе (Ozon: несколько в одном posting)."""
    if not o.marketplace or o.marketplace.type.value != "ozon":
        return []
    ed = o.extra_data or {}
    prods = ed.get("products", [])
    order_size = _sanitize_size(ed.get("size"))
    return [
        OrderProductItem(
            offer_id=str(p.get("offer_id", "")),
            name=str(p.get("name", "")),
            quantity=int(p.get("quantity", 1)),
            image_url=str(p.get("image_url", "")),
            size=_ozon_product_size(
                p, order_id=o.id, offer_id=str(p.get("offer_id", "")), order_size=order_size
            ),
        )
        for p in prods
    ]


class OrderCompleteRequest(BaseModel):
    """Запрос на отметку «Собрано»"""
    kiz_code: Optional[str] = None


@router.get("", response_model=OrdersListResponse)
def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    marketplace_ids: Optional[List[int]] = Query(None, description="ID маркетплейсов (множественный выбор)"),
    marketplace_types: Optional[List[str]] = Query(None, description="Типы: ozon, wildberries (множественный выбор)"),
    warehouse_ids: Optional[List[int]] = Query(None, description="ID складов (множественный выбор)"),
    status: Optional[str] = None,
    search: Optional[str] = Query(None, description="Поиск по артикулу, названию, номеру заказа"),
    sort_by: str = Query("marketplace_created_at", description="marketplace_created_at, article, product_name"),
    sort_desc: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Список заказов для вкладки «Сборка».
    
    Фильтры: marketplace_ids, marketplace_types (ozon/wildberries), warehouse_ids, status, search.
    """
    status_enum = None
    if status:
        try:
            status_enum = OrderStatus(status)
        except ValueError:
            pass
    effective_user_id, packer_allowed_mp_ids = _get_effective_user_and_access(current_user, db)
    order_repo = OrderRepository(db)
    total = order_repo.get_list_count(
        user_id=effective_user_id,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        status=status_enum,
        search=search,
        packer_allowed_marketplace_ids=packer_allowed_mp_ids,
    )
    orders = order_repo.get_list(
        user_id=effective_user_id,
        skip=skip,
        limit=limit,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        status=status_enum,
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
        packer_allowed_marketplace_ids=packer_allowed_mp_ids,
    )
    items = [
        OrderResponse(
            id=o.id,
            external_id=o.external_id,
            posting_number=o.posting_number,
            article=o.article,
            product_name=o.product_name,
            quantity=o.quantity,
            status=o.status.value,
            marketplace_id=o.marketplace_id,
            marketplace_type=o.marketplace.type.value if o.marketplace else None,
            warehouse_id=o.warehouse_id,
            warehouse_name=o.warehouse_name,
            warehouse_color=o.warehouse.color if o.warehouse else None,
            product_image_url=_product_image_url_for_order(o),
            size=_sanitize_size((o.extra_data or {}).get("size")),
            marketplace_created_at=o.marketplace_created_at,
            completed_at=o.completed_at,
            assigned_to_id=o.assigned_to_id,
            assigned_at=o.assigned_at,
            assigned_to_name=o.assigned_to_user.full_name if o.assigned_to_user else None,
            is_locked_by_me=o.is_locked_by(current_user.id),
            is_locked_by_other=o.is_locked_by_other(current_user.id),
            is_kiz_enabled=o.marketplace.is_kiz_enabled if o.marketplace else False,
            products=_order_products(o),
        )
        for o in orders
    ]
    return OrdersListResponse(items=items, total=total)


@router.get("/completed", response_model=OrdersListResponse)
def list_completed_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    marketplace_ids: Optional[List[int]] = Query(None),
    marketplace_types: Optional[List[str]] = Query(None),
    warehouse_ids: Optional[List[int]] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("completed_at", description="completed_at, marketplace_created_at, article"),
    sort_desc: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Список собранных заказов (отмечены «Собрано» в приложении).
    Для секции «Собрано» на странице сборки.
    """
    effective_user_id, packer_allowed_mp_ids = _get_effective_user_and_access(current_user, db)
    order_repo = OrderRepository(db)
    total = order_repo.get_completed_count(
        user_id=effective_user_id,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        search=search,
    )
    orders = order_repo.get_completed_list(
        user_id=effective_user_id,
        skip=skip,
        limit=limit,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )
    items = [
        OrderResponse(
            id=o.id,
            external_id=o.external_id,
            posting_number=o.posting_number,
            article=o.article,
            product_name=o.product_name,
            quantity=o.quantity,
            status=o.status.value,
            marketplace_id=o.marketplace_id,
            marketplace_type=o.marketplace.type.value if o.marketplace else None,
            warehouse_id=o.warehouse_id,
            warehouse_name=o.warehouse_name,
            warehouse_color=o.warehouse.color if o.warehouse else None,
            product_image_url=_product_image_url_for_order(o),
            size=_sanitize_size((o.extra_data or {}).get("size")),
            marketplace_created_at=o.marketplace_created_at,
            completed_at=o.completed_at,
            assigned_to_id=o.assigned_to_id,
            assigned_at=o.assigned_at,
            assigned_to_name=o.assigned_to_user.full_name if o.assigned_to_user else None,
            is_locked_by_me=o.is_locked_by(current_user.id),
            is_locked_by_other=o.is_locked_by_other(current_user.id),
            is_kiz_enabled=o.marketplace.is_kiz_enabled if o.marketplace else False,
            products=_order_products(o),
        )
        for o in orders
    ]
    return OrdersListResponse(items=items, total=total)


@router.get("/stats")
def get_orders_stats(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Общая статистика по заказам для вкладки «Учетная запись».
    """
    order_repo = OrderRepository(db)
    return order_repo.get_stats(user_id=current_user.id)


@router.get("/kiz-scans")
def get_kiz_scans_count(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Количество отсканированных КИЗ в таблице пользователя.
    Для отображения в UI (счётчик перед скачиванием).
    """
    count = (
        db.query(ScannedKiz)
        .filter(ScannedKiz.user_id == current_user.id)
        .count()
    )
    return {"count": count}


@router.delete("/kiz-scans")
def clear_kiz_scans(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Очистить таблицу отсканированных КИЗ.
    Начать новый рабочий день с чистой таблицей.
    """
    deleted = (
        db.query(ScannedKiz)
        .filter(ScannedKiz.user_id == current_user.id)
        .delete()
    )
    db.commit()
    return {"ok": True, "deleted": deleted}


class KizScanAddRequest(BaseModel):
    """Добавить КИЗ в таблицу (свободное сканирование без заказа)."""
    kiz_code: str
    external_id: Optional[str] = None
    posting_number: Optional[str] = None
    marketplace_id: Optional[int] = None


@router.post("/kiz-scans")
def add_kiz_scan(
    data: KizScanAddRequest,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Добавить КИЗ в таблицу отсканированных (свободное сканирование).
    При «Собрано» КИЗ добавляется автоматически. Этот endpoint — для ручного добавления.
    """
    kiz = (data.kiz_code or "").strip()[:31]
    if not kiz:
        raise HTTPException(400, detail="kiz_code required")
    if data.marketplace_id:
        mp = db.query(Marketplace).filter(
            Marketplace.id == data.marketplace_id,
            Marketplace.user_id == current_user.id,
        ).first()
        if not mp:
            raise HTTPException(404, detail="Marketplace not found")
    sk = ScannedKiz(
        user_id=current_user.id,
        kiz_code=kiz,
        external_id=data.external_id,
        posting_number=data.posting_number,
        marketplace_id=data.marketplace_id,
    )
    db.add(sk)
    db.commit()
    return {"ok": True, "id": sk.id}


@router.get("/kiz-export")
def kiz_export(
    marketplace_id: Optional[int] = Query(None, description="Фильтр по маркетплейсу (обязателен для формата WB/Ozon)"),
    export_format: str = Query("xlsx", description="xlsx | txt"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Выгрузка отсканированных КИЗ из таблицы пользователя.
    
    Источник: таблица scanned_kiz (накапливается при «Собрано» и свободном сканировании).
    
    Формат зависит от маркетплейса (marketplace_id):
    - WB: № задания, Стикер, КИЗ (для массовой загрузки в WB)
    - Ozon: Номер отправления, КИЗ
    - Без marketplace_id: общий формат
    """
    from datetime import datetime
    from io import BytesIO

    query = (
        db.query(ScannedKiz)
        .options(joinedload(ScannedKiz.marketplace))
        .filter(ScannedKiz.user_id == current_user.id)
    )
    if marketplace_id:
        query = query.filter(ScannedKiz.marketplace_id == marketplace_id)
    rows = query.order_by(ScannedKiz.created_at.asc()).limit(10000).all()

    mp_type = None
    if marketplace_id:
        mp = db.query(Marketplace).filter(
            Marketplace.id == marketplace_id,
            Marketplace.user_id == current_user.id,
        ).first()
        if mp:
            mp_type = mp.type
    elif rows and rows[0].marketplace:
        mp_type = rows[0].marketplace.type

    if export_format == "txt":
        lines = [(r.kiz_code or "")[:31] for r in rows]
        content = "\n".join(lines).encode("utf-8")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=kiz-export-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.txt",
            },
        )

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active

    if mp_type == MarketplaceType.WILDBERRIES:
        ws.title = "Сборочные задания"
        ws.append(["Магазин", "№ задания", "Стикер", "КИЗ"])
        for r in rows:
            shop = r.marketplace.name if r.marketplace else ""
            ws.append([shop, r.external_id or "", r.posting_number or "", (r.kiz_code or "")[:31]])
        filename = f"kiz-export-WB-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.xlsx"
    elif mp_type == MarketplaceType.OZON:
        ws.title = "КИЗ Ozon"
        ws.append(["Магазин", "Номер отправления", "КИЗ"])
        for r in rows:
            shop = r.marketplace.name if r.marketplace else ""
            ws.append([shop, r.posting_number or "", (r.kiz_code or "")[:31]])
        filename = f"kiz-export-Ozon-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.xlsx"
    else:
        ws.title = "КИЗ"
        ws.append(["Магазин", "КИЗ", "№ задания", "Стикер", "Маркетплейс"])
        for r in rows:
            shop = r.marketplace.name if r.marketplace else ""
            mp_val = r.marketplace.type.value if r.marketplace else ""
            ws.append([shop, (r.kiz_code or "")[:31], r.external_id or "", r.posting_number or "", mp_val])
        filename = f"kiz-export-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.xlsx"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


MM_TO_PT = 2.834645669  # 1 мм = 2.834645669 pt (PDF points)


def _ozon_fbs_to_png(
    pdf_bytes: bytes,
    width_mm: int = 58,
    height_mm: int = 40,
    rotate: int = 90,
) -> bytes:
    """
    Ozon FBS → PNG для превью. Размер 100% от этикетки.
    """
    import io

    from PIL import Image as PILImage, ImageChops
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(pdf_bytes, dpi=203)  # DPI термопринтера для консистентности
    if not images:
        raise ValueError("PDF returned no pages")
    img = images[0].convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")

    # Поворот по настройке: всегда применяем при deg != 0 (как в _ozon_fbs_to_standard_label),
    # иначе превью не совпадает с PDF при рендере pdf2image в альбоме (iw > ih).
    deg = rotate if (rotate and rotate % 90 == 0) else (90 if rotate else 0)
    if deg:
        if deg == 90:
            img = img.transpose(PILImage.Transpose.ROTATE_270)
        elif deg == 270:
            img = img.transpose(PILImage.Transpose.ROTATE_90)
        elif deg == 180:
            img = img.transpose(PILImage.Transpose.ROTATE_180)
        iw, ih = img.size

    try:
        bg = PILImage.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox and (bbox[2] - bbox[0]) > 10 and (bbox[3] - bbox[1]) > 10:
            img = img.crop(bbox)
            iw, ih = img.size
    except Exception:
        pass

    # Целевой размер в пикселях: 100% от 58×40 мм при 96 DPI (превью)
    MM_TO_INCH = 1 / 25.4
    DPI = 96
    target_w_pt = (width_mm * MM_TO_INCH * DPI)
    target_h_pt = (height_mm * MM_TO_INCH * DPI)
    scale = min(target_w_pt / iw, target_h_pt / ih, 1.0)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
    out = PILImage.new("RGB", (new_w, new_h), (255, 255, 255))
    out.paste(img, (0, 0))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _ozon_pdf_set_cropbox_to_content(pdf_bytes: bytes, dpi_low: int = 120) -> Optional[bytes]:
    """
    Вычислить bbox контента по первому рендеру, установить CropBox в PDF, вернуть новый PDF.
    pdf2image с use_cropbox=True тогда отдаст уже обрезанную страницу. Без новых зависимостей (pypdf + pdf2image).
    """
    import io

    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    from pdf2image import convert_from_bytes

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None
        page = reader.pages[0]
        mb = page.mediabox
        page_w_pt = float(mb.width) if hasattr(mb, "width") else (float(mb.right) - float(mb.left))
        page_h_pt = float(mb.height) if hasattr(mb, "height") else (float(mb.top) - float(mb.bottom))
    except Exception as e:
        logger.debug("Ozon PDF cropbox: could not read PDF: %s", e)
        return None

    try:
        low_images = convert_from_bytes(pdf_bytes, dpi=dpi_low, first_page=1, last_page=1)
        if not low_images:
            return None
        img = low_images[0].convert("RGB")
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            return None
        pix = img.load()
        thresh = 250
        min_x, min_y, max_x, max_y = iw, ih, 0, 0
        for y in range(ih):
            for x in range(iw):
                p = pix[x, y]
                v = (p if isinstance(p, int) else max(p[:3]))
                if v < thresh:
                    min_x, min_y = min(min_x, x), min(min_y, y)
                    max_x, max_y = max(max_x, x), max(max_y, y)
        if max_x < min_x or max_y < min_y or (max_x - min_x) < 10 or (max_y - min_y) < 10:
            return None
        # Пиксели → пункты PDF (origin в PDF — нижний левый угол; в картинке y=0 — верх)
        pt_per_px = 72.0 / dpi_low
        left_pt = min_x * pt_per_px
        right_pt = (max_x + 1) * pt_per_px
        top_pt = page_h_pt - min_y * pt_per_px
        bottom_pt = page_h_pt - (max_y + 1) * pt_per_px
        # Не выходить за пределы страницы
        left_pt = max(0, min(left_pt, page_w_pt - 1))
        right_pt = max(left_pt + 1, min(right_pt, page_w_pt))
        bottom_pt = max(0, min(bottom_pt, page_h_pt - 1))
        top_pt = max(bottom_pt + 1, min(top_pt, page_h_pt))

        writer = PdfWriter()
        writer.add_page(page)
        writer.pages[0].cropbox = RectangleObject((left_pt, bottom_pt, right_pt, top_pt))
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        logger.info(
            "Ozon PDF cropbox: set to (%.1f, %.1f, %.1f, %.1f) pt",
            left_pt, bottom_pt, right_pt, top_pt,
        )
        return buf.getvalue()
    except Exception as e:
        logger.debug("Ozon PDF cropbox: failed: %s", e)
        return None


def _ozon_fbs_to_standard_label(
    pdf_bytes: bytes,
    width_mm: int = 58,
    height_mm: int = 40,
    rotate: int = 90,
    dpi: int = 203,
) -> bytes:
    """
    Этикетка Ozon FBS: не редактируем исходный PDF, а пересоздаём страницу.
    1) Опционально: выставляем CropBox по контенту (рендер → bbox → pypdf) и рендерим с use_cropbox=True.
    2) Поворачиваем и при необходимости подрезаем белые поля.
    3) Создаём новый PDF-фрейм 58×40 мм и рисуем контент в верхнем левом углу.
    """
    import io

    from PIL import Image
    from pdf2image import convert_from_bytes
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    # Сначала пробуем обрезать страницу на уровне PDF (CropBox), чтобы рендер сразу без полей
    pdf_to_render = pdf_bytes
    use_cropbox = False
    cropped = _ozon_pdf_set_cropbox_to_content(pdf_bytes, dpi_low=120)
    if cropped:
        pdf_to_render = cropped
        use_cropbox = True

    dpi_val = max(150, min(dpi, 300))
    try:
        images = convert_from_bytes(
            pdf_to_render, dpi=dpi_val, use_pdftocairo=False, use_cropbox=use_cropbox,
        )
    except Exception:
        try:
            images = convert_from_bytes(
                pdf_to_render, dpi=dpi_val, use_pdftocairo=True, use_cropbox=use_cropbox,
            )
        except Exception:
            images = convert_from_bytes(pdf_to_render, dpi=dpi_val)
    if not images:
        raise ValueError("PDF returned no pages")

    # Размер нового фрейма (страницы), который мы создаём с нуля
    frame_w_pt = width_mm * mm
    frame_h_pt = height_mm * mm
    margin_left_pt = 1.0 * mm
    margin_top_pt = 0

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(frame_w_pt, frame_h_pt))

    for idx, img in enumerate(images):
        if idx > 0:
            c.showPage()
        img = img.convert("RGB")
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            continue

        # Поворот растра по настройке (0 / 90 / 180 / 270; при портрете и альбомном стикере — 90 по умолчанию)
        deg: Optional[int]
        if rotate in (0, 90, 180, 270):
            deg = rotate
        elif width_mm > height_mm and ih > iw:
            deg = 90
        else:
            deg = 0
        logger.info(
            "Ozon FBS label: page %s size %sx%s rotate_setting=%s applied_deg=%s",
            idx + 1, iw, ih, rotate, deg,
        )
        if deg:
            if deg == 90:
                img = img.transpose(Image.Transpose.ROTATE_270)
            elif deg == 270:
                img = img.transpose(Image.Transpose.ROTATE_90)
            elif deg == 180:
                img = img.transpose(Image.Transpose.ROTATE_180)
            iw, ih = img.size

        # Убираем белые поля: bbox по порогу «не белый» (max < 250), иначе почти белые пиксели не обрезаются
        try:
            pix = img.load()
            thresh = 250
            min_x, min_y, max_x, max_y = iw, ih, 0, 0
            for y in range(ih):
                for x in range(iw):
                    p = pix[x, y]
                    v = (p if isinstance(p, int) else max(p[:3]))
                    if v < thresh:
                        min_x, min_y = min(min_x, x), min(min_y, y)
                        max_x, max_y = max(max_x, x), max(max_y, y)
            if max_x >= min_x and max_y >= min_y and (max_x - min_x) > 10 and (max_y - min_y) > 10:
                img = img.crop((min_x, min_y, max_x + 1, max_y + 1))
                iw, ih = img.size
        except Exception:
            pass

        # Первая строка с любым тёмным пикселем — верх контента (убираем оставшийся белый пояс сверху)
        try:
            pix = img.load()
            top_thresh = 253
            y_top = 0
            for y in range(ih):
                for x in range(iw):
                    p = pix[x, y]
                    if (p if isinstance(p, int) else max(p[:3])) < top_thresh:
                        y_top = y
                        break
                else:
                    continue
                break
            if y_top > 0 and ih - y_top > 15:
                img = img.crop((0, y_top, iw, ih))
                iw, ih = img.size
        except Exception:
            pass

        # Размещение в новом фрейме: контент прижат к верхнему левому углу (слева отступ 1 мм, сверху 0)
        usable_w = frame_w_pt - margin_left_pt
        usable_h = frame_h_pt - margin_top_pt
        scale = min(usable_w / iw, usable_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        # В ReportLab (x, y) у drawImage — нижний левый угол; чтобы верх контента был у верха страницы: y = frame_h - draw_h
        x_place = margin_left_pt
        y_place = frame_h_pt - draw_h

        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)

        c.drawImage(
            ImageReader(img_buf),
            x_place, y_place, width=draw_w, height=draw_h,
            preserveAspectRatio=True,
        )

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _rotate_pdf(pdf_bytes: bytes, degrees: int) -> bytes:
    """Повернуть все страницы PDF на degrees градусов (0/90/180/270)."""
    if not degrees or degrees % 90 != 0:
        return pdf_bytes
    import io

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page.rotate(degrees))  # rotate() возвращает новую страницу
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.getvalue()


def _crop_image_to_content(img: "Image.Image", white_thresh: int = 252, min_fraction: float = 0.01) -> "Image.Image":
    """Обрезать белые поля: по getbbox и по первой строке с существенным контентом сверху."""
    from PIL import Image
    from PIL import ImageChops

    img = img.convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return img
    try:
        bg = ImageChops.difference(img, Image.new(img.mode, img.size, (255, 255, 255)))
        bbox = bg.getbbox()
        if bbox and (bbox[2] - bbox[0]) > 10 and (bbox[3] - bbox[1]) > 10:
            img = img.crop(bbox)
            iw, ih = img.size
    except Exception:
        pass
    try:
        pix = img.load()
        for y in range(ih):
            dark_count = sum(
                1 for x in range(iw)
                if (pix[x, y] if isinstance(pix[x, y], int) else max(pix[x, y][:3])) < white_thresh
            )
            if dark_count >= max(2, int(iw * min_fraction)):
                if y > 0 and ih - y > 20:
                    img = img.crop((0, y, iw, ih))
                break
    except Exception:
        pass
    return img


def _rotate_pdf_via_image(
    pdf_bytes: bytes,
    degrees: int,
    width_mm: int = 58,
    height_mm: int = 40,
    dpi: int = 203,
) -> bytes:
    """
    Поворот PDF через рендер в изображение (для PDF от ReportLab, где pypdf может падать).
    При 90/270 размер страницы меняется на height_mm×width_mm.
    После поворота обрезаем белое и размещаем контент в верхнем левом углу страницы (без отступа вниз).
    """
    if not degrees or degrees % 90 != 0:
        return pdf_bytes
    import io

    from PIL import Image
    from pdf2image import convert_from_bytes
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    try:
        images = convert_from_bytes(pdf_bytes, dpi=max(150, min(dpi, 300)))
    except Exception as e:
        logger.warning("Barcode PDF rotate via image: convert_from_bytes failed: %s", e)
        return pdf_bytes
    if not images:
        return pdf_bytes

    if degrees in (90, 270):
        page_w_pt = height_mm * mm
        page_h_pt = width_mm * mm
    else:
        page_w_pt = width_mm * mm
        page_h_pt = height_mm * mm

    margin_left_pt = 1.0 * mm
    margin_top_pt = 0

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w_pt, page_h_pt))
    for idx, img in enumerate(images):
        if idx > 0:
            c.showPage()
        img = img.convert("RGB")
        if degrees == 90:
            img = img.transpose(Image.Transpose.ROTATE_270)
        elif degrees == 270:
            img = img.transpose(Image.Transpose.ROTATE_90)
        elif degrees == 180:
            img = img.transpose(Image.Transpose.ROTATE_180)
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            continue
        # Обрезаем белое, чтобы контент прижать к углу (как у ФБС этикетки)
        img = _crop_image_to_content(img)
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            continue
        usable_w = page_w_pt - margin_left_pt
        usable_h = page_h_pt - margin_top_pt
        scale = min(usable_w / iw, usable_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        x_place = margin_left_pt
        y_place = page_h_pt - draw_h
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)
        c.drawImage(ImageReader(img_buf), x_place, y_place, width=draw_w, height=draw_h, preserveAspectRatio=True)
    c.save()
    buf.seek(0)
    return buf.getvalue()


def _generate_kiz_label_pdf(kiz_full: str, kiz_31: str, width_mm: int = 40, height_mm: int = 35) -> bytes:
    """
    PDF этикетки-дубля КИЗ: DataMatrix (полный код) + 31 символ текстом снизу.
    Размер DataMatrix ~22×22 мм по инструкции WB.
    GS1: > в выводе сканера = GS (ASCII 29), добавляем FNC1 (ASCII 232) в начало.
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import createBarcodeDrawing
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    # GS1 DataMatrix: > → GS, FNC1 в начало (если нет)
    data_for_dm = kiz_full.replace(">", "\x1d")
    if not data_for_dm.startswith("\xe8"):
        data_for_dm = "\xe8" + data_for_dm

    dm = createBarcodeDrawing("ECC200DataMatrix", value=data_for_dm)

    dm_size_mm = min(width_mm - 4, height_mm - 12, 22)  # DataMatrix вписывается в этикетку
    label_w = width_mm * mm
    label_h = height_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))
    margin = 2 * mm

    # DataMatrix размер
    scale = (dm_size_mm * mm) / max(dm.width, dm.height)
    dm_w = dm.width * scale
    dm_h = dm.height * scale

    # 31 символ: подбираем размер шрифта
    text = kiz_31[:31]
    from reportlab.pdfbase.pdfmetrics import stringWidth
    max_w = label_w - 2 * margin
    font_size = 5
    for fs in (5, 4, 3):
        if stringWidth(text, "Helvetica", fs) <= max_w:
            font_size = fs
            break

    # Вертикальное центрирование: DataMatrix + 2mm зазор + текст
    gap = 2 * mm
    total_h = dm_h + gap + font_size  # font_size в pt ≈ высота строки
    y_dm_bottom = (label_h - total_h) / 2 + font_size + gap  # нижняя граница DM
    ty = (label_h - total_h) / 2  # базовая линия текста

    # DataMatrix (центрирован горизонтально)
    c.saveState()
    c.translate((label_w - dm_w) / 2, y_dm_bottom)
    c.scale(scale, scale)
    renderPDF.draw(dm, c, 0, 0)
    c.restoreState()

    # 31 символ текстом (центрирован горизонтально)
    c.setFont("Helvetica", font_size)
    c.drawCentredString(label_w / 2, ty, text)

    c.save()
    buf.seek(0)
    return buf.getvalue()


@router.get("/kiz-label")
def get_kiz_label(
    kiz_code: str = Query(..., min_length=1, description="Код КИЗ (маркировка, полный или 31 символ)"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Этикетка-дубль КИЗ для печати после сканирования.
    DataMatrix с полным КИЗ + 31 символ текстом снизу (для ручного ввода).
    Возвращает PDF.
    """
    ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
    kiz_w = (ps.kiz_width_mm or 40) if ps else 40
    kiz_h = (ps.kiz_height_mm or 35) if ps else 35
    kiz_rot = (ps.kiz_rotate or 0) if ps else 0

    kiz = kiz_code.strip()
    kiz_31 = kiz[:31]
    try:
        pdf_bytes = _generate_kiz_label_pdf(kiz, kiz_31, width_mm=kiz_w, height_mm=kiz_h)
    except Exception as e:
        logger.warning("DataMatrix failed, fallback to QR: %s", e)
        import io
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(kiz_31)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename=kiz-{kiz_31[:20]}.png"},
        )
    if kiz_rot:
        try:
            pdf_bytes = _rotate_pdf(pdf_bytes, kiz_rot)
        except Exception as _re:
            logger.warning(f"KIZ PDF rotate failed: {_re}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=kiz-{kiz_31[:20]}.pdf"},
    )


@router.get("/product-image")
async def get_product_image(
    nm_id: int = Query(..., description="Артикул WB (nmId)"),
):
    """
    Прокси изображения товара WB. Пробует несколько URL (webp/jpg, wbbasket/wb.ru).
    nm_id — публичный артикул товара, авторизация не требуется для img src.
    """
    urls = WildberriesClient.build_product_image_urls(nm_id)
    if not urls:
        raise HTTPException(400, detail="Invalid nm_id")
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    media = "image/webp" if ".webp" in url else "image/jpeg"
                    return Response(content=r.content, media_type=media)
            except Exception:
                continue
    raise HTTPException(404, detail="Image not found")


def _get_order_for_user(order_id: int, current_user: User, db: Session) -> Order:
    """Получить заказ с проверкой доступа"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, detail="Order not found")
    mp = order.marketplace
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Order not found")
    return order


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Получить заказ по ID (с информацией о блокировке)"""
    order = _get_order_for_user(order_id, current_user, db)
    return OrderResponse(
        id=order.id,
        external_id=order.external_id,
        posting_number=order.posting_number,
        article=order.article,
        product_name=order.product_name,
        quantity=order.quantity,
        status=order.status.value,
        marketplace_id=order.marketplace_id,
        marketplace_type=order.marketplace.type.value if order.marketplace else None,
        warehouse_id=order.warehouse_id,
        warehouse_name=order.warehouse_name,
        warehouse_color=order.warehouse.color if order.warehouse else None,
        product_image_url=_product_image_url_for_order(order),
        size=_sanitize_size((order.extra_data or {}).get("size")),
        marketplace_created_at=order.marketplace_created_at,
        completed_at=order.completed_at,
        assigned_to_id=order.assigned_to_id,
        assigned_at=order.assigned_at,
        assigned_to_name=order.assigned_to_user.full_name if order.assigned_to_user else None,
        is_locked_by_me=order.is_locked_by(current_user.id),
        is_locked_by_other=order.is_locked_by_other(current_user.id),
        is_kiz_enabled=order.marketplace.is_kiz_enabled if order.marketplace else False,
        products=_order_products(order),
    )


@router.post("/{order_id}/claim")
def claim_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Захватить заказ (открыть окно).
    
    Успех: заказ назначен на текущего пользователя.
    409: заказ уже открыт другим упаковщиком.
    """
    order = _get_order_for_user(order_id, current_user, db)
    if order.status == OrderStatus.COMPLETED:
        raise HTTPException(400, detail="Order already completed")
    if order.is_locked_by_other(current_user.id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "order_locked",
                "message": "Заказ уже открыт другим упаковщиком",
                "assigned_to_id": order.assigned_to_id,
                "assigned_to_name": order.assigned_to_user.full_name if order.assigned_to_user else None,
            },
        )
    order.assign_to(current_user.id)
    db.commit()
    db.refresh(order)
    return {
        "ok": True,
        "order_id": order_id,
        "assigned_to_id": current_user.id,
    }


@router.post("/{order_id}/release")
def release_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Освободить заказ (закрыть окно без «Собрано»).
    
    Только тот, кто захватил заказ, может его освободить.
    """
    order = _get_order_for_user(order_id, current_user, db)
    if order.status == OrderStatus.COMPLETED:
        raise HTTPException(400, detail="Order already completed")
    if order.is_locked_by_other(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="Можно освободить только свой заказ",
        )
    OrderRepository(db).release_order(order)
    return {"ok": True, "order_id": order_id}


@router.post("/sync/marketplace/{marketplace_id}")
async def sync_orders(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Ручная синхронизация заказов для маркетплейса.
    
    Ozon: заказы «Ожидают отгрузки»
    WB: заказы «На сборке» (new + confirm)
    """
    marketplace = db.query(Marketplace).filter(
        Marketplace.id == marketplace_id,
        Marketplace.user_id == current_user.id,
    ).first()
    if not marketplace:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    
    count = await OrderSyncService.sync_marketplace_orders(marketplace, db)
    return {"synced": count, "marketplace_id": marketplace_id}


@router.post("/sync/all")
async def sync_all_orders(
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Синхронизация заказов для всех активных маркетплейсов пользователя.
    """
    marketplaces = db.query(Marketplace).filter(
        Marketplace.user_id == current_user.id,
        Marketplace.is_active == True,
    ).all()
    
    total = 0
    results = []
    for mp in marketplaces:
        count = await OrderSyncService.sync_marketplace_orders(mp, db)
        total += count
        results.append({"marketplace_id": mp.id, "synced": count})
    
    return {"total_synced": total, "results": results}


@router.post("/{order_id}/complete")
async def complete_order(
    order_id: int,
    data: Optional[OrderCompleteRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Отметить заказ «Собрано».
    
    Только упаковщик, захвативший заказ (или админ), может его завершить.
    """
    order = _get_order_for_user(order_id, current_user, db)
    if order.status == OrderStatus.COMPLETED:
        raise HTTPException(400, detail="Order already completed")
    if order.is_locked_by_other(current_user.id) and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Заказ открыт другим упаковщиком. Завершить может только он или администратор.",
        )
    mp = order.marketplace
    kiz_list: list[str] = []
    if data:
        if data.kiz_codes:
            kiz_list = [str(k).strip()[:31] for k in data.kiz_codes if k and str(k).strip()]
        elif data.kiz_code and str(data.kiz_code).strip():
            kiz_list = [str(data.kiz_code).strip()[:31]]
    required_count = order.quantity
    if mp.is_kiz_enabled:
        if len(kiz_list) < required_count:
            raise HTTPException(
                400,
                detail=f"Нужен КИЗ для каждого товара: введите {required_count} код(ов) маркировки.",
            )
    try:
        ok = await OrderCompleteService.complete_order(
            order, current_user.id, kiz_list, db,
        )
    except Exception as e:
        from app.core.exceptions import MarketplaceAPIException
        if isinstance(e, MarketplaceAPIException):
            status = e.status_code
            detail = e.detail if e.detail else str(e)
            if status == 404 and mp and mp.type.value == "ozon":
                detail = (
                    "Отправление не найдено в Ozon или уже отгружено. "
                    "Проверьте статус в личном кабинете Ozon."
                )
            elif status == 403 and mp and mp.type.value == "ozon":
                detail = (
                    "API-ключ Ozon не имеет прав для отгрузки. "
                    "В личном кабинете seller.ozon.ru → Настройки → API: создайте новый ключ с правами «Отправления» (Posting)."
                )
            raise HTTPException(status_code=status, detail=detail)
        raise
    if not ok:
        raise HTTPException(500, detail="Failed to complete order in marketplace API")
    return {"ok": True, "order_id": order_id}


def _wrap_text(text: str, max_chars: int = 28) -> list[str]:
    """Разбить текст на строки по max_chars символов."""
    if not text or not text.strip():
        return []
    words = text.strip().split()
    lines: list[str] = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 <= max_chars:
            current = f"{current} {w}".strip() if current else w
        else:
            if current:
                lines.append(current)
            current = w if len(w) <= max_chars else w[:max_chars]
    if current:
        lines.append(current)
    return lines


def _create_barcode_drawing(code: str, bar_width: float = 0.25, hide_text: bool = False):
    """
    Создать Drawing со штрихкодом (reportlab). EAN13 для 13 цифр, иначе Code128.
    hide_text: для EAN13 убрать встроенные цифры (чтобы рисовать свои с нужным отступом).
    """
    from reportlab.graphics.barcode import createBarcodeDrawing

    code = str(code).strip()
    if len(code) == 13 and code.isdigit():
        kwargs: dict = {"value": code[:12], "barWidth": bar_width}
        if hide_text:
            kwargs["humanReadable"] = 0
        try:
            return createBarcodeDrawing("EAN13", **kwargs)
        except TypeError:
            kwargs.pop("humanReadable", None)
            return createBarcodeDrawing("EAN13", **kwargs)
    return createBarcodeDrawing("Code128", value=code, barWidth=bar_width)


def _is_ean13(code: str) -> bool:
    """EAN13: 13 цифр (WB). OZN — не EAN13."""
    s = str(code).strip()
    return len(s) == 13 and s.isdigit()


# Отступ сверху для ШК товара Ozon — как у ФБС этикетки (к краю, минимальный)
_BARCODE_TOP_OFFSET_MM = 1.5


def _generate_product_barcode_pdf(
    barcode_value: str,
    ozn_code: str = "",
    label_width_mm: int = 58,
    top_offset_mm: float = 0,
) -> bytes:
    """
    Штрихкод товара: Ozon (OZN+SKU) или WB (EAN13).
    EAN13: без встроенных цифр — рисуем свой текст с отступом (избегаем наложения).
    Размер этикетки 58×40 мм.
    top_offset_mm: отступ сверху (5 для Ozon — не обрезать; 0 для WB — обычное центрирование).
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    display_code = ozn_code or barcode_value
    is_ean = _is_ean13(barcode_value)
    # EAN13: скрываем встроенные цифры, рисуем свои с отступом
    bc_product = _create_barcode_drawing(barcode_value, bar_width=0.4, hide_text=is_ean)
    bw1, bh1 = bc_product.width, bc_product.height

    label_w = label_width_mm * mm
    label_h = 40 * mm
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    h = label_h
    margin = 2 * mm
    top_offset = top_offset_mm * mm
    x0 = margin
    y0 = h - margin - top_offset

    scale1 = min((label_w - 2 * margin) / bw1, 25 * mm / bh1, 2.2)
    c.saveState()
    c.translate(x0 + (label_w - bw1 * scale1) / 2, y0 - bh1 * scale1 - 2 * mm)
    c.scale(scale1, scale1)
    renderPDF.draw(bc_product, c, 0, 0)
    c.restoreState()

    # Отступ 10 мм между штрихкодом и цифрами (для EAN13 важнее — избежать наложения)
    ty = y0 - bh1 * scale1 - 10 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x0 + label_w / 2, ty, str(display_code)[:20])

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _generate_multi_product_barcode_pdf(
    items: list[tuple[str, str]],
    label_width_mm: int = 58,
    top_offset_mm: float = 0,
) -> bytes:
    """
    PDF с несколькими страницами — по одному штрихкоду на каждый товар (Ozon двойные заказы).
    Размер этикетки 58×40 мм.
    top_offset_mm: отступ сверху (5 для Ozon; 0 для WB).
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    if not items:
        raise ValueError("No items for barcode PDF")
    if len(items) == 1:
        return _generate_product_barcode_pdf(items[0][0], items[0][1], label_width_mm, top_offset_mm)

    label_w = label_width_mm * mm
    label_h = 40 * mm
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    margin = 2 * mm
    top_offset = top_offset_mm * mm
    x0 = margin

    for i, (barcode_value, ozn_code) in enumerate(items):
        if i > 0:
            c.showPage()
        display_code = ozn_code or barcode_value
        is_ean = _is_ean13(barcode_value)
        bc_product = _create_barcode_drawing(barcode_value, bar_width=0.4, hide_text=is_ean)
        bw1, bh1 = bc_product.width, bc_product.height
        scale1 = min((label_w - 2 * margin) / bw1, 25 * mm / bh1, 2.2)
        h = label_h
        y0 = h - margin - top_offset
        c.saveState()
        c.translate(x0 + (label_w - bw1 * scale1) / 2, y0 - bh1 * scale1 - 2 * mm)
        c.scale(scale1, scale1)
        renderPDF.draw(bc_product, c, 0, 0)
        c.restoreState()

        ty = y0 - bh1 * scale1 - 10 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x0 + label_w / 2, ty, str(display_code)[:20])

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _wb_sticker_to_png(
    image_bytes: bytes,
    label_width_mm: int = 58,
    label_height_mm: int = 40,
    order_number: str | None = None,
    rotate: int = 90,
) -> bytes:
    """
    WB стикер → PNG для превью. Размер 100% от этикетки.
    """
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")
    if rotate and rotate % 90 == 0:
        img = img.rotate(rotate, expand=True)
        iw, ih = img.size
    elif ih > iw and label_width_mm > label_height_mm:
        img = img.rotate(90, expand=True)
        iw, ih = img.size

    MM_TO_INCH = 1 / 25.4
    DPI = 96
    target_w = int(label_width_mm * MM_TO_INCH * DPI)
    target_h = int(label_height_mm * MM_TO_INCH * DPI)
    scale = min(target_w / iw, target_h / ih, 1.0)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    out.paste(img, (0, 0))

    if order_number and str(order_number).strip():
        import os

        draw = ImageDraw.Draw(out)
        font_paths = [
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        font = None
        for p in font_paths:
            try:
                if os.path.exists(p):
                    font = ImageFont.truetype(p, 10)
                    break
            except OSError:
                pass
        if font:
            num_text = str(order_number).strip()[:25]
            bbox = draw.textbbox((0, 0), num_text, font=font)
            tw = bbox[2] - bbox[0]
            draw.text(((new_w - tw) / 2, 4), num_text, fill=(0, 0, 0), font=font)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _wb_sticker_to_pdf_as_is(image_bytes: bytes, dpi: int = 96) -> bytes:
    """
    WB стикер «как есть»: PNG → PDF с размером страницы = размер изображения.
    Для печати с fit — принтер масштабирует под физический лист.
    """
    import io

    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")
    # Страница = размер изображения в пунктах (72 pt = 1 inch)
    page_w = iw * 72 / dpi
    page_h = ih * 72 / dpi
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.drawImage(ImageReader(img_buf), 0, 0, width=page_w, height=page_h)
    c.save()
    buf.seek(0)
    return buf.getvalue()


def _wb_sticker_to_pdf(
    image_bytes: bytes,
    label_width_mm: int = 58,
    label_height_mm: int = 40,
    order_number: str | None = None,
    rotate: int = 90,
    top_margin_mm: float = 6.0,
) -> bytes:
    """
    Конвертировать PNG-стикер WB в PDF для печати (размер 58×40 мм).
    WB присылает «высокую» этикетку — поворачиваем на 90° для широкой 58×40.
    """
    import io

    from PIL import Image
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")
    if rotate and rotate % 90 == 0:
        img = img.rotate(rotate, expand=True)
        iw, ih = img.size
    # WB часто присылает «высокую» картинку — для широкой 58×40 всегда поворачиваем
    elif ih > iw and label_width_mm > label_height_mm:
        img = img.rotate(90, expand=True)
        iw, ih = img.size
    # Стикер WB обычно с белыми полями; убираем их, чтобы вся этикетка (включая код) подтянулась к верху.
    try:
        from PIL import ImageChops as _WBImageChops
        bg = Image.new(img.mode, img.size, (255, 255, 255))
        diff = _WBImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox and (bbox[2] - bbox[0]) > 10 and (bbox[3] - bbox[1]) > 10:
            img = img.crop(bbox)
            iw, ih = img.size
    except Exception:
        pass
    label_w = label_width_mm * mm
    label_h = label_height_mm * mm
    scale = min(label_w / iw, label_h / ih)  # вписать в стикер (масштаб вверх/вниз)
    draw_w = iw * scale
    draw_h = ih * scale
    # Прижимаем к верху, добавляя небольшой отступ слева, чтобы не обрезалось.
    margin_left_mm = 1.5
    margin_top_mm = 0.0
    x0 = margin_left_mm * mm
    y0 = label_h - draw_h - margin_top_mm * mm
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))
    c.drawImage(
        ImageReader(img_buf),
        x0, y0, width=draw_w, height=draw_h,
        preserveAspectRatio=True,
    )
    # Номер заказа WB — внизу этикетки
    if order_number and str(order_number).strip():
        c.setFont("Helvetica-Bold", 8)
        num_text = str(order_number).strip()[:25]
        c.drawCentredString(label_w / 2, 2 * mm, num_text)
    c.save()
    buf.seek(0)
    return buf.getvalue()


def _add_product_name_to_barcode(image_bytes: bytes, product_name: str) -> bytes:
    """Добавить название товара под штрих-кодом (как в примере Ozon)."""
    import io
    import os

    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    # Шрифт с поддержкой кириллицы
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    font_size = max(10, min(w // 15, 14))
    font = None
    for p in font_paths:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, font_size)
                break
            except OSError:
                pass
    if font is None:
        font = ImageFont.load_default()

    lines = _wrap_text(product_name, max_chars=max(20, w // (font_size or 10)))
    line_height = int(font_size * 1.3)
    extra_h = len(lines) * line_height + 8 if lines else 0
    if extra_h == 0:
        return image_bytes

    new_img = Image.new("RGB", (w, h + extra_h), (255, 255, 255))
    new_img.paste(img, (0, 0))
    draw = ImageDraw.Draw(new_img)
    y = h + 4
    for line in lines:
        # Центрирование по ширине (приблизительно)
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = max(0, (w - tw) // 2)
        draw.text((x, y), line, fill=(0, 0, 0), font=font)
        y += line_height

    out = io.BytesIO()
    new_img.save(out, format="PNG")
    return out.getvalue()


@router.get("/{order_id}/product-barcode")
async def get_order_product_barcode(
    order_id: int,
    with_name: bool = Query(True, description="Добавить название товара под штрих-кодом"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Штрихкод товара (upper_barcode) для печати.
    Только Ozon. WB не поддерживает отдельный штрихкод товара.
    С названием товара под штрих-кодом (как в примере Ozon).
    """
    from app.models.marketplace import MarketplaceType
    from app.services.marketplace.ozon import OzonClient
    from app.core.security import decrypt_api_key
    import io

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, detail="Order not found")
    mp = order.marketplace
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Order not found")
    if mp.type != MarketplaceType.OZON:
        raise HTTPException(400, detail="Product barcode only for Ozon")
    if not mp.client_id:
        raise HTTPException(400, detail="Ozon client_id missing")

    api_key = decrypt_api_key(mp.api_key)
    async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
        details = await client.get_posting_details(order.posting_number, with_barcodes=True)
    # Ozon: штрихкод товара = OZN + SKU (док. Ozon). upper_barcode — EAN из карточки.
    products = details.get("products") or []
    sku = products[0].get("sku") if products else None
    if sku is not None:
        code = f"OZN{sku}"
    else:
        barcodes = details.get("barcodes") or {}
        upper = barcodes.get("upper_barcode") if isinstance(barcodes, dict) else None
        if not upper or not str(upper).strip():
            raise HTTPException(404, detail="Product barcode not found")
        code = str(upper).strip()

    # Название товара: из БД или из details
    product_name = (order.product_name or "").strip()
    if not product_name and products:
        product_name = (products[0].get("name") or "").strip()

    try:
        from barcode import EAN13, Code128
        from barcode.writer import ImageWriter

        if len(code) == 13 and code.isdigit():
            bc = EAN13(code[:12], writer=ImageWriter())  # EAN13 expects 12 digits
        else:
            bc = Code128(code, writer=ImageWriter())
        buf = io.BytesIO()
        bc.write(buf)
        buf.seek(0)
        image_bytes = buf.getvalue()

        if with_name and product_name:
            image_bytes = _add_product_name_to_barcode(image_bytes, product_name)

        return Response(
            content=image_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename=product-barcode-{order_id}.png"},
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to generate barcode: {e}") from e


@router.get("/{order_id}/barcodes-pdf")
async def get_order_barcodes_pdf(
    order_id: int,
    label_width: Optional[int] = Query(None, description="Ширина этикетки в мм (58 или 80). Если не указано — из настроек пользователя."),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Штрихкод товара Ozon: большой штрихкод + OZN-код (без названия).
    Для этикетки ФБС используйте /label.
    """
    from app.core.exceptions import MarketplaceAPIException
    from app.models.marketplace import MarketplaceType
    from app.services.marketplace.ozon import OzonClient
    from app.core.security import decrypt_api_key

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, detail="Order not found")
    mp = order.marketplace
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Order not found")

    items: list[tuple[str, str]] = []

    if mp.type == MarketplaceType.WILDBERRIES:
        # WB: товарный баркод хранится в extra_data["skus"] (EAN13 или Code128)
        extra = order.extra_data or {}
        skus: list = extra.get("skus") or []
        for sku_val in skus:
            code = str(sku_val).strip()
            if code:
                items.append((code, code))
        if not items:
            raise HTTPException(404, detail="Товарный баркод не найден в заказе WB (skus пустой)")
    elif mp.type == MarketplaceType.OZON:
        if not mp.client_id:
            raise HTTPException(400, detail="Ozon client_id missing")
        api_key = decrypt_api_key(mp.api_key)
        try:
            async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
                details = await client.get_posting_details(order.posting_number, with_barcodes=True)
        except MarketplaceAPIException as e:
            err_str = str(e).lower()
            detail = getattr(e, "detail", None)
            detail_str = str(detail).lower() if detail else ""
            if isinstance(detail, dict):
                for d in (detail.get("details") or []):
                    if isinstance(d, dict) and d.get("message"):
                        detail_str += " " + str(d.get("message", "")).lower()
            is_delivered_error = (
                "delivered" in err_str or "delivered" in detail_str
                or "label not allowed" in detail_str
                or "not allowed for" in detail_str
            )
            if is_delivered_error:
                if order.status != OrderStatus.DELIVERED:
                    order.status = OrderStatus.DELIVERED
                    order.marketplace_status = "delivered"
                    db.commit()
                raise HTTPException(
                    400,
                    detail="Заказ уже отгружен в Ozon. Печать недоступна. Обновите список заказов.",
                )
            raise

        barcodes = details.get("barcodes") or {}
        products = details.get("products") or []
        upper = (barcodes.get("upper_barcode") or "").strip() if isinstance(barcodes, dict) else ""

        for p in products:
            sku = p.get("sku")
            qty = max(1, int(p.get("quantity", 1)))
            ozn_code = f"OZN{sku}" if sku is not None else (upper if upper else None)
            if not ozn_code:
                continue
            for _ in range(qty):
                items.append((ozn_code, ozn_code))

        if not items:
            raise HTTPException(404, detail="Product barcode not found")
    else:
        raise HTTPException(400, detail="Unknown marketplace type")

    # Ширина и поворот штрихкодов: из query или из настроек пользователя
    ps_barcode = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
    if label_width is None:
        label_width = (ps_barcode.ozon_width_mm or 58) if ps_barcode else 58
    label_width = int(label_width)
    # Ozon: отступ сверху 5 мм — не обрезало принтером. WB: без отступа — обычное центрирование
    top_offset = _BARCODE_TOP_OFFSET_MM if mp.type == MarketplaceType.OZON else 0
    pdf_bytes = _generate_multi_product_barcode_pdf(items, label_width_mm=label_width, top_offset_mm=top_offset)
    # Ozon OZN-штрихкоды: поворот из настроек (90 по умолчанию). WB EAN13 — без поворота
    barcode_rotate = 90 if mp.type == MarketplaceType.OZON else 0
    if mp.type == MarketplaceType.OZON and ps_barcode and ps_barcode.barcode_rotate is not None:
        barcode_rotate = int(ps_barcode.barcode_rotate)
    if barcode_rotate and barcode_rotate in (90, 180, 270):
        logger.info("Barcode PDF: applying rotate=%s (label %s×40 mm)", barcode_rotate, label_width)
        try:
            pdf_bytes = _rotate_pdf_via_image(
                pdf_bytes, barcode_rotate,
                width_mm=label_width, height_mm=40,
            )
        except Exception as e:
            logger.warning("Barcode rotate via image failed (%s), trying pypdf", e)
            try:
                pdf_bytes = _rotate_pdf(pdf_bytes, barcode_rotate)
            except Exception as e2:
                logger.warning("Barcode rotate pypdf also failed: %s", e2)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=barcodes-{order_id}.pdf"},
    )


@router.get("/{order_id}/label")
async def get_order_label(
    order_id: int,
    format: str = Query("pdf", description="pdf — для печати (точный размер 58×40 мм). png — превью."),
    width: Optional[int] = Query(None, description="WB: ширина этикетки в мм. Если не указано — из настроек пользователя."),
    height: Optional[int] = Query(None, description="WB: высота этикетки в мм. Если не указано — из настроек пользователя."),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Получить этикетку заказа для печати.
    
    Ozon: PDF
    WB: SVG/PNG (стикер)
    """
    from app.models.marketplace import MarketplaceType
    from app.services.marketplace.ozon import OzonClient
    from app.services.marketplace.wildberries import WildberriesClient
    from app.core.security import decrypt_api_key

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, detail="Order not found")
    mp = order.marketplace
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Order not found")
    api_key = decrypt_api_key(mp.api_key)

    if mp.type == MarketplaceType.OZON:
        if not mp.client_id:
            raise HTTPException(400, detail="Ozon client_id missing")
        is_delivered_error = False
        try:
            async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
                content = await client.get_order_label(order.posting_number)
        except Exception as e:
            err_str = str(e).lower()
            detail = getattr(e, "detail", None)
            detail_str = str(detail).lower() if detail else ""
            # Ozon: details[].message = "label not allowed for delivered postings"
            if isinstance(detail, dict):
                for d in (detail.get("details") or []):
                    if isinstance(d, dict) and d.get("message"):
                        detail_str += " " + str(d.get("message", "")).lower()
            # Ozon: "label not allowed for delivered postings" или "доставлен" / "отгружен"
            is_delivered_error = (
                "delivered" in err_str or "delivered" in detail_str
                or "label not allowed" in detail_str
                or "not allowed for" in detail_str
                or "доставлен" in detail_str
                or "отгружен" in detail_str
            )
            if is_delivered_error:
                if order.status != OrderStatus.DELIVERED:
                    order.status = OrderStatus.DELIVERED
                    order.marketplace_status = "delivered"
                    db.commit()
                    logger.info(
                        f"Order {order_id} marked as DELIVERED (Ozon label rejected: already delivered)",
                        extra={"order_id": order_id, "posting_number": order.posting_number},
                    )
                raise HTTPException(
                    400,
                    detail="Заказ уже отгружен в Ozon. Этикетка недоступна. Обновите список заказов.",
                )
            raise
        try:
            _ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
            if _ps:
                w_mm = _ps.ozon_width_mm or 58
                h_mm = _ps.ozon_height_mm or 40
                # 0 = 0 (без поворота), 90/180/270 — как есть; None → по умолчанию 90.
                ozon_rot = _ps.ozon_label_rotate if _ps.ozon_label_rotate is not None else 90
                printer_dpi = _ps.printer_dpi or 203
                label_mode = _ps.label_print_mode or "standard_58x40_noscale"
            else:
                w_mm, h_mm, ozon_rot, printer_dpi = 58, 40, 90, 203
                label_mode = "standard_58x40_noscale"
        except Exception:
            w_mm, h_mm, ozon_rot, printer_dpi = 58, 40, 90, 203
            label_mode = "standard_58x40_noscale"
        try:
            if format == "png":
                content = _ozon_fbs_to_png(content, width_mm=w_mm, height_mm=h_mm, rotate=ozon_rot)
                return Response(
                    content=content,
                    media_type="image/png",
                    headers={
                        "Content-Disposition": f"inline; filename=label-{order.posting_number}.png",
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                    },
                )
            if label_mode == "as_is_fit":
                content = _rotate_pdf(content, 90)  # Повернуть в альбом: ширина > высоты, этикетка в углу
            else:
                # noscale: поворот только через PIL в _ozon_fbs_to_standard_label (pypdf ненадёжен с PDF Ozon)
                content = _ozon_fbs_to_standard_label(
                    content, width_mm=w_mm, height_mm=h_mm, rotate=ozon_rot, dpi=printer_dpi,
                )
        except Exception as _re:
            logger.warning("Ozon FBS to standard label failed: %s", _re, exc_info=True)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=label-{order.posting_number}.pdf",
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
    elif mp.type == MarketplaceType.WILDBERRIES:
        ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
        if width is None or height is None:
            w = (ps.wb_width_mm if ps else 58) or 58
            h = (ps.wb_height_mm if ps else 40) or 40
        else:
            w, h = width, height
        wb_rotate = (ps.wb_label_rotate or 90) if ps else 90
        label_mode = (ps.label_print_mode or "standard_58x40_noscale") if ps else "standard_58x40_noscale"
        async with WildberriesClient(api_key=api_key) as client:
            content = await client.get_order_label(
                order.external_id,
                sticker_type="png",
                width=w,
                height=h,
            )
        order_num = order.posting_number or order.external_id or ""
        if format == "png":
            content = _wb_sticker_to_png(
                content, label_width_mm=w, label_height_mm=h,
                order_number=order_num, rotate=wb_rotate,
            )
            return Response(
                content=content,
                media_type="image/png",
                headers={
                    "Content-Disposition": f"inline; filename=label-{order.posting_number}.png",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
        if label_mode == "as_is_fit":
            content = _wb_sticker_to_pdf_as_is(content)
        else:
            content = _wb_sticker_to_pdf(
                content, label_width_mm=w, label_height_mm=h,
                order_number=order_num, rotate=wb_rotate,
            )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=label-{order.posting_number}.pdf"},
        )
    raise HTTPException(400, detail="Unknown marketplace type")
