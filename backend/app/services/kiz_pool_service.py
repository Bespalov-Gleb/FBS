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
# Для ваших этикеток: строка под кодом, начинается с 01 + 14 цифр и содержит хвост
# (в хвосте могут быть символы типа & или )).
_TAIL_KIZ_RE = re.compile(r"^01\d{14}[^\s]{6,220}$")


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


def _normalize_size_for_match(size: str | None) -> str:
    return _normalize_size(size).lower()


def _split_article_and_size(article: str | None) -> tuple[str, str]:
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


def _extract_article_contains_rules(parser_markers: dict | None) -> dict[str, str]:
    if not isinstance(parser_markers, dict):
        return {}
    raw_rules = parser_markers.get("article_contains")
    if not isinstance(raw_rules, dict):
        return {}

    cleaned: dict[str, str] = {}
    for key, value in raw_rules.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            cleaned[k] = v
    return cleaned


def _ensure_article_matches_group_rules(article_raw: str, parser_markers: dict | None) -> None:
    """
    Группа может задавать произвольные правила article_contains:
    {
      "article_contains": {
        "material": "xlop",
        "fit": "unisex"
      }
    }
    Тогда КИЗ из группы используется только если артикул содержит все подстроки.
    """
    rules = _extract_article_contains_rules(parser_markers)
    if not rules:
        return

    article_lc = (article_raw or "").lower()
    failed: list[str] = []
    for param, marker in rules.items():
        if marker.lower() not in article_lc:
            failed.append(f"{param}={marker}")

    if failed:
        raise ValueError(
            "Артикул не подходит под параметры группы: "
            + ", ".join(failed)
        )


def _normalize_kiz(raw: str) -> str:
    s = (raw or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()
    if s.startswith(("]C1", "]c1", "]D2", "]d2", "]Q3", "]q3")):
        s = s[3:]
    while s and (ord(s[0]) < 32) and (s[0] != "\x1d"):
        s = s[1:]
    return s[:255]


def _resolve_group_for_order(db: Session, order: Order) -> KizGroup:
    if not order.marketplace:
        raise ValueError("Для заказа не определен маркетплейс.")

    owner_user_id = order.marketplace.user_id
    article_raw = _normalize_value(order.article)
    if not article_raw:
        raise ValueError("В заказе отсутствует артикул для подбора КИЗ.")

    article, size_from_article = _split_article_and_size(article_raw)
    size_from_order = _normalize_size((order.extra_data or {}).get("size"))

    # В некоторых заказах размер приходит как "L / 48-52": нужен матч по подстроке.
    size_candidates: list[str] = []
    for raw_size in (size_from_order, size_from_article):
        normalized = _normalize_size_for_match(raw_size)
        if normalized and normalized not in size_candidates:
            size_candidates.append(normalized)
    candidates: list[tuple[str, str]] = []
    # 1) Совместимость со старыми маппингами: полный артикул как есть.
    candidates.append((article_raw, ""))
    # 2) Новый формат: базовый артикул + размер из хвоста.
    if article and size_from_article:
        candidates.append((article, size_from_article))
    if article and size_from_order:
        candidates.append((article, size_from_order))
    # 3) Фолбэк на базовый артикул без размера.
    if article:
        candidates.append((article, ""))

    mapping = None
    for candidate_article, candidate_size in candidates:
        rows = db.query(KizProductMapping).filter(
            KizProductMapping.user_id == owner_user_id,
            KizProductMapping.marketplace_id == order.marketplace_id,
            KizProductMapping.article == candidate_article,
        ).all()
        if not rows:
            continue

        candidate_size_norm = _normalize_size_for_match(candidate_size)

        def matches_size(row_size: str) -> bool:
            row_norm = _normalize_size_for_match(row_size)
            # Пустой размер в маппинге — универсальный фолбэк.
            if not row_norm:
                return True
            # Точное совпадение по "ожидаемому" candidate_size (для старой логики).
            if candidate_size_norm and row_norm == candidate_size_norm:
                return True
            # Гибкое совпадение по любому размеру из заказа: подстрока в обе стороны.
            for s in size_candidates:
                if row_norm in s or s in row_norm:
                    return True
            return False

        # Приоритет: более специфичные правила (непустой размер) выше универсального фолбэка.
        rows_sorted = sorted(rows, key=lambda r: (0 if _normalize_size_for_match(r.size) else 1, r.id))
        mapping = next((r for r in rows_sorted if matches_size(r.size)), None)
        if mapping:
            break
    if not mapping:
        raise ValueError(
            f"Для товара '{article_raw}' не настроена группа КИЗ. Обратитесь к администратору."
        )

    group = db.query(KizGroup).filter(
        KizGroup.id == mapping.group_id,
        KizGroup.user_id == owner_user_id,
        KizGroup.is_active == True,
    ).first()
    if not group:
        raise ValueError("Назначенная группа КИЗ не найдена или неактивна.")
    _ensure_article_matches_group_rules(article_raw, group.parser_markers)

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
    return group


def _extract_kiz_from_text(page_text: str | None) -> str | None:
    if not page_text:
        return None

    # 1) Сначала ищем "хвост" из подписи под кодом (самый стабильный для данного шаблона).
    # Проверяем по строкам и токенам.
    for line in page_text.splitlines():
        token = "".join(line.split())
        if _TAIL_KIZ_RE.match(token):
            return _normalize_kiz(token)

    compact = " ".join(page_text.split())

    # 2) Формат с AI в скобках.
    bracketed = _BRACKETED_KIZ_RE.search(compact)
    if bracketed:
        return _normalize_kiz(bracketed.group(0))

    # 3) Фолбэк: 31-символьный алфанумерический код (исторический формат части выгрузок).
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
    group = _resolve_group_for_order(db, order)

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


def suggest_kiz_codes_fifo_for_order(
    db: Session,
    *,
    order: Order,
    required_count: int,
) -> list[str]:
    group = _resolve_group_for_order(db, order)
    pool_items = (
        db.query(KizPoolItem)
        .filter(
            KizPoolItem.group_id == group.id,
            KizPoolItem.status == KizCodeStatus.FREE,
        )
        .order_by(KizPoolItem.id.asc())
        .limit(required_count)
        .all()
    )
    if len(pool_items) < required_count:
        available = len(pool_items)
        raise ValueError(
            f"В группе '{group.name}' недостаточно КИЗ. Нужно: {required_count}, доступно: {available}."
        )
    return [item.code for item in pool_items]


def mark_kiz_codes_used_for_order(
    db: Session,
    *,
    order: Order,
    kiz_codes: Iterable[str],
    completed_by_user_id: int,
) -> None:
    normalized = [_normalize_kiz(code) for code in kiz_codes if _normalize_kiz(code)]
    if not normalized:
        return

    now = datetime.utcnow()
    items = (
        db.query(KizPoolItem)
        .filter(KizPoolItem.code.in_(normalized))
        .with_for_update(skip_locked=True)
        .all()
    )
    by_code = {item.code: item for item in items}
    missing = [code for code in normalized if code not in by_code]
    if missing:
        raise ValueError("Часть КИЗ не найдена в пуле: " + ", ".join(missing[:3]))

    for code in normalized:
        item = by_code[code]
        if item.status == KizCodeStatus.USED and item.used_order_id != order.id:
            raise ValueError(f"КИЗ уже использован в другом заказе: {code}")
        if item.status == KizCodeStatus.FREE:
            item.status = KizCodeStatus.USED
            item.used_at = now
            item.used_order_id = order.id
            item.used_by_user_id = completed_by_user_id
