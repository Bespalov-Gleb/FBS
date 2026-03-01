"""
Утилиты для работы с Redis кэшем
"""
import json
from typing import Any, Optional

import redis
from redis import Redis

from app.config import settings
from app.utils.logger import logger

# Глобальный клиент Redis
_redis_client: Optional[Redis] = None


def get_redis_client() -> Redis:
    """
    Получение клиента Redis
    
    Returns:
        Redis: Клиент Redis
    """
    global _redis_client
    
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                str(settings.REDIS_URL),
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Проверка соединения
            _redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    return _redis_client


def cache_set(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """
    Сохранение значения в кэш
    
    Args:
        key: Ключ кэша
        value: Значение (будет сериализовано в JSON)
        ttl: Время жизни в секундах (опционально)
        
    Returns:
        bool: True если успешно
    """
    try:
        client = get_redis_client()
        serialized = json.dumps(value, ensure_ascii=False)
        
        if ttl:
            client.setex(key, ttl, serialized)
        else:
            client.set(key, serialized)
        
        return True
    except Exception as e:
        logger.error(f"Cache set error for key {key}: {e}")
        return False


def cache_get(key: str) -> Optional[Any]:
    """
    Получение значения из кэша
    
    Args:
        key: Ключ кэша
        
    Returns:
        Optional[Any]: Значение или None если не найдено
    """
    try:
        client = get_redis_client()
        value = client.get(key)
        
        if value is None:
            return None
        
        return json.loads(value)
    except Exception as e:
        logger.error(f"Cache get error for key {key}: {e}")
        return None


def cache_delete(key: str) -> bool:
    """
    Удаление значения из кэша
    
    Args:
        key: Ключ кэша
        
    Returns:
        bool: True если успешно
    """
    try:
        client = get_redis_client()
        client.delete(key)
        return True
    except Exception as e:
        logger.error(f"Cache delete error for key {key}: {e}")
        return False


def cache_delete_pattern(pattern: str) -> int:
    """
    Удаление значений из кэша по паттерну
    
    Args:
        pattern: Паттерн для поиска ключей (например, "user:*")
        
    Returns:
        int: Количество удаленных ключей
    """
    try:
        client = get_redis_client()
        keys = client.keys(pattern)
        
        if not keys:
            return 0
        
        return client.delete(*keys)
    except Exception as e:
        logger.error(f"Cache delete pattern error for pattern {pattern}: {e}")
        return 0


def cache_exists(key: str) -> bool:
    """
    Проверка существования ключа в кэше
    
    Args:
        key: Ключ кэша
        
    Returns:
        bool: True если ключ существует
    """
    try:
        client = get_redis_client()
        return client.exists(key) > 0
    except Exception as e:
        logger.error(f"Cache exists error for key {key}: {e}")
        return False


def get_cache_key(*parts: str) -> str:
    """
    Генерация ключа кэша из частей
    
    Args:
        *parts: Части ключа
        
    Returns:
        str: Ключ кэша (например, "user:123:profile")
        
    Example:
        >>> get_cache_key("user", "123", "profile")
        "user:123:profile"
    """
    return ":".join(str(part) for part in parts)


# Специализированные функции для кэширования

def cache_orders(marketplace_id: int, data: Any, ttl: Optional[int] = None) -> bool:
    """
    Кэширование списка заказов для маркетплейса
    
    Args:
        marketplace_id: ID маркетплейса
        data: Данные заказов
        ttl: Время жизни (по умолчанию из настроек)
        
    Returns:
        bool: True если успешно
    """
    key = get_cache_key("orders", marketplace_id)
    return cache_set(key, data, ttl or settings.CACHE_TTL_ORDERS)


def get_cached_orders(marketplace_id: int) -> Optional[Any]:
    """
    Получение кэшированных заказов для маркетплейса
    
    Args:
        marketplace_id: ID маркетплейса
        
    Returns:
        Optional[Any]: Данные заказов или None
    """
    key = get_cache_key("orders", marketplace_id)
    return cache_get(key)


def invalidate_orders_cache(marketplace_id: Optional[int] = None) -> int:
    """
    Инвалидация кэша заказов
    
    Args:
        marketplace_id: ID маркетплейса (если None - для всех)
        
    Returns:
        int: Количество удаленных ключей
    """
    if marketplace_id is None:
        pattern = get_cache_key("orders", "*")
    else:
        pattern = get_cache_key("orders", marketplace_id)
    
    return cache_delete_pattern(pattern)


def cache_user(user_id: int, data: Any, ttl: Optional[int] = None) -> bool:
    """
    Кэширование данных пользователя
    
    Args:
        user_id: ID пользователя
        data: Данные пользователя
        ttl: Время жизни (по умолчанию из настроек)
        
    Returns:
        bool: True если успешно
    """
    key = get_cache_key("user", user_id)
    return cache_set(key, data, ttl or settings.CACHE_TTL_USER)


def get_cached_user(user_id: int) -> Optional[Any]:
    """
    Получение кэшированных данных пользователя
    
    Args:
        user_id: ID пользователя
        
    Returns:
        Optional[Any]: Данные пользователя или None
    """
    key = get_cache_key("user", user_id)
    return cache_get(key)


def invalidate_user_cache(user_id: int) -> bool:
    """
    Инвалидация кэша пользователя
    
    Args:
        user_id: ID пользователя
        
    Returns:
        bool: True если успешно
    """
    key = get_cache_key("user", user_id)
    return cache_delete(key)
