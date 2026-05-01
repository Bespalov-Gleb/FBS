"""
API endpoints для заказов и синхронизации
"""
from datetime import datetime, timedelta
from typing import List, Optional
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.packer_scope import get_effective_user_and_marketplace_ids
from app.utils.logger import logger
from app.core.dependencies import CurrentUser
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.order import Order, OrderStatus
from app.models.scanned_kiz import ScannedKiz
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCompleteRequest, OrderProductItem, OrderResponse, OrdersListResponse
from app.services.marketplace.wildberries import WildberriesClient
from app.services.order_complete_service import OrderCompleteService
from app.services.kiz_pool_service import suggest_kiz_codes_fifo_for_order
from app.services.order_sync_guard import ManualSyncLockTimeout, SyncCooldownError
from app.services.order_sync_service import OrderSyncService

router = APIRouter(prefix="/orders", tags=["Orders"])


def _is_scanned_kiz_missing_table(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "scanned_kiz" in msg and ("does not exist" in msg or "undefinedtable" in msg)


def _get_effective_user_and_access(
    current_user: User, db: Session
) -> tuple[int, Optional[List[int]]]:
    return get_effective_user_and_marketplace_ids(current_user, db)


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


def _ozon_product_barcode_for_ui(p: dict) -> Optional[str]:
    """
    ШК для карточки заказа Ozon: поля из Seller API или OZN+SKU (как GET .../product-barcode).
    В unfulfilled/list часто есть sku, а barcode на товаре — только при with.barcodes или в /posting/fbs/get.
    """
    if not isinstance(p, dict):
        return None
    for k in ("barcode", "product_barcode", "ean", "product_ean"):
        v = str(p.get(k) or "").strip()
        if v:
            return v
    sku = p.get("sku")
    if sku is not None and str(sku).strip():
        try:
            return f"OZN{int(sku)}"
        except (ValueError, TypeError):
            return f"OZN{sku}"
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
            barcode=_ozon_product_barcode_for_ui(p if isinstance(p, dict) else {}),
            size=_ozon_product_size(
                p, order_id=o.id, offer_id=str(p.get("offer_id", "")), order_size=order_size
            ),
        )
        for p in prods
    ]


def _order_barcode(o: Order) -> Optional[str]:
    """Основной ШК заказа для UI модалки (Ozon: товарный ШК; WB: первый sku)."""
    ed = o.extra_data or {}
    mp = o.marketplace
    if mp and mp.type.value == "ozon" and isinstance(ed, dict):
        prods = ed.get("products")
        if isinstance(prods, list) and prods:
            first = prods[0]
            if isinstance(first, dict):
                bc = _ozon_product_barcode_for_ui(first)
                if bc:
                    return bc
        bdict = ed.get("barcodes")
        if isinstance(bdict, dict):
            for key in ("upper_barcode", "lower_barcode"):
                v = str(bdict.get(key) or "").strip()
                if v:
                    return v
    skus = ed.get("skus") if isinstance(ed, dict) else None
    if isinstance(skus, list):
        for s in skus:
            val = str(s or "").strip()
            if val:
                return val
    val = str(ed.get("barcode", "")).strip() if isinstance(ed, dict) else ""
    return val or None

def _is_printed(order: Order) -> bool:
    ed = order.extra_data or {}
    return isinstance(ed, dict) and bool(ed.get("printed_in_app"))


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
            barcode=_order_barcode(o),
            size=_sanitize_size((o.extra_data or {}).get("size")),
            marketplace_created_at=o.marketplace_created_at,
            completed_at=o.completed_at,
            assigned_to_id=o.assigned_to_id,
            assigned_at=o.assigned_at,
            assigned_to_name=o.assigned_to_user.full_name if o.assigned_to_user else None,
            # Блокировка по факту assigned_to_id: кто открыл заказ (упаковщик или админ).
            is_locked_by_me=o.is_locked_by(current_user.id),
            is_locked_by_other=o.is_locked_by_other(current_user.id),
            is_printed=_is_printed(o),
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
        packer_allowed_marketplace_ids=packer_allowed_mp_ids,
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
            barcode=_order_barcode(o),
            size=_sanitize_size((o.extra_data or {}).get("size")),
            marketplace_created_at=o.marketplace_created_at,
            completed_at=o.completed_at,
            assigned_to_id=o.assigned_to_id,
            assigned_at=o.assigned_at,
            assigned_to_name=o.assigned_to_user.full_name if o.assigned_to_user else None,
            # Блокировка по факту assigned_to_id: кто открыл заказ (упаковщик или админ).
            is_locked_by_me=o.is_locked_by(current_user.id),
            is_locked_by_other=o.is_locked_by_other(current_user.id),
            is_printed=_is_printed(o),
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

    Упаковщик: те же магазины, что в GET /orders (владелец + UserMarketplaceAccess).
    «Собрано» — все отмеченные в приложении за 3 дня в этой области; «собрано мной» — с completed_by_id текущего пользователя.
    Сегодня / неделя / месяц / скорость — личная статистика текущего пользователя.
    """
    effective_user_id, packer_allowed_mp_ids = _get_effective_user_and_access(
        current_user, db
    )
    order_repo = OrderRepository(db)
    return order_repo.get_stats(
        marketplace_owner_id=effective_user_id,
        stats_user_id=current_user.id,
        packer_allowed_marketplace_ids=packer_allowed_mp_ids,
    )


@router.get("/kiz-scans")
def get_kiz_scans_count(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Количество отсканированных КИЗ в таблице пользователя.
    Для отображения в UI (счётчик перед скачиванием).
    """
    try:
        count = (
            db.query(ScannedKiz)
            .filter(ScannedKiz.user_id == current_user.id)
            .count()
        )
    except ProgrammingError as exc:
        if _is_scanned_kiz_missing_table(exc):
            db.rollback()
            return {"count": 0}
        raise
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
    try:
        deleted = (
            db.query(ScannedKiz)
            .filter(ScannedKiz.user_id == current_user.id)
            .delete()
        )
        db.commit()
    except ProgrammingError as exc:
        if _is_scanned_kiz_missing_table(exc):
            db.rollback()
            return {"ok": True, "deleted": 0}
        raise
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
    kiz = (data.kiz_code or "").strip()[:255]
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
    try:
        db.commit()
    except ProgrammingError as exc:
        if _is_scanned_kiz_missing_table(exc):
            db.rollback()
            raise HTTPException(
                503,
                detail="Таблица scanned_kiz отсутствует. Примените миграции backend.",
            ) from exc
        raise
    return {"ok": True, "id": sk.id}


