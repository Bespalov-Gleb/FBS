"""
Сервис отметки заказа «Собрано».

WB: при включённом КИЗ сначала отправка КИЗ в Wildberries API (meta/sgtin), затем БД.
Ozon: только локально (как раньше).
"""
from sqlalchemy.orm import Session

from app.core.exceptions import MarketplaceAPIException
from app.core.security import decrypt_api_key
from app.models.marketplace import MarketplaceType
from app.models.order import Order
from app.models.scanned_kiz import ScannedKiz
from app.services.marketplace.wildberries import WildberriesClient

# Полный КИЗ (Честный ЗНАК / GS1) для API WB и хранения в БД; на этикетке текстом часто показывают 31 символ.
KIZ_STORAGE_MAX = 255


def _normalize_kiz(raw: str) -> str:
    """Нормализация скана КИЗ: убрать AIM-префиксы/мусор в начале, оставить полезные данные."""
    s = (raw or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()
    # AIM-префиксы сканеров DataMatrix (не часть КИЗ)
    if s.startswith("]C1") or s.startswith("]c1") or s.startswith("]D2") or s.startswith("]d2") or s.startswith("]Q3") or s.startswith("]q3"):
        s = s[3:]
    # Служебные символы в начале (кроме GS=0x1D)
    while s and (ord(s[0]) < 32) and (s[0] != "\x1d"):
        s = s[1:]
    return s


def _kiz_31_for_wb(raw: str) -> str:
    """
    Укороченный КИЗ (31) для WB meta/sgtin:
    - GS (0x1D) или '>' считаем разделителем между базовой частью и хвостом 91/92
    - берём часть до разделителя, максимум 31 символ.
    """
    s = _normalize_kiz(raw).replace("\x1d", ">")
    if ">" in s:
        s = s.split(">", 1)[0]
    return s[:31].strip()


def _add_to_scanned_kiz(db: Session, user_id: int, kiz_code: str, order: Order) -> None:
    """Добавить КИЗ в таблицу отсканированных (для выгрузки в WB/Ozon)."""
    if not kiz_code or not kiz_code.strip():
        return
    sk = ScannedKiz(
        user_id=user_id,
        kiz_code=kiz_code[:KIZ_STORAGE_MAX],
        external_id=order.external_id,
        posting_number=order.posting_number,
        marketplace_id=order.marketplace_id,
    )
    db.add(sk)


class OrderCompleteService:
    """Отметка заказа как собранного; для WB с КИЗ — вызов API перед коммитом."""

    @staticmethod
    async def complete_order(
        order: Order,
        user_id: int,
        kiz_codes: list[str],
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД.

        Wildberries: если включён КИЗ и передан код — PUT .../orders/{id}/meta/sgtin;
        при ошибке API исключение, коммита нет.
        Ozon: только локально.
        """
        kiz_list = [_normalize_kiz(k)[:KIZ_STORAGE_MAX] for k in kiz_codes if k and _normalize_kiz(k)]
        first_kiz = kiz_list[0] if kiz_list else None

        mp = order.marketplace
        if not mp:
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        if mp.type == MarketplaceType.OZON:
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        if mp.type == MarketplaceType.WILDBERRIES:
            if mp.is_kiz_enabled and first_kiz:
                wb_kiz = _kiz_31_for_wb(first_kiz)
                if not wb_kiz:
                    raise MarketplaceAPIException(
                        message="WB: пустой КИЗ после нормализации",
                        marketplace="Wildberries",
                        detail="Не удалось выделить корректный КИЗ (31 символ) из скана.",
                        status_code=400,
                    )
                ed = order.extra_data or {}
                supplier = (ed.get("supplierStatus") or ed.get("supplier_status") or "").strip().lower()
                if supplier != "confirm":
                    raise MarketplaceAPIException(
                        message="WB: КИЗ можно передать только после добавления задания в поставку",
                        marketplace="Wildberries",
                        detail=(
                            f"По данным синхронизации статус задания: «{supplier or 'неизвестен'}», "
                            "нужен «confirm» (в поставке). Добавьте задание в поставку в кабинете WB и обновите заказы."
                        ),
                        status_code=400,
                    )
                api_key = decrypt_api_key(mp.api_key)
                async with WildberriesClient(api_key=api_key) as client:
                    await client.add_kiz_code(str(order.external_id), wb_kiz)
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        return False
