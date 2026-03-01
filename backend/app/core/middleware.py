"""
Middleware для приложения
"""
import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import AppException
from app.utils.logger import logger


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления trace_id к каждому запросу"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Генерация или получение trace_id
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Добавление trace_id в контекст запроса
        request.state.trace_id = trace_id
        
        # Выполнение запроса
        response = await call_next(request)
        
        # Добавление trace_id в заголовки ответа
        response.headers["X-Request-ID"] = trace_id
        
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для логирования запросов и ответов"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Получение trace_id
        trace_id = getattr(request.state, "trace_id", "unknown")
        
        # Логирование запроса
        logger.info(
            f"Request started",
            extra={
                "trace_id": trace_id,
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )
        
        # Замер времени выполнения
        start_time = time.time()
        
        try:
            response = await call_next(request)
            process_time = (time.time() - start_time) * 1000  # в миллисекундах
            
            # Логирование ответа
            logger.info(
                f"Request completed",
                extra={
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(process_time, 2),
                },
            )
            
            # Добавление времени выполнения в заголовки
            response.headers["X-Process-Time"] = str(round(process_time, 2))
            
            return response
            
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            
            # Логирование ошибки
            logger.error(
                f"Request failed: {str(e)}",
                extra={
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(process_time, 2),
                },
                exc_info=True,
            )
            
            raise


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Middleware для обработки исключений"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except AppException as e:
            # Обработка кастомных исключений приложения
            trace_id = getattr(request.state, "trace_id", "unknown")
            
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": {
                        "message": e.message,
                        "detail": e.detail,
                        "trace_id": trace_id,
                    }
                },
            )
        except Exception as e:
            # Обработка неожиданных исключений
            trace_id = getattr(request.state, "trace_id", "unknown")
            
            logger.error(
                f"Unhandled exception: {str(e)}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": {
                        "message": "Internal server error",
                        "detail": None,
                        "trace_id": trace_id,
                    }
                },
            )
