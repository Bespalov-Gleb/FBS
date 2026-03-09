"""
API endpoints для аутентификации
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.invite_code import InviteCode
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserMeResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Регистрация нового пользователя.
    Если передан invite_code — упаковщик привязывается к администратору,
    выпустившему код. Без кода создаётся самостоятельный аккаунт (admin по умолчанию).
    """
    user_repo = UserRepository(db)
    if user_repo.get_by_email(data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже зарегистрирован",
        )

    owner_id: int | None = None
    invite: InviteCode | None = None

    if data.invite_code and data.invite_code.strip():
        invite = (
            db.query(InviteCode)
            .filter(InviteCode.code == data.invite_code.strip())
            .first()
        )
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Инвайт-код не найден",
            )
        if not invite.is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Инвайт-код истёк или уже использован",
            )
        owner_id = invite.created_by_id

    # Без инвайта — первый пользователь или самостоятельный admin;
    # с инвайтом — упаковщик под владельцем
    role = UserRole.PACKER if owner_id else UserRole.ADMIN
    user = user_repo.create(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        role=role,
    )

    if owner_id:
        user.owner_id = owner_id

    if invite:
        from datetime import datetime
        invite.used_by_id = user.id
        invite.used_at = datetime.utcnow()

    db.commit()

    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    Вход по email и паролю.
    Возвращает access и refresh токены.
    """
    user_repo = UserRepository(db)
    user = user_repo.get_by_email(data.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь деактивирован",
        )
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """
    Обновление access токена по refresh токену.
    """
    payload = decode_token(data.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный refresh токен",
        )
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный тип токена",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный refresh токен",
        )
    user_repo = UserRepository(db)
    user = user_repo.get(int(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден или деактивирован",
        )
    return AccessTokenResponse(
        access_token=create_access_token(subject=str(user.id)),
    )


@router.get("/me", response_model=UserMeResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Получить текущего пользователя (профиль)"""
    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
    )