@router.get("/kiz-export")
def kiz_export(
    marketplace_id: Optional[int] = Query(None, description="Фильтр по маркетплейсу (обязателен для формата WB/Ozon)"),
    export_format: str = Query("xlsx", description="xlsx | txt"),
    created_from: Optional[datetime] = Query(None, description="Начало периода created_at (ISO)"),
    created_to: Optional[datetime] = Query(None, description="Конец периода created_at (ISO)"),
    today_only: bool = Query(False, description="Только записи за сегодня"),
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
    if today_only:
        now = datetime.utcnow()
        day_start = datetime(now.year, now.month, now.day)
        day_end = day_start + timedelta(days=1)
        query = query.filter(ScannedKiz.created_at >= day_start, ScannedKiz.created_at < day_end)
    else:
        if created_from is not None:
            query = query.filter(ScannedKiz.created_at >= created_from)
        if created_to is not None:
            query = query.filter(ScannedKiz.created_at <= created_to)
    if marketplace_id:
        query = query.filter(ScannedKiz.marketplace_id == marketplace_id)
    try:
        rows = query.order_by(ScannedKiz.created_at.asc()).limit(10000).all()
    except ProgrammingError as exc:
        if _is_scanned_kiz_missing_table(exc):
            db.rollback()
            rows = []
        else:
            raise

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


def _fbs_debug_enabled() -> bool:
    """
    Включить сохранение промежуточных файлов.

    По умолчанию включено (FBS_PRINT_DEBUG не задан):
    - выключить можно только явно: FBS_PRINT_DEBUG=0/false.
    """
    raw = os.environ.get("FBS_PRINT_DEBUG")
    if raw is None:
        return True
    s = str(raw).strip().lower()
    return s not in ("", "0", "false", "off", "no")


def _fbs_debug_root() -> str:
    """Корневая папка для отладки в %APPDATA%."""
    return os.path.join(os.environ.get("APPDATA", ""), "fbs-print-debug")


def _fbs_debug_dir(job_key: str) -> str:
    """
    Папка для конкретного типа печати:
    - ozon_fbs
    - wb_fbs
    - ozon_barcode
    - wb_barcode
    """
    path = os.path.join(_fbs_debug_root(), job_key)
    os.makedirs(path, exist_ok=True)
    return path


def _fbs_debug_write_bytes(job_key: str, stage: str, filename: str, data: bytes) -> None:
    if not _fbs_debug_enabled():
        return
    try:
        d = _fbs_debug_dir(job_key)
        path = os.path.join(d, f"{stage}_{filename}")
        with open(path, "wb") as f:
            f.write(data)
    except Exception:
        # не ломаем печать из-за отладки
        pass


def _fbs_debug_write_text(job_key: str, stage: str, filename: str, text: str) -> None:
    if not _fbs_debug_enabled():
        return
    try:
        d = _fbs_debug_dir(job_key)
        path = os.path.join(d, f"{stage}_{filename}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _fbs_debug_write_json(job_key: str, stage: str, filename: str, obj: object) -> None:
    import json
    if not _fbs_debug_enabled():
        return
    try:
        _fbs_debug_write_text(job_key, stage, filename, json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _fbs_debug_save_pil(job_key: str, stage: str, filename: str, img) -> None:
    """img — PIL.Image.Image"""
    if not _fbs_debug_enabled():
        return
    try:
        d = _fbs_debug_dir(job_key)
        path = os.path.join(d, f"{stage}_{filename}")
        img.save(path, format="PNG")
    except Exception:
        pass


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

    # rotate=0: авто-поворот только если целевая этикетка альбомная (58x40)
    # и исходник портретный, чтобы убрать "вертикальную" печать.
    if rotate in (90, 180, 270):
        deg = rotate
    elif rotate == 0:
        deg = 90 if (width_mm > height_mm and ih > iw) else 0
    else:
        deg = 0
    if deg:
        # UI: 90/270 — по часовой.
        # PIL: ROTATE_90 — против ч/с, ROTATE_270 — по ч/с.
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
    target_w = int(width_mm * MM_TO_INCH * DPI)
    target_h = int(height_mm * MM_TO_INCH * DPI)
    # fit: не выходим за границы этикетки и не делаем контент "порезанным"
    scale = min(target_w / iw, target_h / ih)
    new_w = int(iw * scale)
    new_h = int(ih * scale)
    img = img.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
    out = PILImage.new("RGB", (target_w, target_h), (255, 255, 255))
    x_off = 0
    y_off = 0
    out.paste(img, (x_off, y_off))
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
    scale_factor: float = 1.0,
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

    debug_job_key = "ozon_fbs"
    _fbs_debug_write_bytes(debug_job_key, "00_input", "input.pdf", pdf_bytes)

    # Сначала пробуем обрезать страницу на уровне PDF (CropBox), чтобы рендер сразу без полей
    pdf_to_render = pdf_bytes
    use_cropbox = False
    cropped = _ozon_pdf_set_cropbox_to_content(pdf_bytes, dpi_low=120)
    if cropped:
        pdf_to_render = cropped
        use_cropbox = True

    _fbs_debug_write_bytes(debug_job_key, "01_pdf_to_render", "pdf_to_render.pdf", pdf_to_render)

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

    # Лист альбомной ориентации: ширина×высота = width_mm×height_mm (например 58×40).
    # Рисуем контент так, чтобы он максимально заполнял стикер.
    # scale_factor > 1: страница PDF и контент расширяются вместе.
    page_width_mm = width_mm
    page_height_mm = height_mm
    sf = max(1.0, float(scale_factor))
    frame_w_pt = page_width_mm * mm * sf
    frame_h_pt = page_height_mm * mm * sf
    # Маленький технологический отступ слева, чтобы печать не прилипала к кромке.
    margin_left_pt = 1.0 * mm
    margin_top_pt = 0.0 * mm
    usable_w = max(1.0, frame_w_pt - margin_left_pt)
    usable_h = frame_h_pt

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(frame_w_pt, frame_h_pt))

    for idx, img in enumerate(images):
        if idx > 0:
            c.showPage()
        img = img.convert("RGB")
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            continue

        if idx == 0:
            _fbs_debug_save_pil(debug_job_key, "02_render", "render_before_crops.png", img)

        # rotate=0: авто-поворот под альбомную этикетку 58x40,
        # если исходник портретный.
        deg: Optional[int]
        if rotate in (90, 180, 270):
            deg = int(rotate)
        elif rotate == 0:
            deg = 90 if (width_mm > height_mm and ih > iw) else 0
        else:
            deg = 0
        logger.info(
            "Ozon FBS label: page %s size %sx%s rotate_setting=%s applied_deg=%s",
            idx + 1, iw, ih, rotate, deg,
        )
        # Важно: сначала кропаем/обрезаем белые поля и верхний пояс,
        # и только потом поворачиваем, чтобы поворот не влиял на масштаб/кроп.
        # Убираем белые поля: bbox по порогу «не белый» (чтобы контент не разъезжался).
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

        if idx == 0:
            _fbs_debug_save_pil(debug_job_key, "03_after_white_bbox_crop", "after_white_bbox.png", img)

        # Первая строка с любым тёмным пикселем — верх контента
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

        if idx == 0:
            _fbs_debug_save_pil(debug_job_key, "04_after_top_strip_crop", "after_top_strip.png", img)

        # Применяем поворот, затем считаем масштаб уже для финальной ориентации.
        if deg:
            # UI: 90/270 — по часовой.
            # PIL: ROTATE_90 — против ч/с, ROTATE_270 — по ч/с.
            if deg == 90:
                img = img.transpose(Image.Transpose.ROTATE_270)
            elif deg == 270:
                img = img.transpose(Image.Transpose.ROTATE_90)
            elif deg == 180:
                img = img.transpose(Image.Transpose.ROTATE_180)
            iw, ih = img.size

        if idx == 0:
            _fbs_debug_save_pil(debug_job_key, "05_after_rotation", "after_rotation.png", img)

        # fit: не выходим за границы 58×40 и не режем контент.
        # Важно считать scale после поворота, иначе при авто-rotate (0 -> 90)
        # этикетка становится заметно меньше по ширине.
        scale = min(usable_w / iw, usable_h / ih)

        draw_w = iw * scale
        draw_h = ih * scale
        # Прижать к верхнему левому углу (ожидание "на весь стикер").
        x_place = margin_left_pt
        y_place = frame_h_pt - margin_top_pt - draw_h

        if idx == 0:
            try:
                scaled_w = max(1, int(iw * scale))
                scaled_h = max(1, int(ih * scale))
                img_scaled = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
                _fbs_debug_save_pil(debug_job_key, "06_scaled_for_draw", "scaled.png", img_scaled)
            except Exception:
                pass

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
    content = buf.getvalue()
    _fbs_debug_write_bytes(debug_job_key, "07_output", "output.pdf", content)
    _fbs_debug_write_json(
        debug_job_key,
        "98_meta",
        "meta.json",
        {
            "width_mm": width_mm,
            "height_mm": height_mm,
            "rotate": rotate,
            "dpi": dpi,
            "scale_factor": scale_factor,
            "debug": "ozon_fbs_to_standard_label",
        },
    )
    return content


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
    Поворот/размещение PDF через рендер в изображение (для PDF от ReportLab).
    При 90/270 — та же логика, что у этикетки ФБС: лист книжной ориентации 40×58,
    контент уже альбомный (наш PDF 58×40) — не вращаем, кроп и привязка к верхнему левому как у этикетки.
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

    # Полностью как у этикетки ФБС: книжная страница 40×58, отступы 1 мм, контент в альбомном виде в верхнем левом углу
    if degrees in (90, 270):
        page_w_pt = height_mm * mm   # 40 mm
        page_h_pt = width_mm * mm   # 58 mm
        margin_left_pt = 1.0 * mm
        margin_top_pt = 1.0 * mm
        usable_w = page_w_pt - margin_left_pt - 1.0 * mm
        usable_h = page_h_pt - margin_top_pt - 1.0 * mm
        # Штрихкод-источник уже альбомный (58×40) — не поворачиваем, иначе станет портрет и будет вертикально
        skip_pixel_rotate = True
    else:
        page_w_pt = width_mm * mm
        page_h_pt = height_mm * mm
        margin_left_pt = 1.0 * mm
        margin_top_pt = 0
        usable_w = page_w_pt - margin_left_pt
        usable_h = page_h_pt - margin_top_pt
        skip_pixel_rotate = False

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w_pt, page_h_pt))
    for idx, img in enumerate(images):
        if idx > 0:
            c.showPage()
        img = img.convert("RGB")
        if not skip_pixel_rotate:
            if degrees == 90:
                img = img.transpose(Image.Transpose.ROTATE_270)
            elif degrees == 270:
                img = img.transpose(Image.Transpose.ROTATE_90)
            elif degrees == 180:
                img = img.transpose(Image.Transpose.ROTATE_180)
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            continue
        # Кроп как у этикетки: bbox по порогу 250, затем первая строка с тёмным 253
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
        if iw <= 0 or ih <= 0:
            continue
        # Вписать в область, прижать к верхнему левому — как у этикетки
        scale = min(usable_w / iw, usable_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        x_place = margin_left_pt
        y_place = page_h_pt - margin_top_pt - draw_h
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)
        c.drawImage(
            ImageReader(img_buf), x_place, y_place, width=draw_w, height=draw_h,
            preserveAspectRatio=True,
        )
    c.save()
    buf.seek(0)
    content = buf.getvalue()
    _fbs_debug_write_bytes(debug_job_key, "07_output", "output.pdf", content)
    _fbs_debug_write_json(
        debug_job_key,
        "98_meta",
        "meta.json",
        {
            "label_width_mm": label_width_mm,
            "label_height_mm": label_height_mm,
            "rotate": rotate,
            "scale_factor": scale_factor,
            "debug": "wb_sticker_to_pdf",
        },
    )
    return content


