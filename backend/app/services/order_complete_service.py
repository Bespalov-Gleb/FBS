"""
Сервис отметки заказа «Собрано» с вызовом API маркетплейсов
"""
from sqlalchemy.orm import Session

from app.core.security import decrypt_api_key
from app.models.marketplace import MarketplaceType
from app.models.order import Order, OrderStatus
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient
from app.utils.logger import logger

KIZ_MAX_LENGTH = 31  # WB и Ozon принимают только первые 31 символ


class OrderCompleteService:
    """Отметка заказа как собранного с синхронизацией в API"""

    @staticmethod
    async def complete_order(
        order: Order,
        user_id: int,
        kiz_code: str | None,
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД и вызвать API маркетплейса.
        
        Ozon: ship_posting(posting_number)
        WB: create supply (if needed) -> add order -> deliver supply
        """
        kiz_trimmed = (kiz_code.strip()[:KIZ_MAX_LENGTH] if kiz_code and kiz_code.strip() else None) or None
        order.complete(user_id=user_id, kiz_code=kiz_trimmed)
        db.commit()

        mp = order.marketplace
        if not mp:
            return True
        api_key = decrypt_api_key(mp.api_key)

        if mp.type == MarketplaceType.OZON:
            if not mp.client_id:
                logger.error("Ozon marketplace without client_id")
                return False
            async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
                await client.ship_posting(order.posting_number)
            return True

        elif mp.type == MarketplaceType.WILDBERRIES:
            async with WildberriesClient(api_key=api_key) as client:
                order_id_wb = int(order.external_id)
                if kiz_trimmed:
                    await client.add_kiz_code(str(order.external_id), kiz_trimmed)
                supply_id = await client.create_supply(
                    name=f"FBS-{order.posting_number}",
                )
                await client.add_orders_to_supply(supply_id, [order_id_wb])
                await client.deliver_supply(supply_id)
            return True

        return False
