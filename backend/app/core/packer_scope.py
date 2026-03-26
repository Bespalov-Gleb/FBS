"""
Область данных упаковщика: заказы и маркетплейсы владельца (owner_id) и ограничение по магазинам.
"""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.user_marketplace_access import UserMarketplaceAccess


def get_effective_user_and_marketplace_ids(
    current_user: User, db: Session
) -> Tuple[int, Optional[List[int]]]:
    """
    Для упаковщика с owner_id — ID админа и список разрешённых marketplace_id (None = все).
    Для админа — свой ID и None.
    """
    if current_user.role == UserRole.PACKER and current_user.owner_id:
        effective_user_id = current_user.owner_id
        rows = (
            db.query(UserMarketplaceAccess)
            .filter(UserMarketplaceAccess.user_id == current_user.id)
            .all()
        )
        allowed = [r.marketplace_id for r in rows] if rows else None
        return effective_user_id, allowed
    return current_user.id, None
