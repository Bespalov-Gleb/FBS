"""
Репозиторий для работы с заказами
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.order import Order, OrderStatus


class OrderRepository:
    """CRUD операции для заказов"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, order_id: int) -> Optional[Order]:
        """Получить заказ по ID"""
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_by_external_id(
        self,
        marketplace_id: int,
        external_id: str,
    ) -> Optional[Order]:
        """Получить заказ по marketplace и external_id"""
        return (
            self.db.query(Order)
            .filter(
                Order.marketplace_id == marketplace_id,
                Order.external_id == str(external_id),
            )
            .first()
        )

    def get_by_posting_number(
        self,
        marketplace_id: int,
        posting_number: str,
    ) -> Optional[Order]:
        """Получить заказ по marketplace и posting_number (Ozon)"""
        if not posting_number:
            return None
        return (
            self.db.query(Order)
            .filter(
                Order.marketplace_id == marketplace_id,
                Order.posting_number == str(posting_number),
            )
            .first()
        )

    def create(
        self,
        marketplace_id: int,
        external_id: str,
        posting_number: str,
        article: str,
        product_name: str,
        quantity: int = 1,
        warehouse_id: Optional[int] = None,
        warehouse_name: Optional[str] = None,
        marketplace_status: Optional[str] = None,
        marketplace_created_at: Optional[datetime] = None,
        metadata: Optional[dict] = None,
        status: Optional[OrderStatus] = None,
    ) -> Order:
        """Создать заказ"""
        order_status = status if status is not None else OrderStatus.AWAITING_PACKAGING
        order = Order(
            marketplace_id=marketplace_id,
            external_id=str(external_id),
            posting_number=posting_number,
            article=article,
            product_name=product_name,
            quantity=quantity,
            warehouse_id=warehouse_id,
            warehouse_name=warehouse_name,
            marketplace_status=marketplace_status,
            marketplace_created_at=marketplace_created_at,
            status=order_status,
            extra_data=metadata,
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def get_list(
        self,
        user_id: int,
        *,
        skip: int = 0,
        limit: int = 100,
        marketplace_ids: Optional[List[int]] = None,
        marketplace_types: Optional[List[str]] = None,
        warehouse_ids: Optional[List[int]] = None,
        status: Optional[OrderStatus] = None,
        search: Optional[str] = None,
        sort_by: str = "marketplace_created_at",
        sort_desc: bool = True,
        packer_allowed_marketplace_ids: Optional[List[int]] = None,
    ) -> list[Order]:
        """Список заказов пользователя с фильтрами. Поиск: артикул, название, номер заказа.
        packer_allowed_marketplace_ids — если задан, ограничивает выдачу только этими магазинами."""
        from app.models.marketplace import Marketplace, MarketplaceType

        # Показывать только заказы в сборке. Скрыть: отмеченные у нас «Собрано», доставлен, отменён.
        # status=COMPLETED от Ozon («Собран» у них) — скрываем, показываем только наши (collected_in_app).
        query = (
            self.db.query(Order)
            .join(Marketplace)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.status != OrderStatus.CANCELLED)
            .filter(Order.status != OrderStatus.DELIVERED)
            .filter(Order.status != OrderStatus.COMPLETED)
            .filter(Order.collected_in_app != True)
        )
        # Ограничение доступа упаковщика к конкретным магазинам
        if packer_allowed_marketplace_ids is not None:
            query = query.filter(Order.marketplace_id.in_(packer_allowed_marketplace_ids))
        mp_conds = []
        if marketplace_ids:
            mp_conds.append(Order.marketplace_id.in_(marketplace_ids))
        if marketplace_types:
            valid_types = []
            for t in marketplace_types:
                if not t:
                    continue
                try:
                    valid_types.append(MarketplaceType(str(t).lower()))
                except ValueError:
                    pass
            if valid_types:
                mp_conds.append(Marketplace.type.in_(valid_types))
        if mp_conds:
            query = query.filter(or_(*mp_conds))
        if warehouse_ids:
            query = query.filter(Order.warehouse_id.in_(warehouse_ids))
        if status:
            query = query.filter(Order.status == status)
        search_pattern = None
        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Order.article.ilike(search_pattern),
                    Order.product_name.ilike(search_pattern),
                    Order.posting_number.ilike(search_pattern),
                    Order.external_id.ilike(search_pattern),
                )
            )
        order_col = getattr(Order, sort_by, Order.marketplace_created_at)
        if search_pattern:
            # Приоритет совпадений: 1 артикул, 2 название, 3 номер
            search_priority = case(
                (Order.article.ilike(search_pattern), 1),
                (Order.product_name.ilike(search_pattern), 2),
                (Order.posting_number.ilike(search_pattern), 3),
                (Order.external_id.ilike(search_pattern), 3),
                else_=4,
            ).label("search_priority")
            if sort_desc:
                query = query.order_by(search_priority.asc(), order_col.desc())
            else:
                query = query.order_by(search_priority.asc(), order_col.asc())
        elif sort_desc:
            query = query.order_by(order_col.desc())
        else:
            query = query.order_by(order_col.asc())
        # Eager load — избегаем N+1 при доступе к marketplace, warehouse, assigned_to_user
        query = query.options(
            joinedload(Order.marketplace),
            joinedload(Order.warehouse),
            joinedload(Order.assigned_to_user),
        )
        return query.offset(skip).limit(limit).all()

    def get_list_count(
        self,
        user_id: int,
        *,
        marketplace_ids: Optional[List[int]] = None,
        marketplace_types: Optional[List[str]] = None,
        warehouse_ids: Optional[List[int]] = None,
        status: Optional[OrderStatus] = None,
        search: Optional[str] = None,
        packer_allowed_marketplace_ids: Optional[List[int]] = None,
    ) -> int:
        """Количество заказов по тем же фильтрам, что и get_list"""
        from app.models.marketplace import Marketplace, MarketplaceType

        query = (
            self.db.query(func.count(Order.id))
            .join(Marketplace)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.status != OrderStatus.CANCELLED)
            .filter(Order.status != OrderStatus.DELIVERED)
            .filter(Order.status != OrderStatus.COMPLETED)
            .filter(Order.collected_in_app != True)
        )
        if packer_allowed_marketplace_ids is not None:
            query = query.filter(Order.marketplace_id.in_(packer_allowed_marketplace_ids))
        mp_conds = []
        if marketplace_ids:
            mp_conds.append(Order.marketplace_id.in_(marketplace_ids))
        if marketplace_types:
            valid_types = []
            for t in marketplace_types:
                if not t:
                    continue
                try:
                    valid_types.append(MarketplaceType(str(t).lower()))
                except ValueError:
                    pass
            if valid_types:
                mp_conds.append(Marketplace.type.in_(valid_types))
        if mp_conds:
            query = query.filter(or_(*mp_conds))
        if warehouse_ids:
            query = query.filter(Order.warehouse_id.in_(warehouse_ids))
        if status:
            query = query.filter(Order.status == status)
        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Order.article.ilike(search_pattern),
                    Order.product_name.ilike(search_pattern),
                    Order.posting_number.ilike(search_pattern),
                    Order.external_id.ilike(search_pattern),
                )
            )
        return query.scalar() or 0

    def get_completed_list(
        self,
        user_id: int,
        *,
        skip: int = 0,
        limit: int = 50,
        marketplace_ids: Optional[List[int]] = None,
        marketplace_types: Optional[List[str]] = None,
        warehouse_ids: Optional[List[int]] = None,
        search: Optional[str] = None,
        sort_by: str = "completed_at",
        sort_desc: bool = True,
    ) -> list[Order]:
        """Список заказов, отмеченных «Собрано» в нашем приложении. Только за последние 3 дня."""
        from app.models.marketplace import Marketplace, MarketplaceType

        completed_since = datetime.utcnow() - timedelta(days=3)
        query = (
            self.db.query(Order)
            .join(Marketplace)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.collected_in_app == True)
            .filter(Order.completed_at >= completed_since)
        )
        mp_conds = []
        if marketplace_ids:
            mp_conds.append(Order.marketplace_id.in_(marketplace_ids))
        if marketplace_types:
            valid_types = []
            for t in marketplace_types:
                if not t:
                    continue
                try:
                    valid_types.append(MarketplaceType(str(t).lower()))
                except ValueError:
                    pass
            if valid_types:
                mp_conds.append(Marketplace.type.in_(valid_types))
        if mp_conds:
            query = query.filter(or_(*mp_conds))
        if warehouse_ids:
            query = query.filter(Order.warehouse_id.in_(warehouse_ids))
        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Order.article.ilike(search_pattern),
                    Order.product_name.ilike(search_pattern),
                    Order.posting_number.ilike(search_pattern),
                    Order.external_id.ilike(search_pattern),
                )
            )
        order_col = getattr(Order, sort_by, Order.completed_at)
        if sort_desc:
            query = query.order_by(order_col.desc().nullslast())
        else:
            query = query.order_by(order_col.asc().nullsfirst())
        query = query.options(
            joinedload(Order.marketplace),
            joinedload(Order.warehouse),
            joinedload(Order.assigned_to_user),
        )
        return query.offset(skip).limit(limit).all()

    def get_completed_count(
        self,
        user_id: int,
        *,
        marketplace_ids: Optional[List[int]] = None,
        marketplace_types: Optional[List[str]] = None,
        warehouse_ids: Optional[List[int]] = None,
        search: Optional[str] = None,
    ) -> int:
        """Количество заказов, отмеченных «Собрано» в нашем приложении (за последние 3 дня)."""
        from app.models.marketplace import Marketplace, MarketplaceType

        completed_since = datetime.utcnow() - timedelta(days=3)
        query = (
            self.db.query(func.count(Order.id))
            .join(Marketplace)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.collected_in_app == True)
            .filter(Order.completed_at >= completed_since)
        )
        if marketplace_ids:
            query = query.filter(Order.marketplace_id.in_(marketplace_ids))
        if marketplace_types:
            valid_types = []
            for t in marketplace_types:
                if not t:
                    continue
                try:
                    valid_types.append(MarketplaceType(str(t).lower()))
                except ValueError:
                    pass
            if valid_types:
                query = query.filter(Marketplace.type.in_(valid_types))
        if warehouse_ids:
            query = query.filter(Order.warehouse_id.in_(warehouse_ids))
        if search and search.strip():
            search_pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Order.article.ilike(search_pattern),
                    Order.product_name.ilike(search_pattern),
                    Order.posting_number.ilike(search_pattern),
                    Order.external_id.ilike(search_pattern),
                )
            )
        return query.scalar() or 0

    def get_stats(self, user_id: int) -> dict:
        """
        Общая статистика по заказам пользователя.
        Заказы считаются только из маркетплейсов пользователя.
        """
        from app.models.marketplace import Marketplace

        # Только заказы в сборке (не отмеченные «Собрано» у нас, не COMPLETED от Ozon)
        base = (
            self.db.query(Order)
            .join(Marketplace, Order.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.status != OrderStatus.CANCELLED)
            .filter(Order.status != OrderStatus.DELIVERED)
            .filter(Order.status != OrderStatus.COMPLETED)
            .filter(Order.collected_in_app != True)
        )
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        total = base.count()
        on_assembly = total
        completed_since = datetime.utcnow() - timedelta(days=3)
        completed = (
            self.db.query(Order)
            .join(Marketplace, Order.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.collected_in_app == True)
            .filter(Order.completed_at >= completed_since)
            .count()
        )
        completed_today = (
            self.db.query(Order)
            .join(Marketplace, Order.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.collected_in_app == True)
            .filter(Order.completed_at >= today_start)
            .count()
        )

        # По маркетплейсам: отдельно total и completed для надёжности (за последние 3 дня)
        completed_counts = (
            self.db.query(Order.marketplace_id, func.count(Order.id).label("cnt"))
            .join(Marketplace, Order.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.collected_in_app == True)
            .filter(Order.completed_at >= completed_since)
            .group_by(Order.marketplace_id)
            .all()
        )
        completed_by_mp = {r.marketplace_id: r.cnt for r in completed_counts}

        mp_stats = (
            self.db.query(
                Marketplace.id,
                Marketplace.name,
                Marketplace.type,
                func.count(Order.id).label("total"),
            )
            .join(Order, Order.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .filter(Order.status != OrderStatus.CANCELLED)
            .filter(Order.status != OrderStatus.DELIVERED)
            .filter(Order.status != OrderStatus.COMPLETED)
            .filter(Order.collected_in_app != True)
            .group_by(Marketplace.id, Marketplace.name, Marketplace.type)
            .all()
        )
        by_marketplace = [
            {
                "marketplace_id": r.id,
                "name": r.name,
                "type": r.type.value if r.type else None,
                "total": r.total or 0,
                "completed": completed_by_mp.get(r.id, 0),
            }
            for r in mp_stats
        ]

        return {
            "total": total,
            "on_assembly": on_assembly,
            "completed": completed,
            "completed_today": completed_today,
            "by_marketplace": by_marketplace,
        }

    def release_order(self, order: Order) -> None:
        """Освободить заказ (закрыть окно без «Собрано»)"""
        order.release()
        self.db.commit()
        self.db.refresh(order)

    def mark_completed_by_marketplace(
        self, marketplace_id: int, external_id: str
    ) -> bool:
        """Отметить заказ как собранный по данным маркетплейса (WB complete)."""
        order = self.get_by_external_id(marketplace_id, external_id)
        if not order or order.status == OrderStatus.COMPLETED:
            return False
        order.completed_by_id = None
        order.completed_at = datetime.utcnow()
        order.status = OrderStatus.COMPLETED
        self.db.commit()
        self.db.refresh(order)
        return True

    def mark_cancelled_by_marketplace(
        self, marketplace_id: int, external_id: str
    ) -> bool:
        """Отметить заказ как отменённый по данным маркетплейса (WB cancel)."""
        order = self.get_by_external_id(marketplace_id, external_id)
        if not order or order.status == OrderStatus.CANCELLED:
            return False
        order.cancel()
        self.db.commit()
        self.db.refresh(order)
        return True

    def mark_delivered_by_marketplace(
        self,
        marketplace_id: int,
        external_id: str,
        *,
        posting_number: Optional[str] = None,
    ) -> bool:
        """Отметить заказ как доставленный (Ozon delivered/delivering). Не показывать в списке.
        Для Ozon: ищем по external_id, при неудаче — по posting_number.
        Сбрасываем collected_in_app — при смене статуса с «В сборке» убираем из «Собрано»."""
        order = self.get_by_external_id(marketplace_id, external_id)
        if not order and posting_number:
            order = self.get_by_posting_number(marketplace_id, posting_number)
        if not order or order.status == OrderStatus.DELIVERED:
            return False
        order.status = OrderStatus.DELIVERED
        order.marketplace_status = "delivered"
        order.collected_in_app = False
        self.db.commit()
        self.db.refresh(order)
        return True

    def update_from_marketplace(
        self,
        order: Order,
        *,
        status: Optional[OrderStatus] = None,
        marketplace_status: Optional[str] = None,
        warehouse_id: Optional[int] = None,
        warehouse_name: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Order:
        """Обновить заказ данными из маркетплейса"""
        if marketplace_status:
            order.marketplace_status = marketplace_status
        if status is not None:
            order.status = status
        if warehouse_id is not None:
            order.warehouse_id = warehouse_id
        if warehouse_name is not None:
            order.warehouse_name = warehouse_name
        if metadata is not None:
            order.extra_data = metadata
        self.db.commit()
        self.db.refresh(order)
        return order
