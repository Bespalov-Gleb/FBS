"""
Базовый класс для интеграции с маркетплейсами
"""
import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx

from app.core.exceptions import MarketplaceAPIException, RateLimitException
from app.utils.logger import logger

# Настройки retry
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_BASE = 1.0  # секунды
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)

# Rate limiting: консервативные лимиты (WB: 1-60 req/min, Ozon: daily limits)
DEFAULT_REQUESTS_PER_MINUTE = 50
RATE_LIMIT_WINDOW_SECONDS = 60


class OrderStatus(str, Enum):
    """Статусы заказов (общие для всех маркетплейсов)"""
    AWAITING_PACKAGING = "awaiting_packaging"  # Ожидает упаковки
    PACKAGING = "packaging"  # В процессе упаковки
    COMPLETED = "completed"  # Собран
    CANCELLED = "cancelled"  # Отменен


@dataclass
class Product:
    """Товар в заказе"""
    article: str
    name: str
    quantity: int
    sku: Optional[str] = None
    price: Optional[float] = None


@dataclass
class MarketplaceOrder:
    """Заказ из маркетплейса (унифицированный формат)"""
    external_id: str  # ID в маркетплейсе
    posting_number: str  # Номер отправления
    article: str  # Артикул (основного товара)
    product_name: str
    quantity: int
    warehouse_name: Optional[str]
    status: str  # Статус в маркетплейсе
    created_at: Optional[datetime]
    metadata: dict[str, Any]  # Дополнительные данные


