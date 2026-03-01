"""
Схемы для пользователей
"""
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    """Создание пользователя"""
    email: EmailStr
    password: str
    full_name: str
    role: str = "packer"  # admin | packer


class UserUpdate(BaseModel):
    """Обновление пользователя"""
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """Ответ с данными пользователя"""
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


class UserMeResponse(BaseModel):
    """Текущий пользователь (профиль)"""
    id: int
    email: str
    full_name: str
    role: str
