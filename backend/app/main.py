"""
Главный модуль FastAPI приложения
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import __version__
from app.config import settings
from app.core.middleware import (
    ExceptionHandlerMiddleware,
    LoggingMiddleware,
    RequestIDMiddleware,
)
from app.utils.logger import logger


# Rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Контекстный менеджер для startup и shutdown событий
    """
    # Startup
    logger.info(
        f"Starting {settings.APP_NAME} v{__version__}",
        extra={
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
        },
    )
    
    # Проверка подключения к БД
    try:
        from app.core.database import engine
        with engine.connect() as conn:
            logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise
    
    # Проверка подключения к Redis
    try:
        from app.utils.cache import get_redis_client
        redis_client = get_redis_client()
        redis_client.ping()
        logger.info("Redis connection successful")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    # Создание первого суперпользователя, если не существует
    try:
        from app.core.database import SessionLocal
        from app.core.security import get_password_hash
        from app.models.user import UserRole
        from app.repositories.user_repository import UserRepository

        db = SessionLocal()
        try:
            repo = UserRepository(db)
            existing = repo.get_by_email(settings.FIRST_SUPERUSER_EMAIL)
            if not existing:
                repo.create(
                    email=settings.FIRST_SUPERUSER_EMAIL,
                    hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                    full_name=settings.FIRST_SUPERUSER_FULLNAME,
                    role=UserRole.ADMIN,
                )
                logger.info(f"Created first superuser: {settings.FIRST_SUPERUSER_EMAIL}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"First superuser init skipped: {e}")

    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")


# Создание FastAPI приложения
app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    description="Backend для системы управления FBS-заказами маркетплейсов",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware (порядок важен!)
app.add_middleware(ExceptionHandlerMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS — для development разрешаем localhost, если список пуст
cors_origins = list(settings.BACKEND_CORS_ORIGINS) if settings.BACKEND_CORS_ORIGINS else []
if settings.DEBUG and not cors_origins:
    cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Authorization", "X-Request-ID"],
    )


# Health check endpoints
@app.get("/health", tags=["Health"])
async def health_check():
    """Общий health check"""
    return JSONResponse(
        content={
            "status": "healthy",
            "version": __version__,
            "environment": settings.ENVIRONMENT,
        }
    )


@app.get("/health/db", tags=["Health"])
async def health_check_db():
    """Health check базы данных"""
    try:
        from sqlalchemy import text
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "healthy"})
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)},
        )


@app.get("/health/redis", tags=["Health"])
async def health_check_redis():
    """Health check Redis"""
    try:
        from app.utils.cache import get_redis_client
        redis_client = get_redis_client()
        redis_client.ping()
        return JSONResponse(content={"status": "healthy"})
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)},
        )


@app.get("/health/marketplace/{marketplace}", tags=["Health"])
async def health_check_marketplace(
    marketplace: str,
    api_key: str | None = None,
    client_id: str | None = None,
):
    """
    Health check доступности API маркетплейса.
    
    Query params: api_key (обязательно), client_id (для Ozon).
    Возвращает status: healthy если test_connection() успешен.
    """
    if not api_key:
        return JSONResponse(
            status_code=400,
            content={
                "status": "skipped",
                "message": "api_key required (query param or X-Marketplace-Api-Key header)",
            },
        )
    
    marketplace_lower = marketplace.lower()
    
    try:
        if marketplace_lower == "ozon":
            if not client_id:
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "skipped",
                        "message": "client_id required for Ozon",
                    },
                )
            from app.services.marketplace.ozon import OzonClient
            async with OzonClient(api_key=api_key, client_id=client_id) as client:
                is_ok = await client.test_connection()
        elif marketplace_lower == "wildberries":
            from app.services.marketplace.wildberries import WildberriesClient
            async with WildberriesClient(api_key=api_key) as client:
                is_ok = await client.test_connection()
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Unknown marketplace: {marketplace}. Use 'ozon' or 'wildberries'",
                },
            )
        
        if is_ok:
            return JSONResponse(
                content={"status": "healthy", "marketplace": marketplace_lower},
            )
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "marketplace": marketplace_lower},
        )
    except Exception as e:
        logger.error(f"Marketplace health check failed ({marketplace}): {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "marketplace": marketplace_lower,
                "error": str(e),
            },
        )


# Подключение роутеров API
from app.api.v1.router import api_router
from app.config import settings

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
