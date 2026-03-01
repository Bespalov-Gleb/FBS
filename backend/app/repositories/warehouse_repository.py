"""
Репозиторий для работы со складами
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.warehouse import Warehouse


class WarehouseRepository:
    """CRUD операции для складов"""

    @staticmethod
    def get_by_id(db: Session, warehouse_id: int) -> Optional[Warehouse]:
        """Получить склад по ID"""
        return db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()

    @staticmethod
    def get_by_marketplace_and_external(
        db: Session,
        marketplace_id: int,
        external_warehouse_id: str,
    ) -> Optional[Warehouse]:
        """Получить склад по marketplace и external ID"""
        return (
            db.query(Warehouse)
            .filter(
                Warehouse.marketplace_id == marketplace_id,
                Warehouse.external_warehouse_id == str(external_warehouse_id),
            )
            .first()
        )

    @staticmethod
    def get_by_marketplace(db: Session, marketplace_id: int) -> list[Warehouse]:
        """Получить все склады маркетплейса"""
        return (
            db.query(Warehouse)
            .filter(Warehouse.marketplace_id == marketplace_id)
            .order_by(Warehouse.name)
            .all()
        )

    @staticmethod
    def get_all_for_user(db: Session, user_id: int, marketplace_type: Optional[str] = None) -> list:
        """Получить все склады пользователя (через маркетплейсы). Опционально по типу."""
        from app.models.marketplace import Marketplace, MarketplaceType

        query = (
            db.query(Warehouse)
            .join(Marketplace, Warehouse.marketplace_id == Marketplace.id)
            .filter(Marketplace.user_id == user_id)
            .order_by(Marketplace.name, Warehouse.name)
        )
        if marketplace_type:
            try:
                mp_type = MarketplaceType(marketplace_type)
                query = query.filter(Marketplace.type == mp_type)
            except ValueError:
                pass
        return query.all()

    @staticmethod
    def create(
        db: Session,
        marketplace_id: int,
        external_warehouse_id: str,
        name: str,
        color: Optional[str] = None,
    ) -> Warehouse:
        """Создать склад"""
        warehouse = Warehouse(
            marketplace_id=marketplace_id,
            external_warehouse_id=str(external_warehouse_id),
            name=name,
            color=color,
        )
        db.add(warehouse)
        db.commit()
        db.refresh(warehouse)
        return warehouse

    @staticmethod
    def get_or_create(
        db: Session,
        marketplace_id: int,
        external_warehouse_id: str,
        name: str,
        color: Optional[str] = None,
    ) -> Warehouse:
        """Получить или создать склад"""
        warehouse = WarehouseRepository.get_by_marketplace_and_external(
            db, marketplace_id, str(external_warehouse_id)
        )
        if warehouse:
            return warehouse
        return WarehouseRepository.create(
            db, marketplace_id, external_warehouse_id, name, color
        )

    @staticmethod
    def update_color(db: Session, warehouse_id: int, color: str) -> Optional[Warehouse]:
        """Обновить цвет склада"""
        warehouse = WarehouseRepository.get_by_id(db, warehouse_id)
        if not warehouse:
            return None
        warehouse.color = color
        db.commit()
        db.refresh(warehouse)
        return warehouse
