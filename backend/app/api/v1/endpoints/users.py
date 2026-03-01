"""
API endpoints для пользователей (админ)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentAdminUser
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


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
