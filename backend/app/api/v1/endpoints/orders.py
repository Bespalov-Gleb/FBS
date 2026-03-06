"""
API endpoints для заказов и синхронизации
"""
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.utils.logger import logger
from app.core.dependencies import CurrentAdminUser, CurrentUser
from app.models.marketplace import Marketplace
from app.models.order import Order, OrderStatus
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderProductItem, OrderResponse, OrdersListResponse
from app.services.marketplace.wildberries import WildberriesClient
from app.services.order_complete_service import OrderCompleteService
from app.services.order_sync_service import OrderSyncService

router = APIRouter(prefix="/orders", tags=["Orders"])


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


def _ozon_product_size(p: dict) -> Optional[str]:
    """Размер товара Ozon из product dict."""
    dims = p.get("dimensions")
    if isinstance(dims, dict):
        return dims.get("size_name") or dims.get("size")
    return p.get("size_name") or p.get("size")


def _order_products(o: Order) -> list[OrderProductItem]:
    """Список товаров в заказе (Ozon: несколько в одном posting)."""
    if not o.marketplace or o.marketplace.type.value != "ozon":
        return []
    prods = (o.extra_data or {}).get("products", [])
    return [
        OrderProductItem(
            offer_id=str(p.get("offer_id", "")),
            name=str(p.get("name", "")),
            quantity=int(p.get("quantity", 1)),
            image_url=str(p.get("image_url", "")),
            size=_ozon_product_size(p),
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
    order_repo = OrderRepository(db)
    total = order_repo.get_list_count(
        user_id=current_user.id,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        status=status_enum,
        search=search,
    )
    orders = order_repo.get_list(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        marketplace_ids=marketplace_ids,
        marketplace_types=marketplace_types,
        warehouse_ids=warehouse_ids,
        status=status_enum,
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
            size=(o.extra_data or {}).get("size"),
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


@router.get("/kiz-export")
def kiz_export(
    marketplace_id: Optional[int] = Query(None, description="Фильтр по маркетплейсу"),
    export_format: str = Query("xlsx", description="xlsx | txt"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    Выгрузка КИЗ собранных заказов.
    Возвращает Excel или TXT со всеми просканированными КИЗ.
    """
    from datetime import datetime
    from io import BytesIO

    query = (
        db.query(Order)
        .join(Marketplace)
        .filter(Marketplace.user_id == current_user.id)
        .filter(Order.status == OrderStatus.COMPLETED)
        .filter(Order.kiz_code.isnot(None))
        .filter(Order.kiz_code != "")
    )
    if marketplace_id:
        query = query.filter(Order.marketplace_id == marketplace_id)
    orders = query.order_by(Order.completed_at.desc()).limit(10000).all()

    rows = []
    for o in orders:
        rows.append({
            "kiz_code": o.kiz_code or "",
            "posting_number": o.posting_number,
            "article": o.article,
            "product_name": (o.product_name or "")[:100],
            "completed_at": o.completed_at.strftime("%Y-%m-%d %H:%M") if o.completed_at else "",
            "marketplace": o.marketplace.type.value if o.marketplace else "",
        })

    if export_format == "txt":
        lines = [r["kiz_code"] for r in rows]
        content = "\n".join(lines).encode("utf-8")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=kiz-export-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.txt",
            },
        )

    # xlsx
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "КИЗ"
    ws.append(["КИЗ", "Номер отправления", "Артикул", "Товар", "Дата сборки", "Маркетплейс"])
    for r in rows:
        ws.append([r["kiz_code"], r["posting_number"], r["article"], r["product_name"], r["completed_at"], r["marketplace"]])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=kiz-export-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.xlsx",
        },
    )


def _generate_kiz_label_pdf(kiz_full: str, kiz_31: str) -> bytes:
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

    dm_size_mm = 22
    label_w = 40 * mm
    label_h = 35 * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))
    margin = 2 * mm
    x0 = margin
    y0 = label_h - margin

    # DataMatrix 22×22 мм
    scale = (dm_size_mm * mm) / max(dm.width, dm.height)
    dm_w = dm.width * scale
    dm_h = dm.height * scale
    c.saveState()
    c.translate(x0 + (label_w - 2 * margin - dm_w) / 2, y0 - dm_h)
    c.scale(scale, scale)
    renderPDF.draw(dm, c, 0, 0)
    c.restoreState()

    # 31 символ текстом снизу
    ty = y0 - dm_h - 4 * mm
    c.setFont("Helvetica", 8)
    c.drawCentredString(label_w / 2, ty, kiz_31[:31])

    c.save()
    buf.seek(0)
    return buf.getvalue()


@router.get("/kiz-label")
def get_kiz_label(
    kiz_code: str = Query(..., min_length=1, description="Код КИЗ (маркировка, полный или 31 символ)"),
    current_user: User = CurrentUser,
):
    """
    Этикетка-дубль КИЗ для печати после сканирования.
    DataMatrix с полным КИЗ + 31 символ текстом снизу (для ручного ввода).
    Возвращает PDF.
    """
    kiz = kiz_code.strip()
    kiz_31 = kiz[:31]
    try:
        pdf_bytes = _generate_kiz_label_pdf(kiz, kiz_31)
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
        size=(order.extra_data or {}).get("size"),
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
    kiz = (data.kiz_code if data else None) or None
    if mp.is_kiz_enabled and not kiz:
        raise HTTPException(400, detail="kiz_code required for this marketplace")
    try:
        ok = await OrderCompleteService.complete_order(
            order, current_user.id, kiz, db,
        )
    except Exception as e:
        from app.core.exceptions import MarketplaceAPIException
        if isinstance(e, MarketplaceAPIException):
            detail = e.detail if e.detail else str(e)
            raise HTTPException(status_code=e.status_code, detail=detail)
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


def _create_barcode_drawing(code: str, bar_width: float = 0.25):
    """Создать Drawing со штрихкодом (reportlab). EAN13 для 13 цифр, иначе Code128."""
    from reportlab.graphics.barcode import createBarcodeDrawing

    code = str(code).strip()
    if len(code) == 13 and code.isdigit():
        return createBarcodeDrawing("EAN13", value=code[:12], barWidth=bar_width)
    return createBarcodeDrawing("Code128", value=code, barWidth=bar_width)


def _generate_product_barcode_pdf(
    barcode_value: str,
    ozn_code: str = "",
    label_width_mm: int = 58,
) -> bytes:
    """
    Штрихкод товара (Ozon): большой штрихкод + OZN-код. Без названия.
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    display_code = ozn_code or barcode_value
    label_w = label_width_mm * mm
    label_h = 45 * mm  # чуть выше для отступа между штрихкодом и кодом
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    h = label_h
    margin = 2 * mm
    x0 = margin
    y0 = h - margin

    # Большой штрихкод — занимает почти всю ширину, чуть больше
    bc_product = _create_barcode_drawing(barcode_value, bar_width=0.4)
    bw1, bh1 = bc_product.width, bc_product.height
    scale1 = min((label_w - 2 * margin) / bw1, 25 * mm / bh1, 2.2)
    c.saveState()
    c.translate(x0 + (label_w - bw1 * scale1) / 2, y0 - bh1 * scale1 - 2 * mm)
    c.scale(scale1, scale1)
    renderPDF.draw(bc_product, c, 0, 0)
    c.restoreState()

    # Отступ 6 мм между штрихкодом и OZN-кодом, чтобы не налезал
    ty = y0 - bh1 * scale1 - 8 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x0 + label_w / 2, ty, str(display_code)[:20])

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _generate_multi_product_barcode_pdf(
    items: list[tuple[str, str]],
    label_width_mm: int = 58,
) -> bytes:
    """
    PDF с несколькими страницами — по одному штрихкоду на каждый товар (Ozon двойные заказы).
    items: [(barcode_value, ozn_code), ...]
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    if not items:
        raise ValueError("No items for barcode PDF")
    if len(items) == 1:
        return _generate_product_barcode_pdf(items[0][0], items[0][1], label_width_mm)

    label_w = label_width_mm * mm
    label_h = 45 * mm
    pagesize = (label_w, label_h)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    margin = 2 * mm
    x0 = margin

    for i, (barcode_value, ozn_code) in enumerate(items):
        if i > 0:
            c.showPage()
        display_code = ozn_code or barcode_value
        h = label_h
        y0 = h - margin

        bc_product = _create_barcode_drawing(barcode_value, bar_width=0.4)
        bw1, bh1 = bc_product.width, bc_product.height
        scale1 = min((label_w - 2 * margin) / bw1, 25 * mm / bh1, 2.2)
        c.saveState()
        c.translate(x0 + (label_w - bw1 * scale1) / 2, y0 - bh1 * scale1 - 2 * mm)
        c.scale(scale1, scale1)
        renderPDF.draw(bc_product, c, 0, 0)
        c.restoreState()

        ty = y0 - bh1 * scale1 - 8 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x0 + label_w / 2, ty, str(display_code)[:20])

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _generate_barcodes_pdf(
    product_code: str,
    fbs_code: str,
    product_name: str = "",
    label_width_mm: int = 58,
) -> bytes:
    """
    Генерация PDF с обоими штрихкодами (товар + ФБС) для качественной печати.
    Страница = размер этикетки (58×40 или 80×40 мм) — без лишнего белого пространства.
    """
    import io

    from reportlab.graphics import renderPDF
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    label_w = label_width_mm * mm
    label_h = 40 * mm
    pagesize = (label_w, label_h)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pagesize)
    h = label_h

    # Контент на всю страницу этикетки
    margin = 2 * mm
    x0 = margin
    y0 = h - margin

    # Штрихкод товара (уменьшенный barWidth для этикетки)
    bc_product = _create_barcode_drawing(product_code, bar_width=0.2)
    bw1, bh1 = bc_product.width, bc_product.height
    scale1 = min((label_w - 4 * mm) / bw1, 12 * mm / bh1, 1.5)
    c.saveState()
    c.translate(x0 + (label_w - bw1 * scale1) / 2, y0 - bh1 * scale1 - 2 * mm)
    c.scale(scale1, scale1)
    renderPDF.draw(bc_product, c, 0, 0)
    c.restoreState()

    # Код OZN под штрихкодом (как у Ozon: OZN1994424509)
    ty = y0 - bh1 * scale1 - 4 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x0 + label_w / 2, ty, str(product_code)[:20])
    ty -= 3.5 * mm

    # Название товара
    if product_name:
        text_lines = _wrap_text(product_name, max_chars=24)
        c.setFont("Helvetica", 8)
        for line in reversed(text_lines):
            c.drawCentredString(x0 + label_w / 2, ty, line[:40])
            ty -= 3.5 * mm

    # Штрихкод ФБС (внизу этикетки, с отступом для подписи)
    bc_fbs = _create_barcode_drawing(fbs_code, bar_width=0.2)
    bw2, bh2 = bc_fbs.width, bc_fbs.height
    scale2 = min((label_w - 4 * mm) / bw2, 10 * mm / bh2, 1.5)
    fbs_y = 4 * mm  # отступ снизу для подписи «ШК ФБС»
    c.saveState()
    c.translate(x0 + (label_w - bw2 * scale2) / 2, fbs_y)
    c.scale(scale2, scale2)
    renderPDF.draw(bc_fbs, c, 0, 0)
    c.restoreState()
    c.drawCentredString(x0 + label_w / 2, fbs_y - 2 * mm, "ШК ФБС")

    c.save()
    buf.seek(0)
    return buf.getvalue()


def _wb_sticker_to_pdf(
    image_bytes: bytes,
    label_width_mm: int = 58,
    label_height_mm: int = 40,
    order_number: str | None = None,
) -> bytes:
    """Конвертировать PNG-стикер WB в PDF для печати (размер этикетки 58×40 мм)."""
    import io

    from PIL import Image
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("Invalid image dimensions")
    label_w = label_width_mm * mm
    label_h = label_height_mm * mm
    scale = min(label_w / iw, label_h / ih, 1.0)
    draw_w = iw * scale
    draw_h = ih * scale
    x0 = (label_w - draw_w) / 2
    y0 = (label_h - draw_h) / 2
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))
    c.drawImage(
        ImageReader(io.BytesIO(image_bytes)),
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
    if mp.type != MarketplaceType.OZON:
        raise HTTPException(400, detail="Barcodes PDF only for Ozon")
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

    # По одному штрихкоду на каждую единицу товара (для двойных заказов Ozon)
    items: list[tuple[str, str]] = []
    for p in products:
        sku = p.get("sku")
        qty = max(1, int(p.get("quantity", 1)))
        ozn_code = f"OZN{sku}" if sku is not None else (upper if upper else None)
        if not ozn_code:
            continue
        # Штрихкод: OZN+SKU (Code128) для каждого товара
        barcode_value = ozn_code
        for _ in range(qty):
            items.append((barcode_value, ozn_code))

    if not items:
        raise HTTPException(404, detail="Product barcode not found")

    # Ширина этикетки: из query или из настроек пользователя
    if label_width is None:
        ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
        label_width = (ps.ozon_width_mm or 58) if ps else 58
    pdf_bytes = _generate_multi_product_barcode_pdf(items, label_width_mm=label_width)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=barcodes-{order_id}.pdf"},
    )


@router.get("/{order_id}/label")
async def get_order_label(
    order_id: int,
    format: str = Query("pdf", description="Ozon: pdf. WB: svg, png, zplv, zplh"),
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
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=label-{order.posting_number}.pdf"},
        )
    elif mp.type == MarketplaceType.WILDBERRIES:
        # WB API возвращает SVG/PNG. Запрашиваем PNG и конвертируем в PDF для качественной печати.
        sticker_type = "png"
        if width is None or height is None:
            ps = db.query(PrintSettings).filter(PrintSettings.user_id == current_user.id).first()
            w = width if width is not None else (ps.wb_width_mm if ps else 58) or 58
            h = height if height is not None else (ps.wb_height_mm if ps else 40) or 40
        else:
            w, h = width, height
        async with WildberriesClient(api_key=api_key) as client:
            content = await client.get_order_label(
                order.external_id,
                sticker_type=sticker_type,
                width=w,
                height=h,
            )
        order_num = order.posting_number or order.external_id or ""
        content = _wb_sticker_to_pdf(content, label_width_mm=w, label_height_mm=h, order_number=order_num)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=label-{order.posting_number}.pdf"},
        )
    raise HTTPException(400, detail="Unknown marketplace type")
