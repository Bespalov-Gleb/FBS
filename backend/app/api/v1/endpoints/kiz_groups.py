from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentAdminUser
from app.models.kiz_group import KizGroup, kiz_group_marketplaces
from app.models.kiz_parser_error import KizParserError
from app.models.kiz_pool_item import KizCodeStatus, KizPoolItem
from app.models.kiz_product_mapping import KizProductMapping
from app.models.marketplace import Marketplace
from app.models.order import Order
from app.models.user import User
from app.services.kiz_pool_service import import_kiz_codes_from_pdfs

router = APIRouter(prefix="/kiz-groups", tags=["KIZ Groups"])


class KizGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = Field(default=None, max_length=120)
    size: Optional[str] = Field(default=None, max_length=120)
    cut_type: Optional[str] = Field(default=None, max_length=120)
    parser_markers: Optional[dict[str, Any]] = None
    marketplace_ids: list[int] = Field(default_factory=list)


class KizGroupResponse(BaseModel):
    id: int
    name: str
    color: Optional[str]
    size: Optional[str]
    cut_type: Optional[str]
    parser_markers: Optional[dict[str, Any]]
    marketplace_ids: list[int]
    free_count: int
    used_count: int
    parser_errors_count: int


class ProductGroupMappingUpsert(BaseModel):
    marketplace_id: int
    article: str
    size: Optional[str] = ""
    group_id: int


def _split_article_and_size(article: str | None) -> tuple[str, str]:
    """
    Размер извлекаем из артикула по последнему '_' (например ABC123_XL).
    Если шаблон не распознан, считаем, что размера нет.
    """
    raw = (article or "").strip()
    if not raw:
        return "", ""
    if "_" not in raw:
        return raw, ""
    base, size = raw.rsplit("_", 1)
    base = base.strip()
    size = size.strip()
    if not base or not size:
        return raw, ""
    return base, size

def _group_to_response(
    group: KizGroup,
    *,
    free_count: int,
    used_count: int,
    parser_errors_count: int,
) -> KizGroupResponse:
    return KizGroupResponse(
        id=group.id,
        name=group.name,
        color=group.color,
        size=group.size,
        cut_type=group.cut_type,
        parser_markers=group.parser_markers,
        marketplace_ids=[m.id for m in group.marketplaces],
        free_count=free_count,
        used_count=used_count,
        parser_errors_count=parser_errors_count,
    )


