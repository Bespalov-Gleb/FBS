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
        kiz_code: str | None,
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД.

        Ozon и WB: только локально — сохраняем статус и КИЗ.
        На Ozon нет кнопки «Собрано», заказ пропадает после приёмки на складе.
        На WB статус меняется только внутри приложения, supply API не вызывается.
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
            # WB: только локально — без вызова supply API.
            # Статус меняется только внутри приложения, WB не уведомляется.
            if kiz_trimmed:
                _add_to_scanned_kiz(db, user_id, kiz_trimmed, order)
            order.complete(user_id=user_id, kiz_code=kiz_trimmed)
            db.commit()
            return True

        return False
