from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pdf2image import convert_from_bytes
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

from app.models.kiz_group import KizGroup, kiz_group_marketplaces
from app.models.kiz_parser_error import KizParserError
from app.models.kiz_pool_item import KizCodeStatus, KizPoolItem
from app.models.kiz_product_mapping import KizProductMapping
from app.models.order import Order

_BRACKETED_KIZ_RE = re.compile(
    r"\(01\)\d{14}\(21\)[A-Za-z0-9]{1,40}(?:\(91\)[A-Za-z0-9]{1,20})?(?:\(92\)[A-Za-z0-9]{1,120})?"
)
_ALNUM_31_RE = re.compile(r"\b[A-Za-z0-9]{31}\b")


@dataclass(slots=True)
class UploadParseStats:
    total_pages: int = 0
    imported: int = 0
    duplicates: int = 0
    errors: int = 0


def _normalize_value(value: str | None) -> str:
    return (value or "").strip()


def _normalize_size(size: str | None) -> str:
    return (size or "").strip()


def _normalize_kiz(raw: str) -> str:
    s = (raw or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()
    if s.startswith(("]C1", "]c1", "]D2", "]d2", "]Q3", "]q3")):
        s = s[3:]
    while s and (ord(s[0]) < 32) and (s[0] != "\x1d"):
        s = s[1:]
    return s[:255]


def _extract_kiz_from_text(page_text: str | None) -> str | None:
    if not page_text:
        return None
    compact = " ".join(page_text.split())
    bracketed = _BRACKETED_KIZ_RE.search(compact)
    if bracketed:
        return _normalize_kiz(bracketed.group(0))

    # В части цифровых PDF КИЗ печатается как 31-символьный алфанумерический код.
    short_code = _ALNUM_31_RE.search(compact)
    if short_code:
        return _normalize_kiz(short_code.group(0))
    return None


def _extract_kiz_from_datamatrix(page_pdf_bytes: bytes) -> str | None:
    try:
        from pylibdmtx.pylibdmtx import decode
    except Exception as exc:
        raise RuntimeError(
            "Не удалось загрузить декодер DataMatrix (pylibdmtx)."
        ) from exc

    images = convert_from_bytes(
        page_pdf_bytes,
        dpi=300,
        fmt="png",
        first_page=1,
        last_page=1,
        single_file=True,
    )
    if not images:
        return None

    decoded = decode(images[0], max_count=1)
    if not decoded:
        return None
    raw = decoded[0].data.decode("utf-8", errors="ignore")
    return _normalize_kiz(raw)


def _page_to_pdf_bytes(page) -> bytes:
    writer = PdfWriter()
    writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def import_kiz_codes_from_pdfs(
    db: Session,
    *,
    owner_user_id: int,
    group: KizGroup,
    uploaded_files: Iterable[tuple[str, bytes]],
) -> UploadParseStats:
    stats = UploadParseStats()

    for filename, file_bytes in uploaded_files:
        reader = PdfReader(io.BytesIO(file_bytes))
        for idx, page in enumerate(reader.pages, start=1):
            stats.total_pages += 1
            page_text = None
            try:
                page_text = page.extract_text()
            except Exception:
                page_text = None

            code = _extract_kiz_from_text(page_text)
            if not code:
                try:
                    code = _extract_kiz_from_datamatrix(_page_to_pdf_bytes(page))
                except Exception as exc:
                    db.add(
                        KizParserError(
                            user_id=owner_user_id,
                            group_id=group.id,
                            source_filename=filename,
                            source_page=idx,
                            error_message=f"Ошибка DataMatrix парсера: {exc}",
                        )
                    )
                    stats.errors += 1
                    continue

            if not code:
                db.add(
                    KizParserError(
                        user_id=owner_user_id,
                        group_id=group.id,
                        source_filename=filename,
                        source_page=idx,
                        error_message="КИЗ не найден на странице.",
                    )
                )
                stats.errors += 1
                continue

            exists = db.query(KizPoolItem.id).filter(KizPoolItem.code == code).first()
            if exists:
                stats.duplicates += 1
                continue

            db.add(
                KizPoolItem(
                    code=code,
                    group_id=group.id,
                    source_filename=filename,
                    source_page=idx,
                    status=KizCodeStatus.FREE,
                )
            )
            stats.imported += 1

    db.commit()
    return stats


def assign_kiz_codes_fifo_for_order(
    db: Session,
    *,
    order: Order,
    required_count: int,
    completed_by_user_id: int,
) -> list[str]:
    if not order.marketplace:
        raise ValueError("Для заказа не определен маркетплейс.")

    owner_user_id = order.marketplace.user_id
    article = _normalize_value(order.article)
    if not article:
        raise ValueError("В заказе отсутствует артикул для подбора КИЗ.")

    size = _normalize_size(order.size)

    mapping_q = db.query(KizProductMapping).filter(
        KizProductMapping.user_id == owner_user_id,
        KizProductMapping.marketplace_id == order.marketplace_id,
        KizProductMapping.article == article,
    )

    mapping = None
    if size:
        mapping = mapping_q.filter(KizProductMapping.size == size).first()
    if not mapping:
        mapping = mapping_q.filter(KizProductMapping.size == "").first()
    if not mapping:
        raise ValueError(
            f"Для товара '{article}' не настроена группа КИЗ. Обратитесь к администратору."
        )

    group = db.query(KizGroup).filter(
        KizGroup.id == mapping.group_id,
        KizGroup.user_id == owner_user_id,
        KizGroup.is_active == True,
    ).first()
    if not group:
        raise ValueError("Назначенная группа КИЗ не найдена или неактивна.")

    group_has_marketplace = (
        db.query(kiz_group_marketplaces)
        .filter(
            kiz_group_marketplaces.c.group_id == group.id,
            kiz_group_marketplaces.c.marketplace_id == order.marketplace_id,
        )
        .first()
        is not None
    )
    if not group_has_marketplace:
        raise ValueError("Группа КИЗ не привязана к магазину текущего заказа.")

    pool_items = (
        db.query(KizPoolItem)
        .filter(
            KizPoolItem.group_id == group.id,
            KizPoolItem.status == KizCodeStatus.FREE,
        )
        .order_by(KizPoolItem.id.asc())
        .with_for_update(skip_locked=True)
        .limit(required_count)
        .all()
    )
    if len(pool_items) < required_count:
        available = len(pool_items)
        raise ValueError(
            f"В группе '{group.name}' недостаточно КИЗ. Нужно: {required_count}, доступно: {available}."
        )

    now = datetime.utcnow()
    result: list[str] = []
    for item in pool_items:
        item.status = KizCodeStatus.USED
        item.used_at = now
        item.used_order_id = order.id
        item.used_by_user_id = completed_by_user_id
        result.append(item.code)
    return result