@router.get("", response_model=list[KizGroupResponse])
def list_kiz_groups(
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    groups = (
        db.query(KizGroup)
        .filter(KizGroup.user_id == current_user.id)
        .order_by(KizGroup.created_at.desc())
        .all()
    )
    if not groups:
        return []

    group_ids = [g.id for g in groups]
    pool_counts = (
        db.query(KizPoolItem.group_id, KizPoolItem.status, func.count(KizPoolItem.id))
        .filter(KizPoolItem.group_id.in_(group_ids))
        .group_by(KizPoolItem.group_id, KizPoolItem.status)
        .all()
    )
    errors_counts = (
        db.query(KizParserError.group_id, func.count(KizParserError.id))
        .filter(KizParserError.group_id.in_(group_ids))
        .group_by(KizParserError.group_id)
        .all()
    )

    free_by_group: dict[int, int] = defaultdict(int)
    used_by_group: dict[int, int] = defaultdict(int)
    err_by_group: dict[int, int] = defaultdict(int)

    for gid, status_val, cnt in pool_counts:
        normalized_status = status_val.value if hasattr(status_val, "value") else str(status_val)
        if normalized_status == KizCodeStatus.FREE.value:
            free_by_group[gid] = int(cnt)
        elif normalized_status == KizCodeStatus.USED.value:
            used_by_group[gid] = int(cnt)
    for gid, cnt in errors_counts:
        err_by_group[gid] = int(cnt)

    return [
        _group_to_response(
            g,
            free_count=free_by_group[g.id],
            used_count=used_by_group[g.id],
            parser_errors_count=err_by_group[g.id],
        )
        for g in groups
    ]


@router.post("", response_model=KizGroupResponse)
def create_kiz_group(
    payload: KizGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название группы обязательно.")

    exists = (
        db.query(KizGroup.id)
        .filter(KizGroup.user_id == current_user.id, KizGroup.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже существует.")

    marketplaces = []
    if payload.marketplace_ids:
        marketplaces = (
            db.query(Marketplace)
            .filter(
                Marketplace.user_id == current_user.id,
                Marketplace.id.in_(payload.marketplace_ids),
            )
            .all()
        )
        if len(marketplaces) != len(set(payload.marketplace_ids)):
            raise HTTPException(status_code=400, detail="Часть магазинов не найдена.")

    group = KizGroup(
        user_id=current_user.id,
        name=name,
        color=(payload.color or "").strip() or None,
        size=(payload.size or "").strip() or None,
        cut_type=(payload.cut_type or "").strip() or None,
        parser_markers=payload.parser_markers,
        is_active=True,
    )
    group.marketplaces = marketplaces
    db.add(group)
    db.commit()
    db.refresh(group)
    return _group_to_response(group, free_count=0, used_count=0, parser_errors_count=0)


@router.patch("/{group_id}", response_model=KizGroupResponse)
def update_kiz_group(
    group_id: int,
    payload: KizGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    group = (
        db.query(KizGroup)
        .filter(KizGroup.id == group_id, KizGroup.user_id == current_user.id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена.")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название группы обязательно.")

    dup = (
        db.query(KizGroup.id)
        .filter(
            KizGroup.user_id == current_user.id,
            KizGroup.name == name,
            KizGroup.id != group_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже существует.")

    marketplaces = (
        db.query(Marketplace)
        .filter(
            Marketplace.user_id == current_user.id,
            Marketplace.id.in_(payload.marketplace_ids or []),
        )
        .all()
    )
    if len(marketplaces) != len(set(payload.marketplace_ids or [])):
        raise HTTPException(status_code=400, detail="Часть магазинов не найдена.")

    group.name = name
    group.color = (payload.color or "").strip() or None
    group.size = (payload.size or "").strip() or None
    group.cut_type = (payload.cut_type or "").strip() or None
    group.parser_markers = payload.parser_markers
    group.marketplaces = marketplaces
    db.commit()
    db.refresh(group)

    free_count = (
        db.query(func.count(KizPoolItem.id))
        .filter(KizPoolItem.group_id == group.id, KizPoolItem.status == KizCodeStatus.FREE)
        .scalar()
        or 0
    )
    used_count = (
        db.query(func.count(KizPoolItem.id))
        .filter(KizPoolItem.group_id == group.id, KizPoolItem.status == KizCodeStatus.USED)
        .scalar()
        or 0
    )
    parser_errors_count = (
        db.query(func.count(KizParserError.id))
        .filter(KizParserError.group_id == group.id)
        .scalar()
        or 0
    )

    return _group_to_response(
        group,
        free_count=int(free_count),
        used_count=int(used_count),
        parser_errors_count=int(parser_errors_count),
    )


@router.post("/{group_id}/upload-pdf")
async def upload_kiz_pdfs(
    group_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    group = (
        db.query(KizGroup)
        .filter(KizGroup.id == group_id, KizGroup.user_id == current_user.id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена.")
    if not files:
        raise HTTPException(status_code=400, detail="Не выбраны PDF файлы.")

    loaded_files: list[tuple[str, bytes]] = []
    for uploaded in files:
        filename = uploaded.filename or "file.pdf"
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(
                status_code=400,
                detail=f"Файл {filename}: поддерживаются только PDF.",
            )
        loaded_files.append((filename, await uploaded.read()))

    try:
        stats = import_kiz_codes_from_pdfs(
            db,
            owner_user_id=current_user.id,
            group=group,
            uploaded_files=loaded_files,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка импорта PDF: {exc}") from exc

    return {
        "ok": True,
        "total_pages": stats.total_pages,
        "imported": stats.imported,
        "duplicates": stats.duplicates,
        "errors": stats.errors,
    }


@router.post("/product-mappings")
def upsert_product_mapping(
    payload: ProductGroupMappingUpsert,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    article = (payload.article or "").strip()
    if not article:
        raise HTTPException(status_code=400, detail="article обязателен.")

    size = (payload.size or "").strip()

    group = (
        db.query(KizGroup)
        .filter(KizGroup.id == payload.group_id, KizGroup.user_id == current_user.id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена.")

    marketplace = (
        db.query(Marketplace)
        .filter(
            Marketplace.id == payload.marketplace_id,
            Marketplace.user_id == current_user.id,
        )
        .first()
    )
    if not marketplace:
        raise HTTPException(status_code=404, detail="Магазин не найден.")

    row = (
        db.query(KizProductMapping)
        .filter(
            KizProductMapping.user_id == current_user.id,
            KizProductMapping.marketplace_id == payload.marketplace_id,
            KizProductMapping.article == article,
            KizProductMapping.size == size,
        )
        .first()
    )
    if not row:
        row = KizProductMapping(
            user_id=current_user.id,
            marketplace_id=payload.marketplace_id,
            article=article,
            size=size,
            group_id=payload.group_id,
        )
        db.add(row)
    else:
        row.group_id = payload.group_id
    db.commit()
    return {"ok": True}


@router.get("/products/export")
def export_products_for_mapping(
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    products = (
        db.query(
            Order.marketplace_id,
            Marketplace.name.label("marketplace_name"),
            Order.article,
            func.max(Order.product_name).label("product_name"),
        )
        .join(Marketplace, Marketplace.id == Order.marketplace_id)
        .filter(Marketplace.user_id == current_user.id)
        .group_by(Order.marketplace_id, Marketplace.name, Order.article)
        .order_by(Marketplace.name.asc(), Order.article.asc())
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(
        [
            "marketplace_id",
            "marketplace_name",
            "article",
            "size",
            "product_name",
            "group_id",
            "group_name",
        ]
    )

    for row in products:
        article_base, size = _split_article_and_size(row.article)
        mapping = (
            db.query(KizProductMapping, KizGroup.name)
            .join(KizGroup, KizGroup.id == KizProductMapping.group_id)
            .filter(
                KizProductMapping.user_id == current_user.id,
                KizProductMapping.marketplace_id == row.marketplace_id,
                KizProductMapping.article == article_base,
                KizProductMapping.size == size,
            )
            .first()
        )
        group_id = mapping[0].group_id if mapping else ""
        group_name = mapping[1] if mapping else ""
        ws.append(
            [
                row.marketplace_id,
                row.marketplace_name,
                article_base,
                size,
                row.product_name or "",
                group_id,
                group_name,
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="kiz-product-mapping.xlsx"'},
    )


def _parse_mapping_rows(file_name: str, content: bytes) -> list[dict[str, str]]:
    ext = Path(file_name).suffix.lower()
    if ext == ".csv":
        raw = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    if ext == ".xlsx":
        wb = load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
        header = [str(c.value or "").strip() for c in ws[1]]
        rows: list[dict[str, str]] = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            item: dict[str, str] = {}
            for idx, key in enumerate(header):
                if not key:
                    continue
                item[key] = str(row[idx] if idx < len(row) and row[idx] is not None else "").strip()
            rows.append(item)
        wb.close()
        return rows
    raise ValueError("Поддерживаются только .xlsx или .csv.")


@router.post("/products/import")
async def import_product_mapping_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    file_name = file.filename or "mapping.xlsx"
    content = await file.read()

    try:
        rows = _parse_mapping_rows(file_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = 0
    created = 0
    skipped = 0

    groups_by_id = {
        g.id: g
        for g in db.query(KizGroup).filter(KizGroup.user_id == current_user.id).all()
    }
    groups_by_name = {g.name.strip().lower(): g for g in groups_by_id.values()}
    marketplaces = {
        m.id: m
        for m in db.query(Marketplace).filter(Marketplace.user_id == current_user.id).all()
    }

    for row in rows:
        article = (row.get("article") or "").strip()
        if not article:
            skipped += 1
            continue

        try:
            marketplace_id = int((row.get("marketplace_id") or "").strip())
        except Exception:
            skipped += 1
            continue
        if marketplace_id not in marketplaces:
            skipped += 1
            continue

        group = None
        group_id_raw = (row.get("group_id") or "").strip()
        if group_id_raw:
            try:
                group = groups_by_id.get(int(group_id_raw))
            except Exception:
                group = None
        if not group:
            group_name = (row.get("group_name") or "").strip().lower()
            group = groups_by_name.get(group_name)
        if not group:
            skipped += 1
            continue

        size = (row.get("size") or "").strip()
        existing = (
            db.query(KizProductMapping)
            .filter(
                KizProductMapping.user_id == current_user.id,
                KizProductMapping.marketplace_id == marketplace_id,
                KizProductMapping.article == article,
                KizProductMapping.size == size,
            )
            .first()
        )
        if existing:
            if existing.group_id != group.id:
                existing.group_id = group.id
                updated += 1
        else:
            db.add(
                KizProductMapping(
                    user_id=current_user.id,
                    marketplace_id=marketplace_id,
                    article=article,
                    size=size,
                    group_id=group.id,
                )
            )
            created += 1

    db.commit()
    return {"ok": True, "created": created, "updated": updated, "skipped": skipped}


@router.get("/reports")
def download_kiz_report(
    report_type: str = Query("free", description="free | used | errors"),
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    kind = (report_type or "").strip().lower()
    wb = Workbook()
    ws = wb.active

    if kind == "errors":
        ws.title = "errors"
        ws.append(["group_name", "source_filename", "source_page", "error_message", "created_at"])
        rows = (
            db.query(KizParserError, KizGroup.name)
            .join(KizGroup, KizGroup.id == KizParserError.group_id)
            .filter(KizParserError.user_id == current_user.id)
            .order_by(KizParserError.created_at.desc())
            .all()
        )
        for err, group_name in rows:
            ws.append(
                [
                    group_name,
                    err.source_filename or "",
                    err.source_page or "",
                    err.error_message,
                    err.created_at.isoformat(),
                ]
            )
        filename = "kiz-report-errors.xlsx"
    else:
        target_status = KizCodeStatus.FREE if kind == "free" else KizCodeStatus.USED
        ws.title = target_status.value
        ws.append(
            [
                "group_name",
                "code",
                "source_filename",
                "source_page",
                "used_order_id",
                "used_at",
            ]
        )
        rows = (
            db.query(KizPoolItem, KizGroup.name)
            .join(KizGroup, KizGroup.id == KizPoolItem.group_id)
            .filter(
                KizGroup.user_id == current_user.id,
                KizPoolItem.status == target_status,
            )
            .order_by(KizPoolItem.id.asc())
            .all()
        )
        for item, group_name in rows:
            ws.append(
                [
                    group_name,
                    item.code,
                    item.source_filename or "",
                    item.source_page or "",
                    item.used_order_id or "",
                    item.used_at.isoformat() if item.used_at else "",
                ]
            )
        filename = f"kiz-report-{target_status.value}.xlsx"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/products")
def list_products_for_mapping(
    search: str = Query("", description="Поиск по артикулу/названию"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    q = (
        db.query(
            Order.marketplace_id,
            Marketplace.name.label("marketplace_name"),
            Order.article,
            func.max(Order.product_name).label("product_name"),
        )
        .join(Marketplace, Marketplace.id == Order.marketplace_id)
        .filter(Marketplace.user_id == current_user.id)
        .group_by(Order.marketplace_id, Marketplace.name, Order.article)
        .order_by(Marketplace.name.asc(), Order.article.asc())
    )
    if search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(or_(Order.article.ilike(term), Order.product_name.ilike(term)))
    rows = q.limit(limit).all()

    out = []
    for row in rows:
        article_base, size = _split_article_and_size(row.article)
        mapping = (
            db.query(KizProductMapping, KizGroup.name)
            .join(KizGroup, KizGroup.id == KizProductMapping.group_id)
            .filter(
                KizProductMapping.user_id == current_user.id,
                KizProductMapping.marketplace_id == row.marketplace_id,
                KizProductMapping.article == article_base,
                KizProductMapping.size == size,
            )
            .first()
        )
        out.append(
            {
                "marketplace_id": row.marketplace_id,
                "marketplace_name": row.marketplace_name,
                "article": article_base,
                "size": size,
                "product_name": row.product_name or "",
                "group_id": mapping[0].group_id if mapping else None,
                "group_name": mapping[1] if mapping else None,
            }
        )
    return out
