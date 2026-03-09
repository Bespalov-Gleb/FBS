"""
API endpoints для пользователей (админ)
"""
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentAdminUser
from app.core.security import get_password_hash
from app.models.invite_code import InviteCode
from app.models.marketplace import Marketplace
from app.models.order import Order
from app.models.user import User, UserRole
from app.models.user_marketplace_access import UserMarketplaceAccess
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])

INVITE_TTL_HOURS = 24


# ─────────────────────────────────────────
# Схемы ответов
# ─────────────────────────────────────────

class InviteCodeResponse(BaseModel):
    code: str
    expires_at: datetime
    used: bool
    used_by_name: Optional[str] = None


class MarketplaceAccessResponse(BaseModel):
    marketplace_id: int
    marketplace_name: str


class MarketplaceAccessUpdate(BaseModel):
    marketplace_ids: List[int]


class UserStatsResponse(BaseModel):
    orders_last_hour: int
    orders_today: int
    orders_total: int
    avg_minutes_per_order: Optional[float]


# ─────────────────────────────────────────
# Инвайт-коды (должны быть до /{user_id})
# ─────────────────────────────────────────

@router.post("/invite-code", response_model=InviteCodeResponse)
def create_invite_code(
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Сгенерировать инвайт-код для регистрации упаковщика.
    Код действует 24 часа и может быть использован один раз.
    """
    code = secrets.token_hex(8)  # 16 символов hex
    expires_at = datetime.utcnow() + timedelta(hours=INVITE_TTL_HOURS)
    invite = InviteCode(
        code=code,
        created_by_id=current_user.id,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return InviteCodeResponse(code=invite.code, expires_at=invite.expires_at, used=False)


@router.get("/invite-codes", response_model=list[InviteCodeResponse])
def list_invite_codes(
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Список инвайт-кодов текущего администратора (последние 50)."""
    invites = (
        db.query(InviteCode)
        .filter(InviteCode.created_by_id == current_user.id)
        .order_by(InviteCode.created_at.desc())
        .limit(50)
        .all()
    )
    result = []
    for inv in invites:
        used_by_name: Optional[str] = None
        if inv.used_by_id:
            used_by = db.query(User).filter(User.id == inv.used_by_id).first()
            used_by_name = used_by.full_name if used_by else None
        result.append(
            InviteCodeResponse(
                code=inv.code,
                expires_at=inv.expires_at,
                used=inv.is_used,
                used_by_name=used_by_name,
            )
        )
    return result


# ─────────────────────────────────────────
# CRUD пользователей (только admin)
# ─────────────────────────────────────────

@router.get("", response_model=list[UserResponse])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Список пользователей"""
    role_enum = None
    if role:
        try:
            role_enum = UserRole(role)
        except ValueError:
            pass
    repo = UserRepository(db)
    users = repo.get_all(skip=skip, limit=limit, role=role_enum, is_active=is_active)
    return [
        UserResponse(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value,
            is_active=u.is_active,
        )
        for u in users
    ]


@router.post("", response_model=UserResponse)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Добавить пользователя-упаковщика"""
    repo = UserRepository(db)
    if repo.get_by_email(data.email):
        raise HTTPException(400, detail="Email already registered")
    try:
        role = UserRole(data.role)
    except ValueError:
        role = UserRole.PACKER
    user = repo.create(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role=role,
    )
    if role == UserRole.PACKER:
        user.owner_id = current_user.id
        db.commit()
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Получить пользователя"""
    repo = UserRepository(db)
    user = repo.get(user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
    )


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Обновить пользователя"""
    repo = UserRepository(db)
    user = repo.get(user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    role_enum = None
    if data.role:
        try:
            role_enum = UserRole(data.role)
        except ValueError:
            pass
    user = repo.update(
        user_id,
        full_name=data.full_name,
        role=role_enum,
        is_active=data.is_active,
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
    )


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Деактивировать пользователя"""
    repo = UserRepository(db)
    user = repo.get(user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(400, detail="Cannot deactivate yourself")
    repo.update(user_id, is_active=False)
    return {"ok": True}


# ─────────────────────────────────────────
# Доступ упаковщика к магазинам
# ─────────────────────────────────────────

@router.get("/{user_id}/marketplace-access", response_model=list[MarketplaceAccessResponse])
def get_marketplace_access(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Получить список маркетплейсов, к которым разрешён доступ упаковщику.
    Пустой список означает доступ ко всем магазинам владельца.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")
    rows = (
        db.query(UserMarketplaceAccess)
        .filter(UserMarketplaceAccess.user_id == user_id)
        .all()
    )
    result = []
    for row in rows:
        mp = db.query(Marketplace).filter(Marketplace.id == row.marketplace_id).first()
        if mp:
            result.append(MarketplaceAccessResponse(
                marketplace_id=mp.id,
                marketplace_name=mp.name,
            ))
    return result


@router.put("/{user_id}/marketplace-access")
def set_marketplace_access(
    user_id: int,
    data: MarketplaceAccessUpdate,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Установить список маркетплейсов упаковщика.
    Передайте пустой список, чтобы разрешить доступ ко всем магазинам.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")
    db.query(UserMarketplaceAccess).filter(
        UserMarketplaceAccess.user_id == user_id
    ).delete()
    for mp_id in data.marketplace_ids:
        mp = db.query(Marketplace).filter(Marketplace.id == mp_id).first()
        if mp:
            db.add(UserMarketplaceAccess(user_id=user_id, marketplace_id=mp_id))
    db.commit()
    return {"ok": True, "marketplace_ids": data.marketplace_ids}


# ─────────────────────────────────────────
# Статистика упаковщика
# ─────────────────────────────────────────

@router.get("/{user_id}/stats", response_model=UserStatsResponse)
def get_user_stats(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """
    Статистика упаковщика: заказы за последний час, сегодня, всего.
    avg_minutes_per_order — среднее время сборки (только для завершённых заказов с assigned_at).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, detail="User not found")

    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    base_q = db.query(Order).filter(Order.completed_by_id == user_id)

    orders_last_hour = base_q.filter(Order.completed_at >= hour_ago).count()
    orders_today = base_q.filter(Order.completed_at >= today_start).count()
    orders_total = base_q.count()

    avg_minutes: Optional[float] = None
    timed_orders = (
        base_q
        .filter(Order.assigned_at.isnot(None))
        .filter(Order.completed_at.isnot(None))
        .with_entities(Order.assigned_at, Order.completed_at)
        .all()
    )
    if timed_orders:
        total_seconds = sum(
            (o.completed_at - o.assigned_at).total_seconds()
            for o in timed_orders
            if o.completed_at > o.assigned_at
        )
        count = len([o for o in timed_orders if o.completed_at > o.assigned_at])
        if count > 0:
            avg_minutes = round(total_seconds / count / 60, 1)

    return UserStatsResponse(
        orders_last_hour=orders_last_hour,
        orders_today=orders_today,
        orders_total=orders_total,
        avg_minutes_per_order=avg_minutes,
    )
