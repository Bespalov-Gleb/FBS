"""
Схемы для аутентификации
"""
from pydantic import BaseModel, EmailStr, Field

# bcrypt ограничен 72 байтами
PASSWORD_MAX_LENGTH = 72


class LoginRequest(BaseModel):
    """Запрос на вход"""
    email: EmailStr
    password: str = Field(..., max_length=PASSWORD_MAX_LENGTH)


class RegisterRequest(BaseModel):
    """Запрос на регистрацию"""
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=PASSWORD_MAX_LENGTH)
    full_name: str


class TokenResponse(BaseModel):
    """Ответ с токенами"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Запрос на обновление токена"""
    refresh_token: str


class AccessTokenResponse(BaseModel):
    """Ответ с access токеном"""
    access_token: str
    token_type: str = "bearer"