class BaseMarketplaceClient(ABC):
    """Абстрактный базовый класс для клиентов маркетплейсов"""
    
    def __init__(
        self,
        api_key: str,
        client_id: Optional[str] = None,
        timeout: int = 30,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
    ):
        """
        Инициализация клиента
        
        Args:
            api_key: API ключ
            client_id: Client ID (для Ozon)
            timeout: Таймаут запросов в секундах
            requests_per_minute: Лимит запросов в минуту (rate limiting)
        """
        self.api_key = api_key
        self.client_id = client_id
        self.timeout = timeout
        self.requests_per_minute = requests_per_minute
        self._client: Optional[httpx.AsyncClient] = None
        self._request_timestamps: list[float] = []
        self._rate_limit_lock = asyncio.Lock()
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """Базовый URL API маркетплейса"""
        pass
    
    @property
    @abstractmethod
    def marketplace_name(self) -> str:
        """Название маркетплейса"""
        pass
    
    @abstractmethod
    def _get_headers(self) -> dict[str, str]:
        """Получение заголовков для запросов"""
        pass
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Получение HTTP клиента"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self._get_headers(),
            )
        return self._client
    
    async def close(self) -> None:
        """Закрытие HTTP клиента"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
        return False
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> dict[str, Any]:
        """
        Выполнение HTTP запроса к API с retry при временных ошибках
        
        Retry при: 429, 5xx, сетевых ошибках.
        Exponential backoff: 1s, 2s, 4s.
        
        Args:
            method: HTTP метод (GET, POST и т.д.)
            endpoint: Endpoint API
            params: Query параметры
            json_data: JSON данные для тела запроса
            max_retries: Максимум попыток (0 = без retry)
            
        Returns:
            dict: Ответ от API
            
        Raises:
            MarketplaceAPIException: При ошибке API
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(max_retries + 1):
            try:
                return await self._do_request(method, endpoint, params, json_data)
            except (MarketplaceAPIException, RateLimitException) as e:
                last_exception = e
                # Retry только для retryable ошибок
                if attempt < max_retries and self._is_retryable(e):
                    wait_time = DEFAULT_RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        f"Retry {attempt + 1}/{max_retries} after {wait_time}s",
                        extra={
                            "marketplace": self.marketplace_name,
                            "endpoint": endpoint,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except httpx.HTTPError as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = DEFAULT_RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        f"Network error, retry {attempt + 1}/{max_retries} after {wait_time}s",
                        extra={"marketplace": self.marketplace_name, "error": str(e)},
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise MarketplaceAPIException(
                        message=f"HTTP error: {str(e)}",
                        marketplace=self.marketplace_name,
                        detail=str(e),
                    )
        
        if last_exception:
            raise last_exception
        raise MarketplaceAPIException(
            message="Request failed",
            marketplace=self.marketplace_name,
        )
    
    def _extract_error_message(self, error_detail: Any) -> Optional[str]:
        """Извлечь человекочитаемое сообщение из ответа API маркетплейса"""
        if isinstance(error_detail, str) and error_detail.strip():
            return error_detail[:500]
        if isinstance(error_detail, dict):
            # Ozon gRPC-style: details: [{message: "..."}]
            details = error_detail.get("details")
            if isinstance(details, list) and details:
                first = details[0]
                if isinstance(first, dict) and first.get("message"):
                    return str(first["message"])
            msg = (
                error_detail.get("message")
                or error_detail.get("error")
                or error_detail.get("detail")
            )
            if msg:
                return str(msg) if not isinstance(msg, dict) else str(msg.get("message", msg))
            errors = error_detail.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                return str(first.get("message", first)) if isinstance(first, dict) else str(first)
        return None

    def _is_retryable(self, e: Exception) -> bool:
        """Проверка, стоит ли повторять запрос"""
        if isinstance(e, RateLimitException):
            return True
        if isinstance(e, MarketplaceAPIException) and e.status_code in RETRYABLE_STATUS_CODES:
            return True
        return False
    
    async def _wait_for_rate_limit(self) -> None:
        """
        Ожидание при необходимости для соблюдения rate limit.
        Sliding window: не более N запросов за последние 60 секунд.
        """
        if self.requests_per_minute <= 0:
            return
        
        async with self._rate_limit_lock:
            now = time.monotonic()
            cutoff = now - RATE_LIMIT_WINDOW_SECONDS
            self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]
            
            if len(self._request_timestamps) >= self.requests_per_minute:
                oldest = min(self._request_timestamps)
                wait_time = (oldest + RATE_LIMIT_WINDOW_SECONDS) - now
                if wait_time > 0:
                    logger.debug(
                        f"Rate limit: waiting {wait_time:.1f}s",
                        extra={"marketplace": self.marketplace_name},
                    )
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
                    self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]
            
            self._request_timestamps.append(now)
    
    async def _do_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]],
        json_data: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Выполнение одного HTTP запроса без retry"""
        await self._wait_for_rate_limit()
        client = await self._get_client()
        
        logger.info(
            f"Making {method} request to {self.marketplace_name} API",
            extra={
                "marketplace": self.marketplace_name,
                "method": method,
                "endpoint": endpoint,
            },
        )
        
        response = await client.request(
            method=method,
            url=endpoint,
            params=params,
            json=json_data,
        )
        
        logger.info(
            f"Received response from {self.marketplace_name} API",
            extra={
                "marketplace": self.marketplace_name,
                "status_code": response.status_code,
                "endpoint": endpoint,
            },
        )
        
        if response.status_code >= 400:
            error_detail = response.text
            try:
                error_json = response.json()
                error_detail = error_json
            except Exception:
                pass
            
            err_msg = str(error_detail)[:500] if error_detail else ""
            log_fn = logger.warning if response.status_code == 404 else logger.error
            log_fn(
                f"API error from {self.marketplace_name}: HTTP {response.status_code} — {err_msg}",
                extra={
                    "marketplace": self.marketplace_name,
                    "status_code": response.status_code,
                    "error": error_detail,
                },
            )
            
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", 60)
                raise RateLimitException(
                    message="Rate limit exceeded",
                    retry_after=int(retry_after) if str(retry_after).isdigit() else 60,
                )
            
            raise MarketplaceAPIException(
                message=f"{self.marketplace_name} API error: HTTP {response.status_code}",
                marketplace=self.marketplace_name,
                detail=error_detail,
                status_code=response.status_code,
            )
        
        return response.json()
    
    async def _request_content(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict[str, Any]] = None,
    ) -> bytes:
        """
        Выполнение HTTP запроса с возвратом бинарного контента
        
        Используется для получения PDF, изображений и т.д.
        
        Args:
            method: HTTP метод
            endpoint: Endpoint API
            json_data: JSON данные для тела запроса
            
        Returns:
            bytes: Бинарное содержимое ответа
        """
        await self._wait_for_rate_limit()
        client = await self._get_client()
        
        try:
            response = await client.request(
                method=method,
                url=endpoint,
                json=json_data,
            )
            
            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_detail = response.json()
                except Exception:
                    pass
                logger.error(
                    f"{self.marketplace_name} API error",
                    extra={
                        "marketplace": self.marketplace_name,
                        "status_code": response.status_code,
                        "endpoint": endpoint,
                        "response_body": error_detail,
                    },
                )
                # Человекочитаемое сообщение из ответа API
                msg = self._extract_error_message(error_detail)
                raise MarketplaceAPIException(
                    message=f"{self.marketplace_name} API error: HTTP {response.status_code}",
                    marketplace=self.marketplace_name,
                    detail=msg or error_detail,
                    status_code=response.status_code,
                )
            
            return response.content
            
        except httpx.HTTPError as e:
            logger.error(
                f"HTTP error when calling {self.marketplace_name} API",
                extra={"marketplace": self.marketplace_name, "error": str(e)},
                exc_info=True,
            )
            raise MarketplaceAPIException(
                message=f"HTTP error: {str(e)}",
                marketplace=self.marketplace_name,
                detail=str(e),
            )
            
        except MarketplaceAPIException:
            raise
            
        except Exception as e:
            raise MarketplaceAPIException(
                message=str(e),
                marketplace=self.marketplace_name,
                detail=str(e),
            )
    
    @abstractmethod
    async def get_orders(
        self,
        warehouse_id: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
    ) -> list[MarketplaceOrder]:
        """
        Получение списка заказов
        
        Args:
            warehouse_id: ID склада для фильтрации
            since: Начало периода
            to: Конец периода
            
        Returns:
            list[MarketplaceOrder]: Список заказов
        """
        pass
    
    @abstractmethod
    async def get_order_label(self, order_id: str) -> bytes:
        """
        Получение этикетки заказа
        
        Args:
            order_id: ID заказа
            
        Returns:
            bytes: Данные этикетки (PDF, PNG и т.д.)
        """
        pass
    
    @abstractmethod
    async def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
    ) -> bool:
        """
        Обновление статуса заказа
        
        Args:
            order_id: ID заказа
            status: Новый статус
            
        Returns:
            bool: True если успешно
        """
        pass
