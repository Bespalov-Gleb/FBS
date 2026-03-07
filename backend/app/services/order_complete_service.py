"""
Сервис отметки заказа «Собрано» с вызовом API маркетплейсов
"""
from sqlalchemy.orm import Session

from app.core.security import decrypt_api_key
from app.models.marketplace import MarketplaceType
from app.models.order import Order
from app.models.scanned_kiz import ScannedKiz
from app.services.marketplace.wildberries import WildberriesClient

KIZ_MAX_LENGTH = 31  # WB и Ozon принимают только первые 31 символ


def _add_to_scanned_kiz(db: Session, user_id: int, kiz_code: str, order: Order) -> None:
    """Добавить КИЗ в таблицу отсканированных (для выгрузки в WB/Ozon)."""
    if not kiz_code or not kiz_code.strip():
        return
    sk = ScannedKiz(
        user_id=user_id,
        kiz_code=kiz_code[:KIZ_MAX_LENGTH],
        external_id=order.external_id,
        posting_number=order.posting_number,
        marketplace_id=order.marketplace_id,
    )
    db.add(sk)


class OrderCompleteService:
    """Отметка заказа как собранного с синхронизацией в API (WB) или только локально (Ozon)"""

    @staticmethod
    async def complete_order(
        order: Order,
        user_id: int,
        kiz_code: str | None,
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД.
        
        Ozon: только локально — сохраняем статус и КИЗ. На Ozon нет кнопки «Собрано»,
        заказ пропадает только после приёмки на складе Ozon. Номер заказа уникален,
        запоминаем что собран — скрываем из списка.
        
        WB: create supply -> add order -> deliver supply (вызов API).
        """
        kiz_trimmed = (kiz_code.strip()[:KIZ_MAX_LENGTH] if kiz_code and kiz_code.strip() else None) or None

        mp = order.marketplace
        if not mp:
            if kiz_trimmed:
                _add_to_scanned_kiz(db, user_id, kiz_trimmed, order)
            order.complete(user_id=user_id, kiz_code=kiz_trimmed)
            db.commit()
            return True

        if mp.type == MarketplaceType.OZON:
            # Ozon: только локально — без вызова ship API
            if kiz_trimmed:
                _add_to_scanned_kiz(db, user_id, kiz_trimmed, order)
            order.complete(user_id=user_id, kiz_code=kiz_trimmed)
            db.commit()
            return True

        if mp.type == MarketplaceType.WILDBERRIES:
            api_key = decrypt_api_key(mp.api_key)
            async with WildberriesClient(api_key=api_key) as client:
                order_id_wb = int(order.external_id)
                if kiz_trimmed:
                    await client.add_kiz_code(str(order.external_id), kiz_trimmed)
                supply_id = await client.create_supply(
                    name=f"FBS-{order.posting_number}",
                )
                await client.add_orders_to_supply(supply_id, [order_id_wb])
                await client.deliver_supply(supply_id)
            if kiz_trimmed:
                _add_to_scanned_kiz(db, user_id, kiz_trimmed, order)
            order.complete(user_id=user_id, kiz_code=kiz_trimmed)
            db.commit()
            return True

        return False
