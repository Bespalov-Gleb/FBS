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
from app.core.dependencies import CurrentAdminUser, CurrentUser
from app.models.marketplace import Marketplace
from app.models.order import Order, OrderStatus
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


@router.get("/kiz-label")
def get_kiz_label(
    kiz_code: str = Query(..., min_length=1, description="Код КИЗ (маркировка)"),
    current_user: User = CurrentUser,
):
    """
    Этикетка-дубль КИЗ для печати после сканирования.
    Возвращает SVG с QR-кодом кода маркировки.
    """
    import io
    import qrcode
    kiz = kiz_code.strip()[:31]  # WB/Ozon принимают только 31 символ
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(kiz)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=kiz-{kiz[:20]}.png"},
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
    ok = await OrderCompleteService.complete_order(
        order, current_user.id, kiz, db,
    )
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
    from reportlab.graphics.barcode import code128, eanbc
    from reportlab.graphics.shapes import Drawing

    code = str(code).strip()
    try:
        if len(code) == 13 and code.isdigit():
            bc = eanbc.Ean13BarcodeWidget(code[:12], barWidth=bar_width)
        else:
            bc = code128.Code128(code, barWidth=bar_width)
    except TypeError:
        # barWidth не поддерживается в некоторых версиях
        if len(code) == 13 and code.isdigit():
            bc = eanbc.Ean13BarcodeWidget(code[:12])
        else:
            bc = code128.Code128(code)
    d = Drawing(bc.width, bc.height)
    d.add(bc)
    return d


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

    # Текст под штрихкодом товара
    if product_name:
        text_lines = _wrap_text(product_name, max_chars=24)
        c.setFont("Helvetica", 8)
        ty = y0 - bh1 * scale1 - 5 * mm
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
    label_width: int = Query(58, description="Ширина этикетки в мм (58 или 80)"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """
    PDF с обоими штрихкодами (товар + ШК ФБС) для качественной печати.
    Векторный формат — чёткая печать без пикселизации.
    Только Ozon.
    """
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
    async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
        details = await client.get_posting_details(order.posting_number, with_barcodes=True)

    barcodes = details.get("barcodes") or {}
    if not isinstance(barcodes, dict):
        raise HTTPException(404, detail="Barcodes not found")
    upper = (barcodes.get("upper_barcode") or "").strip()
    lower = (barcodes.get("lower_barcode") or "").strip()
    products = details.get("products") or []
    sku = products[0].get("sku") if products else None

    if sku is not None:
        product_code = f"OZN{sku}"
    elif upper:
        product_code = upper
    else:
        raise HTTPException(404, detail="Product barcode not found")
    if not lower:
        raise HTTPException(404, detail="FBS barcode (lower_barcode) not found")

    product_name = (order.product_name or "").strip()
    if not product_name and products:
        product_name = (products[0].get("name") or "").strip()

    try:
        w = 80 if label_width >= 80 else 58
        pdf_bytes = _generate_barcodes_pdf(product_code, lower, product_name, label_width_mm=w)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=barcodes-{order_id}.pdf"},
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to generate barcodes PDF: {e}") from e


@router.get("/{order_id}/label")
async def get_order_label(
    order_id: int,
    format: str = Query("pdf", description="Ozon: pdf. WB: svg, png, zplv, zplh"),
    width: int = Query(58, description="WB: ширина этикетки 58 или 80 мм"),
    height: int = Query(40, description="WB: высота этикетки 40 или 30 мм"),
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
        try:
            async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
                content = await client.get_order_label(order.posting_number)
        except Exception as e:
            err_str = str(e).lower()
            detail = getattr(e, "detail", None)
            detail_str = str(detail).lower() if detail else ""
            # Ozon: "label not allowed for delivered postings" или "доставлен" / "отгружен"
            is_delivered_error = (
                "delivered" in err_str or "delivered" in detail_str
                or "label not allowed" in detail_str
                or "not allowed for" in detail_str
                or "доставлен" in detail_str
                or "отгружен" in detail_str
            )
            if is_delivered_error:
                if order.status != OrderStatus.COMPLETED:
                    order.complete(user_id=current_user.id, kiz_code=order.kiz_code)
                    db.commit()
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
        sticker_type = "png" if format == "png" else "svg"
        # WB API: width 58 или 40, height 40 или 30
        w, h = (58, 40) if width >= 80 else (58, 40)
        async with WildberriesClient(api_key=api_key) as client:
            content = await client.get_order_label(
                order.external_id,
                sticker_type=sticker_type,
                width=w,
                height=h,
            )
        media_type = "image/png" if sticker_type == "png" else "image/svg+xml"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"inline; filename=label-{order.posting_number}.{sticker_type}"},
        )
    raise HTTPException(400, detail="Unknown marketplace type")
