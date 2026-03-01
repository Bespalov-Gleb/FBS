"""
Репозиторий для работы с маркетплейсами
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.marketplace import Marketplace, MarketplaceType


class MarketplaceRepository:
    """CRUD операции для маркетплейсов"""

    def __init__(self, db: Session):
        self.db = db

    def get(self, marketplace_id: int) -> Optional[Marketplace]:
        """Получить маркетплейс по ID"""
        return self.db.query(Marketplace).filter(Marketplace.id == marketplace_id).first()

    def get_by_user(
        self,
        user_id: int,
        *,
        is_active: Optional[bool] = None,
        type_filter: Optional[MarketplaceType] = None,
    ) -> list[Marketplace]:
        """Получить маркетплейсы пользователя"""
        query = self.db.query(Marketplace).filter(Marketplace.user_id == user_id)
        if is_active is not None:
            query = query.filter(Marketplace.is_active == is_active)
        if type_filter:
            query = query.filter(Marketplace.type == type_filter)
        return query.order_by(Marketplace.name).all()

    def create(
        self,
        user_id: int,
        type_: MarketplaceType,
        name: str,
        api_key_encrypted: str,
        *,
        client_id: Optional[str] = None,
        is_kiz_enabled: bool = False,
        save_kiz_to_file: bool = False,
    ) -> Marketplace:
        """Создать маркетплейс"""
        mp = Marketplace(
            user_id=user_id,
            type=type_,
            name=name,
            api_key=api_key_encrypted,
            client_id=client_id,
            is_kiz_enabled=is_kiz_enabled,
            save_kiz_to_file=save_kiz_to_file,
        )
        self.db.add(mp)
        self.db.commit()
        self.db.refresh(mp)
        return mp

    def update(
        self,
        marketplace_id: int,
        *,
        name: Optional[str] = None,
        is_kiz_enabled: Optional[bool] = None,
        save_kiz_to_file: Optional[bool] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Marketplace]:
        """Обновить маркетплейс"""
        mp = self.get(marketplace_id)
        if not mp:
            return None
        if name is not None:
            mp.name = name
        if is_kiz_enabled is not None:
            mp.is_kiz_enabled = is_kiz_enabled
        if save_kiz_to_file is not None:
            mp.save_kiz_to_file = save_kiz_to_file
        if is_active is not None:
            mp.is_active = is_active
        self.db.commit()
        self.db.refresh(mp)
        return mp

    def delete(self, marketplace_id: int) -> bool:
        """Удалить маркетплейс"""
        mp = self.get(marketplace_id)
        if not mp:
            return False
        self.db.delete(mp)
        self.db.commit()
        return True
