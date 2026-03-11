"""
Сервис отметки заказа «Собрано» — только локальное изменение статуса
"""
from sqlalchemy.orm import Session

from app.models.marketplace import MarketplaceType
from app.models.order import Order
from app.models.scanned_kiz import ScannedKiz

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
    """Отметка заказа как собранного — только локально, без вызова API маркетплейсов"""

    @staticmethod
    async def complete_order(
        order: Order,
        user_id: int,
        kiz_codes: list[str],
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД.

        Ozon и WB: только локально — сохраняем статус и КИЗ (по одному на каждый товар).
        """
        kiz_list = [k.strip()[:KIZ_MAX_LENGTH] for k in kiz_codes if k and k.strip()]
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
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        return False
