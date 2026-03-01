"""
Кастомные исключения приложения
"""
from typing import Any, Optional


class AppException(Exception):
    """Базовое исключение приложения"""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(self.message)


class NotFoundException(AppException):
    """Исключение - ресурс не найден"""
    
    def __init__(self, message: str = "Resource not found", detail: Optional[Any] = None):
        super().__init__(message, status_code=404, detail=detail)


class UnauthorizedException(AppException):
    """Исключение - не авторизован"""
    
    def __init__(self, message: str = "Unauthorized", detail: Optional[Any] = None):
        super().__init__(message, status_code=401, detail=detail)


class ForbiddenException(AppException):
    """Исключение - доступ запрещен"""
    
    def __init__(self, message: str = "Forbidden", detail: Optional[Any] = None):
        super().__init__(message, status_code=403, detail=detail)


class BadRequestException(AppException):
    """Исключение - неверный запрос"""
    
    def __init__(self, message: str = "Bad request", detail: Optional[Any] = None):
        super().__init__(message, status_code=400, detail=detail)


class ConflictException(AppException):
    """Исключение - конфликт данных"""
    
    def __init__(self, message: str = "Conflict", detail: Optional[Any] = None):
        super().__init__(message, status_code=409, detail=detail)


class ValidationException(AppException):
    """Исключение - ошибка валидации"""
    
    def __init__(self, message: str = "Validation error", detail: Optional[Any] = None):
        super().__init__(message, status_code=422, detail=detail)


class MarketplaceAPIException(AppException):
    """Исключение при работе с API маркетплейса"""
    
    def __init__(
        self,
        message: str = "Marketplace API error",
        marketplace: Optional[str] = None,
        detail: Optional[Any] = None,
        status_code: int = 502,
    ):
        self.marketplace = marketplace
        super().__init__(message, status_code=status_code, detail=detail)


class RateLimitException(AppException):
    """Исключение - превышен лимит запросов"""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
    ):
        detail = {"retry_after": retry_after} if retry_after else None
        super().__init__(message, status_code=429, detail=detail)
