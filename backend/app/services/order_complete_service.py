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


def _wb_meta_lists_contain_sgtin(extra: dict) -> bool:
    """WB в API отдаёт requiredMeta/optionalMeta; в БД часто required_meta/optional_meta."""
    req = extra.get("required_meta") or extra.get("requiredMeta") or []
    opt = extra.get("optional_meta") or extra.get("optionalMeta") or []

    def mentions_sgtin(meta_list) -> bool:
        if not meta_list:
            return False
        for x in meta_list:
            if isinstance(x, str) and x.strip().lower() == "sgtin":
                return True
            if isinstance(x, dict):
                key = (
                    x.get("type")
                    or x.get("name")
                    or x.get("meta")
                    or x.get("key")
                    or ""
                )
                if str(key).strip().lower() == "sgtin":
                    return True
        return False

    return mentions_sgtin(req) or mentions_sgtin(opt)


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
        kiz_list = [k.strip()[:KIZ_STORAGE_MAX] for k in kiz_codes if k and k.strip()]
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
                ed = order.extra_data or {}
                if not _wb_meta_lists_contain_sgtin(ed):
                    raise MarketplaceAPIException(
                        message="WB: для задания не запрошена маркировка КИЗ (sgtin)",
                        marketplace="Wildberries",
                        detail=(
                            "В данных заказа нет sgtin в requiredMeta/optionalMeta. "
                            "Нажмите «Синхронизировать» на странице Сборки или проверьте карточку товара в WB."
                        ),
                        status_code=400,
                    )
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
                    await client.add_kiz_code(str(order.external_id), first_kiz)
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        return False