def _parse_kiz_01_21_91_92(s: str) -> Optional[tuple[str, str, str, str]]:
    """
    Полный КИЗ ЧЗ без скобок: 01+GTIN(14)+21+serial+91+key(4)+92+crypto.
    Возвращает (gtin, serial, key, crypto) или None.
    """
    t = (s or "").strip()
    if not t or t.startswith("("):
        return None
    m = re.match(r"^01(\d{14})21(.*?)91([A-Za-z0-9]{4})92(.+)$", t)
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3), m.group(4))


def _try_datamatrix_image_zint_gs1(raw: str):
    """
    GS1 Data Matrix через Zint. Подбираем режим, ближе к этикеткам ЧЗ / сервисам вроде 2КИЗ.

    В Zint по умолчанию между полями GS1 в DM идёт FNC1; у маркировки часто ожидается
    разделитель GS (ASCII 29) — см. Zint manual 6.6.1: опция --gssep.
    Дополнительно --square — только квадратные размеры (как 26×26, 32×32…).

    Порядок: [01]… + --gs1 --gssep --square → … --gssep → … --square → …; затем --gs1raw + \\G.
    FBS_KIZ_ZINT_MODE=bracket_only — только первый старый вариант (--gs1 без gssep).
    """
    import shutil
    import subprocess
    import tempfile

    from PIL import Image

    ev = (os.environ.get("FBS_KIZ_USE_ZINT") or "1").strip().lower()
    if ev in ("0", "false", "no", "off"):
        return None
    if not shutil.which("zint"):
        return None
    parsed = _parse_kiz_01_21_91_92(raw)
    if not parsed:
        return None
    gtin, serial, key, crypto = parsed
    if any(("[" in p or "]" in p) for p in (gtin, serial, key, crypto)):
        return None
    bracket = f"[01]{gtin}[21]{serial}[91]{key}[92]{crypto}"
    # Сырой поток: 01…21… <GS> 91… <GS> 92… (Zint --gs1raw, \G + --esc)
    raw_gs1 = f"01{gtin}21{serial}\\G91{key}\\G92{crypto}"

    mode = (os.environ.get("FBS_KIZ_ZINT_MODE") or "").strip().lower()
    if mode == "bracket_only":
        attempts: list[tuple[str, list[str], str]] = [
            ("zint --gs1", ["--gs1"], bracket),
        ]
    else:
        attempts = [
            ("zint --gs1 --gssep --square", ["--gs1", "--gssep", "--square"], bracket),
            ("zint --gs1 --gssep", ["--gs1", "--gssep"], bracket),
            ("zint --gs1 --square", ["--gs1", "--square"], bracket),
            ("zint --gs1", ["--gs1"], bracket),
            (
                "zint --gs1raw --esc --gssep --square",
                ["--gs1raw", "--esc", "--gssep", "--square"],
                raw_gs1,
            ),
            ("zint --gs1raw --esc --gssep", ["--gs1raw", "--esc", "--gssep"], raw_gs1),
            ("zint --gs1raw --esc --square", ["--gs1raw", "--esc", "--square"], raw_gs1),
            ("zint --gs1raw --esc", ["--gs1raw", "--esc"], raw_gs1),
        ]

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    path = tmp.name
    tmp.close()
    last_err = ""
    try:
        for label, flags, data in attempts:
            r = subprocess.run(
                [
                    "zint",
                    "-b",
                    "DATAMATRIX",
                    *flags,
                    "--notext",
                    "-o",
                    path,
                    "-d",
                    data,
                ],
                capture_output=True,
                timeout=30,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                img = Image.open(path).convert("RGB")
                img.load()
                logger.info("KIZ label: GS1 DataMatrix via %s", label)
                return img
            last_err = (r.stderr or r.stdout or "").strip()[:400]
        logger.warning(
            "zint GS1 DataMatrix: all variants failed, last stderr=%s",
            last_err,
        )
        return None
    except Exception as e:
        logger.warning("zint GS1 DataMatrix: %s", e)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _kiz_to_bwipp_gs1_datamatrix_string(raw: str) -> str:
    """
    BWIPP / treepoem barcode_type=gs1datamatrix ожидает человекочитаемый GS1 со скобками:
    (01)GTIN14(21)serial…(91)key4(92)crypto…
    Сырая строка сканера без скобок даёт ошибку: GS1aiMissingOpenParen AIs must start with '('

    Компактный КИЗ Честного ЗНАКА (без GS в строке): 01+14 цифр + 21 + серия 13 + 91+4 + 92+остаток.
    """
    s = (raw or "").strip()
    if not s:
        return s
    if s.startswith("("):
        return s
    # Уже с разделителями GS — разбить и собрать в скобочный формат (первый сегмент = 01…21…)
    if "\x1d" in s:
        parts = [p for p in s.split("\x1d") if p]
        if len(parts) == 1:
            return _kiz_to_bwipp_gs1_datamatrix_string(parts[0])
        out: list[str] = []
        for p in parts:
            if p.startswith("01") and len(p) >= 18 and p[16:18] == "21" and len(p) >= 31:
                out.append(f"(01){p[2:16]}(21){p[18:31]}")
                tail = p[31:]
                if tail:
                    out.append(_kiz_to_bwipp_gs1_datamatrix_string(tail))
            elif p.startswith("91") and len(p) >= 6:
                out.append(f"(91){p[2:6]}")
                if len(p) > 6:
                    rest = p[6:]
                    if rest.startswith("92") and len(rest) >= 2:
                        out.append(f"(92){rest[2:]}")
                    else:
                        out.append(rest)
            elif p.startswith("92") and len(p) >= 2:
                out.append(f"(92){p[2:]}")
            elif p.startswith("93") and len(p) >= 2:
                out.append(f"(93){p[2:]}")
            else:
                out.append(p)
        return "".join(out)

    if not (s.startswith("01") and len(s) >= 18 and s[16:18] == "21"):
        return s

    parsed_full = _parse_kiz_01_21_91_92(s)
    if parsed_full:
        gtin, serial, key, crypto = parsed_full
        return f"(01){gtin}(21){serial}(91){key}(92){crypto}"

    gtin = s[2:16]
    if len(s) < 31:
        serial = s[18:]
        return f"(01){gtin}(21){serial}"

    serial = s[18:31]
    tail = s[31:]
    if not tail:
        return f"(01){gtin}(21){serial}"

    if tail.startswith("91") and len(tail) >= 6:
        key = tail[2:6]
        rest = tail[6:]
        if rest.startswith("92") and len(rest) >= 2:
            return f"(01){gtin}(21){serial}(91){key}(92){rest[2:]}"
        return f"(01){gtin}(21){serial}(91){key}{rest}"

    if tail.startswith("93") and len(tail) >= 2:
        return f"(01){gtin}(21){serial}(93){tail[2:]}"

    return f"(01){gtin}(21){serial}{tail}"


def _generate_kiz_label_pdf(kiz_full: str, kiz_31: str, width_mm: int = 40, height_mm: int = 35) -> bytes:
    """
    PDF этикетки-дубля КИЗ: GS1 DataMatrix (полный код) + 31 символ текстом снизу.
    Размер DataMatrix ~22×22 мм по инструкции WB.

    Сначала пробуем Zint (формат [01]…[21]…[91]…[92]…, --gs1) — ближе к типичным дублям КИЗ.
    Иначе treepoem + BWIPP gs1datamatrix со скобками (01)… — см. _kiz_to_bwipp_gs1_datamatrix_string.
    """
    import io

    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    import treepoem

    raw = (kiz_full or "").strip()
    if not raw:
        raise ValueError("Пустой payload для DataMatrix")

    dm_img = _try_datamatrix_image_zint_gs1(raw)
    if dm_img is None:
        data_for_dm = _kiz_to_bwipp_gs1_datamatrix_string(raw)
        if not data_for_dm.startswith("("):
            raise ValueError(
                "Неверный формат КИЗ для GS1 DataMatrix (ожидается 01…21… или уже (01)…)"
            )
        dm_img = treepoem.generate_barcode(
            barcode_type="gs1datamatrix",
            data=data_for_dm,
        ).convert("RGB")

    dm_size_mm = min(width_mm - 4, height_mm - 12, 22)  # DataMatrix вписывается в этикетку
    label_w = width_mm * mm
    label_h = height_mm * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))
    margin = 1 * mm

    # DataMatrix размер
    dm_src_w, dm_src_h = dm_img.size
    scale = (dm_size_mm * mm) / max(dm_src_w, dm_src_h)
    dm_w = dm_src_w * scale
    dm_h = dm_src_h * scale

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
    dm_buf = io.BytesIO()
    dm_img.save(dm_buf, format="PNG")
    dm_buf.seek(0)
    c.drawImage(
        ImageReader(dm_buf),
        (label_w - dm_w) / 2,
        y_dm_bottom,
        width=dm_w,
        height=dm_h,
        preserveAspectRatio=True,
        mask="auto",
    )

    # 31 символ текстом (центрирован горизонтально)
    c.setFont("Helvetica", font_size)
    c.drawCentredString(label_w / 2, ty, text)

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _normalize_kiz_for_label(raw: str) -> str:
    s = (raw or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()
    if s.startswith("]C1") or s.startswith("]c1") or s.startswith("]D2") or s.startswith("]d2") or s.startswith("]Q3") or s.startswith("]q3"):
        s = s[3:]
    while s and (ord(s[0]) < 32) and (s[0] != "\x1d"):
        s = s[1:]
    return s


def _kiz_31(raw: str) -> str:
    # Только отображение для подписи под кодом: берём первые 31 символа как есть.
    return (raw or "")[:31]


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

    # Снять префиксы сканера (]C1 и т.д.) и управляющие символы — иначе BWIPP не распознаёт 01…21…
    kiz = _normalize_kiz_for_label(kiz_code)

    # Кириллица в КИЗ = сканер работал в русской раскладке.
    # Такой код неверный — сообщаем пользователю и не генерируем DataMatrix.
    if any('\u0400' <= ch <= '\u04FF' for ch in kiz):
        logger.warning("KIZ contains Cyrillic characters (wrong scanner layout): %r", kiz[:40])
        raise HTTPException(
            400,
            detail=(
                "Сканер работал в русской раскладке — код КИЗ содержит кириллицу. "
                "Переключите сканер/клавиатуру на английский (ENG) и отсканируйте повторно."
            ),
        )

    kiz_31 = _kiz_31(kiz)
    if not kiz_31:
        raise HTTPException(400, detail="Пустой КИЗ")
    try:
        pdf_bytes = _generate_kiz_label_pdf(kiz, kiz_31, width_mm=kiz_w, height_mm=kiz_h)
    except Exception as e:
        logger.warning("DataMatrix generation failed (no QR fallback): %s", e)
        raise HTTPException(
            400,
            detail=(
                "Не удалось сформировать DataMatrix из скана КИЗ. "
                "Проверьте раскладку сканера (ENG), префиксы/суффиксы и повторите сканирование."
            ),
        )
    if kiz_rot:
        try:
            pdf_bytes = _rotate_pdf(pdf_bytes, kiz_rot)
        except Exception as _re:
            logger.warning(f"KIZ PDF rotate failed: {_re}")
    # Имя файла только из ASCII-символов, иначе latin-1 в заголовке упадёт
    safe_name = "".join(ch for ch in kiz_31[:20] if ch.isascii() and ch.isprintable()) or "kiz"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=kiz-{safe_name}.pdf"},
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
    """
    Получить заказ с проверкой доступа.

    Упаковщик с owner_id видит заказы магазинов владельца (как в GET /orders);
    при ограничении UserMarketplaceAccess — только указанные marketplace_id.
    """
    order = (
        db.query(Order)
        .options(joinedload(Order.marketplace))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(404, detail="Order not found")
    mp = order.marketplace
    effective_user_id, packer_allowed_mp_ids = _get_effective_user_and_access(
        current_user, db
    )
    if not mp or mp.user_id != effective_user_id:
        raise HTTPException(404, detail="Order not found")
    if packer_allowed_mp_ids is not None and order.marketplace_id not in packer_allowed_mp_ids:
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
        barcode=_order_barcode(order),
        size=_sanitize_size((order.extra_data or {}).get("size")),
        marketplace_created_at=order.marketplace_created_at,
        completed_at=order.completed_at,
        assigned_to_id=order.assigned_to_id,
        assigned_at=order.assigned_at,
        assigned_to_name=order.assigned_to_user.full_name if order.assigned_to_user else None,
        is_locked_by_me=order.is_locked_by(current_user.id),
        is_locked_by_other=order.is_locked_by_other(current_user.id),
        is_printed=_is_printed(order),
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
    ed = order.extra_data if isinstance(order.extra_data, dict) else {}
    ed["printed_in_app"] = True
    ed["printed_at"] = datetime.utcnow().isoformat()
    ed["printed_by_id"] = current_user.id
    order.extra_data = ed
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


def _marketplace_for_order_sync(
    marketplace_id: int, current_user: User, db: Session
) -> Marketplace:
    """Маркетплейс владельца; упаковщик — только из разрешённых (как список заказов)."""
    eff_id, allowed = _get_effective_user_and_access(current_user, db)
    mp = (
        db.query(Marketplace)
        .filter(
            Marketplace.id == marketplace_id,
            Marketplace.user_id == eff_id,
        )
        .first()
    )
    if not mp:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    if allowed is not None and marketplace_id not in allowed:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    return mp


@router.post("/sync/marketplace/{marketplace_id}")
async def sync_orders(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Ручная синхронизация заказов для маркетплейса.
    
    Ozon: заказы «Ожидают отгрузки»
    WB: заказы «На сборке» (new + confirm)
    
    Доступ: администратор (свои магазины) или упаковщик (магазины владельца по доступу).
    """
    marketplace = _marketplace_for_order_sync(marketplace_id, current_user, db)
    try:
        count = await OrderSyncService.sync_marketplace_orders(
            marketplace,
            db,
            sync_source="manual",
        )
    except SyncCooldownError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Синхронизацию можно запускать не чаще 1 раза в час. Повторите через {e.seconds_left} сек.",
        ) from e
    except ManualSyncLockTimeout as e:
        raise HTTPException(
            status_code=409,
            detail="Сейчас уже идёт синхронизация этого маркетплейса. Повторите чуть позже.",
        ) from e
    return {"synced": count, "marketplace_id": marketplace_id}


@router.post("/sync/all")
async def sync_all_orders(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Синхронизация заказов для всех активных маркетплейсов в области видимости пользователя.
    Упаковщик — только разрешённые магазины владельца.
    """
    eff_id, allowed = _get_effective_user_and_access(current_user, db)
    q = db.query(Marketplace).filter(
        Marketplace.user_id == eff_id,
        Marketplace.is_active == True,
    )
    if allowed is not None:
        q = q.filter(Marketplace.id.in_(allowed))
    marketplaces = q.all()
    
    total = 0
    results = []
    cooldown_count = 0
    lock_busy_count = 0
    for mp in marketplaces:
        try:
            count = await OrderSyncService.sync_marketplace_orders(
                mp,
                db,
                sync_source="manual",
            )
            results.append({"marketplace_id": mp.id, "synced": count})
            total += count
        except SyncCooldownError as e:
            cooldown_count += 1
            results.append(
                {
                    "marketplace_id": mp.id,
                    "synced": 0,
                    "skipped": "cooldown",
                    "seconds_left": e.seconds_left,
                }
            )
        except ManualSyncLockTimeout:
            lock_busy_count += 1
            results.append(
                {
                    "marketplace_id": mp.id,
                    "synced": 0,
                    "skipped": "lock_busy",
                }
            )

    payload = {
        "total_synced": total,
        "results": results,
        "total_marketplaces": len(marketplaces),
        "synced_marketplaces": len([r for r in results if (r.get("synced") or 0) > 0]),
        "cooldown_count": cooldown_count,
        "lock_busy_count": lock_busy_count,
    }
    logger.info(
        "Manual sync/all summary",
        extra={
            "user_id": current_user.id,
            "effective_user_id": eff_id,
            "total_marketplaces": payload["total_marketplaces"],
            "total_synced": payload["total_synced"],
            "synced_marketplaces": payload["synced_marketplaces"],
            "cooldown_count": payload["cooldown_count"],
            "lock_busy_count": payload["lock_busy_count"],
        },
    )
    return payload


@router.get("/{order_id}/kiz-suggest")
def suggest_kiz_for_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    order = _get_order_for_user(order_id, current_user, db)
    mp = order.marketplace
    if not mp or not mp.is_kiz_enabled:
        return {"kiz_codes": [], "reason": None}
    try:
        codes = suggest_kiz_codes_fifo_for_order(
            db,
            order=order,
            required_count=order.quantity,
        )
    except ValueError as exc:
        # Для UI автоподстановки не ломаем запрос ошибкой 400 — возвращаем причину.
        return {"kiz_codes": [], "reason": str(exc)}
    return {"kiz_codes": codes, "reason": None}


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
        # Безопасное чтение полей (чтобы не падать при рассинхроне версий схем/контейнеров).
        kiz_codes = getattr(data, "kiz_codes", None)
        kiz_code = getattr(data, "kiz_code", None)

        # До 255 символов: полный КИЗ для WB API / Честного ЗНАКА; этикетки могут показывать 31 символ отдельно.
        _kiz_max = 255
        if kiz_codes:
            try:
                kiz_list = [str(k).strip()[:_kiz_max] for k in kiz_codes if k and str(k).strip()]
            except TypeError:
                # на всякий случай, если kiz_codes вдруг пришёл не как список
                kiz_list = []
        elif kiz_code and str(kiz_code).strip():
            kiz_list = [str(kiz_code).strip()[:_kiz_max]]
    required_count = order.quantity
    if mp.is_kiz_enabled:
        # Если КИЗ не переданы вручную — сервис подберёт их автоматически из пула группы (FIFO).
        if kiz_list and len(kiz_list) < required_count:
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
        if isinstance(e, ValueError):
            raise HTTPException(status_code=400, detail=str(e))
        if isinstance(e, MarketplaceAPIException):
            status = e.status_code
            detail = e.detail if e.detail else str(e)
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("detail") or str(detail)
            if status == 400 and mp and mp.type.value == "wildberries":
                if not detail or str(detail).strip() in ("", "Incorrect Request"):
                    detail = (
                        "Wildberries отклонил запрос КИЗ (400). Частые причины: задание не в поставке "
                        "(нужен статус confirm), в задании не запрошен sgtin, или неверный формат кода маркировки. "
                        "Обновите заказы и проверьте личный кабинет WB."
                    )
            if status == 409 and mp and mp.type.value == "wildberries":
                detail = (
                    "Wildberries не принял КИЗ для этого задания: по их ответу задание не в подходящем статусе "
                    "(часто уже не «в сборке» / Processing, отменено, убрано из поставки или ID не совпадает). "
                    f"Ответ WB: {detail}. Синхронизируйте заказы и проверьте задание в личном кабинете."
                )
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


def _fit_font_size_to_width(
    text: str,
    *,
    font_name: str,
    max_width: float,
    max_size: float,
    min_size: float,
) -> float:
    """Подобрать размер шрифта, чтобы текст влезал в max_width."""
    from reportlab.pdfbase import pdfmetrics

    if not text:
        return max_size
    sz = max_size
    while sz > min_size:
        if pdfmetrics.stringWidth(text, font_name, sz) <= max_width:
            return sz
        sz -= 0.5
    return min_size


def _ellipsize_to_width(text: str, *, font_name: str, font_size: float, max_width: float) -> str:
    """Обрезать текст по ширине с добавлением '...'."""
    from reportlab.pdfbase import pdfmetrics

    if not text:
        return ""
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text
    ell = "..."
    ell_w = pdfmetrics.stringWidth(ell, font_name, font_size)
    if ell_w >= max_width:
        return ""
    out = text
    while out and (pdfmetrics.stringWidth(out, font_name, font_size) + ell_w > max_width):
        out = out[:-1]
    return (out + ell) if out else ""


def _draw_article_and_size_line(
    c,
    *,
    label_w: float,
    y: float,
    margin: float,
    article: str,
    size: Optional[str],
    is_wb: bool,
) -> None:
    """
    Отрисовка подписи над ШК:
    - WB: артикул + размер с адаптивной подгонкой по ширине.
    - Ozon/прочие: только артикул (центрированно).
    """
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics

    article_text = re.sub(r"\s+", " ", str(article or "").strip())
    if not article_text and not size:
        return

    available_w = max(1.0, label_w - 2 * margin)
    article_font = "Helvetica"
    size_font = "Helvetica-Bold"

    if not is_wb:
        fs = _fit_font_size_to_width(
            article_text,
            font_name=article_font,
            max_width=available_w,
            max_size=9.0,
            min_size=6.0,
        )
        out = _ellipsize_to_width(article_text, font_name=article_font, font_size=fs, max_width=available_w)
        if out:
            c.setFont(article_font, fs)
            c.drawCentredString(label_w / 2, y, out)
        return

    size_text = _sanitize_size(size)
    size_text = re.sub(r"\s+", " ", size_text).strip()[:16] if size_text else ""

    # Если размера нет, WB ведём как обычный single-line.
    if not size_text:
        fs = _fit_font_size_to_width(
            article_text,
            font_name=article_font,
            max_width=available_w,
            max_size=9.0,
            min_size=6.0,
        )
        out = _ellipsize_to_width(article_text, font_name=article_font, font_size=fs, max_width=available_w)
        if out:
            c.setFont(article_font, fs)
            c.drawCentredString(label_w / 2, y, out)
        return

    gap = 1.2 * mm
    # Размеру даём ограниченную, но гарантированную полосу.
    size_lane_max = max(available_w * 0.28, 9 * mm)
    size_lane_max = min(size_lane_max, available_w * 0.45)
    size_fs = _fit_font_size_to_width(
        size_text,
        font_name=size_font,
        max_width=size_lane_max,
        max_size=9.0,
        min_size=6.0,
    )
    size_out = _ellipsize_to_width(size_text, font_name=size_font, font_size=size_fs, max_width=size_lane_max)
    size_w = pdfmetrics.stringWidth(size_out, size_font, size_fs) if size_out else 0.0

    article_lane = max(available_w - size_w - gap, available_w * 0.45)
    article_fs = _fit_font_size_to_width(
        article_text,
        font_name=article_font,
        max_width=article_lane,
        max_size=9.0,
        min_size=6.0,
    )
    article_out = _ellipsize_to_width(
        article_text, font_name=article_font, font_size=article_fs, max_width=article_lane
    )
    article_w = pdfmetrics.stringWidth(article_out, article_font, article_fs) if article_out else 0.0

    total_w = article_w + (gap + size_w if article_out and size_out else 0.0)
    x_left = (label_w - total_w) / 2
    x_left = max(margin, min(x_left, label_w - margin - total_w))

    if article_out:
        c.setFont(article_font, article_fs)
        c.drawString(x_left, y, article_out)
    if size_out:
        c.setFont(size_font, size_fs)
        c.drawString(x_left + article_w + (gap if article_out else 0.0), y, size_out)


def _create_barcode_drawing(
    code: str,
    bar_width: float = 0.25,
    hide_text: bool = False,
    bar_height: Optional[float] = None,
    quiet: Optional[bool] = None,
):
    """
    Создать Drawing со штрихкодом (reportlab). EAN13 для 13 цифр, иначе Code128.
    hide_text: для EAN13 убрать встроенные цифры (чтобы рисовать свои с нужным отступом).
    """
    from reportlab.graphics.barcode import createBarcodeDrawing

    code = str(code).strip()
    if len(code) == 13 and code.isdigit():
        kwargs: dict = {"value": code[:12], "barWidth": bar_width}
        if bar_height is not None:
            kwargs["barHeight"] = bar_height
        if quiet is not None:
            kwargs["quiet"] = quiet
        if hide_text:
            kwargs["humanReadable"] = 0
        try:
            return createBarcodeDrawing("EAN13", **kwargs)
        except TypeError:
            kwargs.pop("humanReadable", None)
            kwargs.pop("quiet", None)
            return createBarcodeDrawing("EAN13", **kwargs)
    kwargs = {"value": code, "barWidth": bar_width}
    if bar_height is not None:
        kwargs["barHeight"] = bar_height
    if quiet is not None:
        kwargs["quiet"] = quiet
    return createBarcodeDrawing("Code128", **kwargs)


def _is_ean13(code: str) -> bool:
    """EAN13: 13 цифр (WB). OZN — не EAN13."""
    s = str(code).strip()
    return len(s) == 13 and s.isdigit()


# Отступ сверху для ШК товара Ozon — как у ФБС этикетки (к краю, минимальный)
_BARCODE_TOP_OFFSET_MM = 1.5


def _generate_product_barcode_pdf(
    barcode_value: str,
    ozn_code: str = "",
    article: str = "",
    size: Optional[str] = None,
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
    is_ozon_code = str(display_code).strip().upper().startswith("OZN")
    is_wb_barcode = is_ean and not is_ozon_code
    # Раздельная геометрия по маркетплейсам:
    # - Ozon (OZN...): оставляем базовую геометрию, quiet=False.
    # - WB (EAN13): делаем чуть ниже, но шире.
    wb_bar_width = 0.52 if is_wb_barcode else 0.4
    wb_bar_height = (14 * mm) if is_wb_barcode else None
    # EAN13: скрываем встроенные цифры, рисуем свои с отступом
    bc_product = _create_barcode_drawing(
        barcode_value,
        bar_width=wb_bar_width,
        hide_text=is_ean,
        bar_height=wb_bar_height,
        quiet=False if is_ozon_code and not is_ean else None,
    )
    bw1, bh1 = bc_product.width, bc_product.height

    label_w = label_width_mm * mm
    label_h = 40 * mm
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    h = label_h
    margin = 1 * mm
    top_offset = top_offset_mm * mm
    x0 = margin
    # Рисуем так, чтобы блок (штрихкод + цифры) занимал почти всю высоту этикетки и был центрирован.
    # top_offset_mm используем как "смещение вверх" (для Ozon), чтобы не обрезать верхние элементы.
    article_font_size = 9
    digits_font_size = 10
    # Резерв под 2 строки: артикул + номер ШК
    article_gap = 8 * mm
    digits_gap = 3.5 * mm
    digits_reserved = article_gap + digits_gap + 1 * mm

    available_h_for_barcode = label_h - 2 * margin - digits_reserved
    if available_h_for_barcode <= 0:
        available_h_for_barcode = label_h - 2 * margin

    scale_fit_reserved = min((label_w - 2 * margin) / bw1, available_h_for_barcode / bh1)
    # WORKING: пропорционально увеличиваем Ozon относительно базового fit.
    # Без прежнего "верхнего зажима", который обнулял эффект.
    # Уменьшаем Ozon ШК относительно базового fit.
    # Важно: раньше эффект мог быть "срезан" clamp'ом scale_page_limit, поэтому
    # задаём более нейтральный коэффициент (1.0), чтобы реально ушло вниз.
    # Для видимого уменьшения нужно уходить <1.0,
    # иначе масштаб может клиповаться по width-limit (label_w-2*margin).
    ozon_scale_boost = 0.9 if is_ozon_code and not is_ean else 1.0
    scale1 = scale_fit_reserved * ozon_scale_boost
    # Защита от выхода за лист (58x40), но не от "резерва подписи" — чтобы рост реально был виден.
    scale_page_limit = min((label_w - 2 * margin) / bw1, (label_h - 2 * margin) / bh1)
    if scale1 > scale_page_limit:
        scale1 = scale_page_limit
    draw_w = bw1 * scale1
    draw_h = bh1 * scale1

    barcode_left = margin + (label_w - 2 * margin - draw_w) / 2
    barcode_bottom = margin + digits_reserved + (available_h_for_barcode - draw_h) / 2 + top_offset

    c.saveState()
    c.translate(barcode_left, barcode_bottom)
    c.scale(scale1, scale1)
    renderPDF.draw(bc_product, c, 0, 0)
    c.restoreState()

    ay = max(margin + digits_gap, barcode_bottom - article_gap)
    _draw_article_and_size_line(
        c,
        label_w=label_w,
        y=ay,
        margin=margin,
        article=str(article or "").strip(),
        size=size,
        is_wb=is_wb_barcode,
    )
    ty = max(margin, ay - digits_gap)
    c.setFont("Helvetica-Bold", digits_font_size)
    c.drawCentredString(label_w / 2, ty, str(display_code)[:20])

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _generate_multi_product_barcode_pdf(
    items: list[tuple[str, str, str, Optional[str]]],
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
        return _generate_product_barcode_pdf(
            items[0][0], items[0][1], items[0][2], items[0][3], label_width_mm, top_offset_mm
        )

    label_w = label_width_mm * mm
    label_h = 40 * mm
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    margin = 1 * mm
    top_offset = top_offset_mm * mm
    x0 = margin
    article_font_size = 9
    digits_font_size = 10
    # Резерв под 2 строки: артикул + номер ШК
    article_gap = 8 * mm
    digits_gap = 3.5 * mm
    digits_reserved = article_gap + digits_gap + 1 * mm

    available_h_for_barcode = label_h - 2 * margin - digits_reserved
    if available_h_for_barcode <= 0:
        available_h_for_barcode = label_h - 2 * margin

    for i, (barcode_value, ozn_code, article, size) in enumerate(items):
        if i > 0:
            c.showPage()
        display_code = ozn_code or barcode_value
        is_ean = _is_ean13(barcode_value)
        is_ozon_code = str(display_code).strip().upper().startswith("OZN")
        is_wb_barcode = is_ean and not is_ozon_code
        wb_bar_width = 0.52 if is_wb_barcode else 0.4
        wb_bar_height = (14 * mm) if is_wb_barcode else None
        bc_product = _create_barcode_drawing(
            barcode_value,
            bar_width=wb_bar_width,
            hide_text=is_ean,
            bar_height=wb_bar_height,
            quiet=False if is_ozon_code and not is_ean else None,
        )
        bw1, bh1 = bc_product.width, bc_product.height
        scale_fit_reserved = min((label_w - 2 * margin) / bw1, available_h_for_barcode / bh1)
        ozon_scale_boost = 0.9 if is_ozon_code and not is_ean else 1.0
        scale1 = scale_fit_reserved * ozon_scale_boost
        scale_page_limit = min((label_w - 2 * margin) / bw1, (label_h - 2 * margin) / bh1)
        if scale1 > scale_page_limit:
            scale1 = scale_page_limit
        draw_w = bw1 * scale1
        draw_h = bh1 * scale1

        barcode_left = x0 + (label_w - 2 * margin - draw_w) / 2
        barcode_bottom = margin + digits_reserved + (available_h_for_barcode - draw_h) / 2 + top_offset
        c.saveState()
        c.translate(barcode_left, barcode_bottom)
        c.scale(scale1, scale1)
        renderPDF.draw(bc_product, c, 0, 0)
        c.restoreState()

        ay = max(margin + digits_gap, barcode_bottom - article_gap)
        _draw_article_and_size_line(
            c,
            label_w=label_w,
            y=ay,
            margin=margin,
            article=str(article or "").strip(),
            size=size,
            is_wb=is_wb_barcode,
        )
        ty = max(margin, ay - digits_gap)
        c.setFont("Helvetica-Bold", digits_font_size)
        c.drawCentredString(label_w / 2, ty, str(display_code)[:20])

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

    from PIL import Image

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
        from PIL import ImageDraw, ImageFont

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
    scale_factor: float = 1.0,
) -> bytes:
    """
    Конвертировать PNG-стикер WB в PDF — та же логика, что у этикетки Ozon:
    лист книжной ориентации (40×58 мм), этикетка в альбомном виде прижата к верхнему левому углу.
    """
    import io

    from PIL import Image
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    debug_job_key = "wb_fbs"
    _fbs_debug_write_bytes(debug_job_key, "00_input", "input.png", image_bytes)

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")

    try:
        rotate = int(rotate) if rotate is not None else 90
    except (TypeError, ValueError):
        rotate = 90
    # Точно как у Ozon: 0/90/180/270 из настроек; при формате 58×40 и портрете (ih>iw) — по умолчанию 90
    if rotate in (0, 90, 180, 270):
        deg = rotate
    elif label_width_mm > label_height_mm and ih > iw:
        deg = 90
    else:
        deg = 0
    logger.info(
        "WB FBS label: size %sx%s rotate_setting=%s applied_deg=%s",
        iw, ih, rotate, deg,
    )

    # Сначала кроп (без поворота), потом разделение по белому поясу, затем поворот только этикетки; строчку не крутим и кладём в самый верх
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

    _fbs_debug_save_pil(debug_job_key, "01_after_white_bbox_crop", "after_white_bbox.png", img)
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

    _fbs_debug_save_pil(debug_job_key, "02_after_top_strip_crop", "after_top_strip.png", img)

    # Ищем белый пояс: верх = этикетка (её повернём), низ = строчка (без поворота, прижмём к верху страницы)
    # Берём самый широкий пояс в нижней половине картинки (между этикеткой и строчкой), а не первый попавшийся
    line_at_top = False
    try:
        thresh = 250
        pix = img.load()
        band_min_rows = 3
        dark_frac = 0.10
        bands = []
        y_band_start = y_band_end = None
        for y in range(ih):
            dark = sum(1 for x in range(iw) if (pix[x, y] if isinstance(pix[x, y], int) else max(pix[x, y][:3])) < thresh)
            if dark < max(2, int(iw * dark_frac)):
                if y_band_start is None:
                    y_band_start = y
                y_band_end = y
            else:
                if y_band_start is not None and (y_band_end - y_band_start + 1) >= band_min_rows:
                    bands.append((y_band_start, y_band_end))
                y_band_start = None
                y_band_end = None
        if y_band_start is not None and (y_band_end - y_band_start + 1) >= band_min_rows:
            bands.append((y_band_start, y_band_end))
        best_start, best_end = None, None
        best_len = 0
        for (ys, ye) in bands:
            length = ye - ys + 1
            mid = (ys + ye) / 2
            if length >= band_min_rows and mid >= ih * 0.25 and length > best_len:
                best_len = length
                best_start, best_end = ys, ye
        if best_start is None and bands:
            ys, ye = max(bands, key=lambda b: b[1] - b[0] + 1)
            if ye - ys + 1 >= band_min_rows:
                best_start, best_end = ys, ye
        if best_start is not None and best_end is not None:
            y_band_start, y_band_end = best_start, best_end
        if y_band_start is not None and y_band_end is not None and (y_band_end - y_band_start + 1) >= band_min_rows:
            top_img = img.crop((0, 0, iw, y_band_start))
            bottom_img = img.crop((0, y_band_end + 1, iw, ih))
            # Поворот только для этикетки (top_img)
            if deg:
                if deg == 90 and top_img.size[1] > top_img.size[0]:
                    top_img = top_img.transpose(Image.Transpose.ROTATE_270)
                elif deg == 270 and top_img.size[0] > top_img.size[1]:
                    top_img = top_img.transpose(Image.Transpose.ROTATE_90)
                elif deg == 180:
                    top_img = top_img.transpose(Image.Transpose.ROTATE_180)
            # Строчка (bottom_img) — без поворота, только bbox + первая тёмная строка, прижать
            bw, bh = bottom_img.size
            if bw > 0 and bh > 0:
                bpix = bottom_img.load()
                bmin_x, bmin_y, bmax_x, bmax_y = bw, bh, 0, 0
                for by in range(bh):
                    for bx in range(bw):
                        p = bpix[bx, by]
                        v = (p if isinstance(p, int) else max(p[:3]))
                        if v < thresh:
                            bmin_x, bmin_y = min(bmin_x, bx), min(bmin_y, by)
                            bmax_x, bmax_y = max(bmax_x, bx), max(bmax_y, by)
                if bmax_x >= bmin_x and bmax_y >= bmin_y and (bmax_x - bmin_x) > 4 and (bmax_y - bmin_y) > 4:
                    bottom_img = bottom_img.crop((bmin_x, bmin_y, bmax_x + 1, bmax_y + 1))
                bw, bh = bottom_img.size
                btop = 0
                try:
                    bpix2 = bottom_img.load()
                    for by in range(bh):
                        for bx in range(bw):
                            p = bpix2[bx, by]
                            if (p if isinstance(p, int) else max(p[:3])) < 253:
                                btop = by
                                break
                        else:
                            continue
                        break
                    if btop > 0 and bh - btop > 5:
                        bottom_img = bottom_img.crop((0, btop, bw, bh))
                except Exception:
                    pass
            # Поворот только строчки на 180°
            bottom_img = bottom_img.transpose(Image.Transpose.ROTATE_180)
            # Собираем: этикетка по размеру; строчка прижата к верху и накладывается на этикетку
            new_h = top_img.size[1]
            new_w = max(top_img.size[0], bottom_img.size[0])
            img = Image.new("RGB", (new_w, new_h), (255, 255, 255))
            img.paste(top_img, (0, 0))
            img.paste(bottom_img, (0, 0))
            iw, ih = img.size
            line_at_top = True
            logger.info("WB label: строчка прижата к верху (горизонтальный белый пояс)")
            _fbs_debug_save_pil(debug_job_key, "03_after_line_split_merge", "after_line_split_merge.png", img)
        else:
            logger.info("WB label: горизонтальный пояс не сработал — bands=%s best_start=%s ih=%s iw=%s", len(bands), best_start, ih, iw)
    except Exception as e:
        logger.warning("WB label: ошибка при поиске горизонтального пояса: %s", e, exc_info=True)

    if not line_at_top:
        # Белый пояс не нашли — крутим всё изображение
        if deg:
            if deg == 90 and ih > iw:
                img = img.transpose(Image.Transpose.ROTATE_270)
                iw, ih = img.size
            elif deg == 270 and iw > ih:
                img = img.transpose(Image.Transpose.ROTATE_90)
                iw, ih = img.size
            elif deg == 180:
                img = img.transpose(Image.Transpose.ROTATE_180)
                iw, ih = img.size

    # Подтянуть всё вверх: если есть большой белый пояс в середине — убрать его, нижний блок прижать к верху (наложение)
    if ih > 30 and iw > 10:
        try:
            pix = img.load()
            t = 250
            dark_frac = 0.12
            best_band_start = None
            best_band_end = None
            best_band_len = 0
            y_start = None
            y_end = None
            for y in range(ih):
                dark = sum(1 for x in range(iw) if (pix[x, y] if isinstance(pix[x, y], int) else max(pix[x, y][:3])) < t)
                if dark < max(2, int(iw * dark_frac)):
                    if y_start is None:
                        y_start = y
                    y_end = y
                else:
                    if y_start is not None:
                        band_len = y_end - y_start + 1
                        if band_len >= max(5, int(ih * 0.05)) and y_start >= int(ih * 0.05) and y_end <= int(ih * 0.95) and band_len > best_band_len:
                            best_band_len = band_len
                            best_band_start = y_start
                            best_band_end = y_end
                    y_start = None
                    y_end = None
            if y_start is not None:
                band_len = y_end - y_start + 1
                if band_len >= max(5, int(ih * 0.05)) and y_start >= int(ih * 0.05) and y_end <= int(ih * 0.95) and band_len > best_band_len:
                    best_band_start = y_start
                    best_band_end = y_end
            if best_band_start is not None and best_band_end is not None:
                top_part = img.crop((0, 0, iw, best_band_start))
                bottom_part = img.crop((0, best_band_end + 1, iw, ih))
                new_h = top_part.size[1]
                new_w = max(top_part.size[0], bottom_part.size[0])
                img = Image.new("RGB", (new_w, new_h), (255, 255, 255))
                img.paste(top_part, (0, 0))
                img.paste(bottom_part, (0, 0))
                iw, ih = img.size
                logger.info("WB label: строчка прижата к верху (сжатие белого пояса по середине)")
            else:
                logger.info("WB label: сжатие пояса не сработало — best_band_len=%s ih=%s", best_band_len, ih)
        except Exception as e:
            logger.warning("WB label: ошибка при сжатии белого пояса: %s", e, exc_info=True)

    _fbs_debug_save_pil(debug_job_key, "04_after_final_trims", "after_final_trims.png", img)

    # Не давать надписи уходить низко: при сильной вытянутости по высоте режем снизу
    if ih > iw * 1.35:
        max_h = max(int(iw * 1.25), int(ih * 0.82))
        if max_h < ih:
            img = img.crop((0, 0, iw, max_h))
            iw, ih = img.size

    # Лист альбомной ориентации: ширина×высота = label_width_mm×label_height_mm (например 58×40).
    # Прижать к верхнему левому углу.
    # scale_factor > 1: страница PDF и контент расширяются вместе.
    page_width_mm = label_width_mm
    page_height_mm = label_height_mm
    sf = max(1.0, float(scale_factor))
    frame_w_pt = page_width_mm * mm * sf
    frame_h_pt = page_height_mm * mm * sf
    # Маленький технологический отступ слева, чтобы печать не прилипала к кромке.
    margin_left_pt = 1.0 * mm
    margin_top_pt = 0.0 * mm
    usable_w = max(1.0, frame_w_pt - margin_left_pt)
    usable_h = frame_h_pt

    scale = min(usable_w / iw, usable_h / ih)
    draw_w = iw * scale
    draw_h = ih * scale
    x_place = margin_left_pt
    y_place = frame_h_pt - margin_top_pt - draw_h

    # debug: что реально идёт на отрисовку (в виде PIL-рисунка, приблизительно в px)
    try:
        scaled_w = max(1, int(iw * scale))
        scaled_h = max(1, int(ih * scale))
        img_scaled = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
        _fbs_debug_save_pil(debug_job_key, "05_scaled_for_draw", "scaled.png", img_scaled)
    except Exception:
        pass

    # Источник изображения, который ReportLab масштабирует при drawImage(...)
    _fbs_debug_save_pil(debug_job_key, "06_pdf_draw_source", "source.png", img)

    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(frame_w_pt, frame_h_pt))
    c.drawImage(
        ImageReader(img_buf),
        x_place, y_place, width=draw_w, height=draw_h,
        preserveAspectRatio=True,
    )
    c.save()
    buf.seek(0)
    content = buf.getvalue()
    _fbs_debug_write_bytes(debug_job_key, "07_output", "output.pdf", content)
    _fbs_debug_write_json(
        debug_job_key,
        "98_meta",
        "meta.json",
        {
            "label_width_mm": label_width_mm,
            "label_height_mm": label_height_mm,
            "rotate": rotate,
            "scale_factor": scale_factor,
            "debug": "wb_sticker_to_pdf",
        },
    )
    return content


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

    order = _get_order_for_user(order_id, current_user, db)
    mp = order.marketplace
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

    order = _get_order_for_user(order_id, current_user, db)
    mp = order.marketplace

    items: list[tuple[str, str, str, Optional[str]]] = []

    if mp.type == MarketplaceType.WILDBERRIES:
        # WB: товарный баркод хранится в extra_data["skus"] (EAN13 или Code128)
        extra = order.extra_data or {}
        skus: list = extra.get("skus") or []
        article = str(order.article or "").strip()
        wb_size = _sanitize_size(extra.get("size"))
        for sku_val in skus:
            code = str(sku_val).strip()
            if code:
                items.append((code, code, article, wb_size))
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
            article = str(p.get("offer_id") or p.get("article") or order.article or "").strip()
            if not ozn_code:
                continue
            for _ in range(qty):
                # Для Ozon размер не добавляем: он уже зашит в артикул/offer_id.
                items.append((ozn_code, ozn_code, article, None))

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

    debug_job_key = "ozon_barcode" if mp.type == MarketplaceType.OZON else "wb_barcode"
    _fbs_debug_write_json(
        debug_job_key,
        "00_params",
        "params.json",
        {
            "order_id": order_id,
            "label_width_mm": label_width,
            "top_offset_mm": top_offset,
            "items_count": len(items),
            "barcode_rotate_setting": None if mp.type != MarketplaceType.OZON else ps_barcode.barcode_rotate,
        },
    )
    _fbs_debug_write_bytes(debug_job_key, "01_unrotated", "barcode.pdf", pdf_bytes)
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

    _fbs_debug_write_bytes(debug_job_key, "02_after_rotate", "barcode.pdf", pdf_bytes)
    _fbs_debug_write_json(
        debug_job_key,
        "98_meta",
        "meta.json",
        {
            "barcode_rotate": barcode_rotate,
            "debug": "get_order_barcodes_pdf",
        },
    )
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

    order = _get_order_for_user(order_id, current_user, db)
    mp = order.marketplace
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
                scale_factor = float(_ps.label_scale_factor) if _ps.label_scale_factor is not None else 1.0
            else:
                w_mm, h_mm, ozon_rot, printer_dpi = 58, 40, 90, 203
                label_mode = "standard_58x40_noscale"
                scale_factor = 1.0
        except Exception:
            w_mm, h_mm, ozon_rot, printer_dpi = 58, 40, 90, 203
            label_mode = "standard_58x40_noscale"
            scale_factor = 1.0
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
            # Всегда размещаем этикетку на листе правильного размера (58×40) — без A4.
            # Не возвращаем сырой PDF от Ozon (A4) при ошибке — поднимаем исключение.
            content = _ozon_fbs_to_standard_label(
                content, width_mm=w_mm, height_mm=h_mm, rotate=ozon_rot, dpi=printer_dpi,
                scale_factor=scale_factor,
            )
        except Exception as _re:
            logger.warning("Ozon FBS to standard label failed: %s", _re, exc_info=True)
            raise HTTPException(
                500,
                detail="Не удалось сформировать этикетку 58×40. Проверьте pdf2image/poppler. Ошибка: " + str(_re),
            ) from _re
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
        wb_rotate = (ps.wb_label_rotate if ps.wb_label_rotate is not None else 90) if ps else 90
        scale_factor = float(ps.label_scale_factor) if ps and ps.label_scale_factor is not None else 1.0
        logger.info("WB label: wb_label_rotate=%s (from print_settings)", wb_rotate)
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
        # Всегда размещаем этикетку на листе правильного размера (58×40) — без A4
        content = _wb_sticker_to_pdf(
            content, label_width_mm=w, label_height_mm=h,
            order_number=order_num, rotate=wb_rotate,
            scale_factor=scale_factor,
        )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=label-{order.posting_number}.pdf"},
        )
    raise HTTPException(400, detail="Unknown marketplace type")
