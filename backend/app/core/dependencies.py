"""
Dependency Injection для FastAPI
"""
from typing import Generator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

# Security scheme для Swagger
security = HTTPBearer()


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Получение текущего пользователя из JWT токена
    
    Args:
        db: Сессия БД
        credentials: Токен из заголовка Authorization
        
    Returns:
        User: Текущий пользователь
        
    Raises:
        UnauthorizedException: Если токен невалидный или пользователь не найден
    """
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise UnauthorizedException(message="Could not validate credentials")
    
    token_type = payload.get("type")
    if token_type != "access":
        raise UnauthorizedException(message="Invalid token type")
    
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException(message="Could not validate credentials")
    
    # Получение пользователя из БД
    user_repo = UserRepository(db)
    user = user_repo.get(int(user_id))
    
    if user is None:
        raise UnauthorizedException(message="User not found")
    
    if not user.is_active:
        raise UnauthorizedException(message="User is inactive")
    
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Получение текущего активного пользователя
    
    Args:
        current_user: Текущий пользователь
        
    Returns:
        User: Активный пользователь
        
    Raises:
        ForbiddenException: Если пользователь неактивен
    """
    if not current_user.is_active:
        raise ForbiddenException(message="Inactive user")
    return current_user


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Получение текущего пользователя-администратора
    
    Args:
        current_user: Текущий пользователь
        
    Returns:
        User: Пользователь с ролью администратора
        
    Raises:
        ForbiddenException: Если пользователь не администратор
    """
    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException(message="Not enough permissions")
    return current_user


def get_optional_current_user(
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Optional[User]:
    """
    Получение текущего пользователя (опционально)
    Используется для endpoints, где авторизация опциональна
    
    Args:
        db: Сессия БД
        credentials: Токен из заголовка Authorization (опционально)
        
    Returns:
        Optional[User]: Пользователь или None
    """
    if credentials is None:
        return None
    
    try:
        return get_current_user(db, credentials)
    except (UnauthorizedException, JWTError):
        return None


# Алиасы для удобства
CurrentUser = Depends(get_current_user)
CurrentActiveUser = Depends(get_current_active_user)
CurrentAdminUser = Depends(get_current_admin_user)
OptionalCurrentUser = Depends(get_optional_current_user)
