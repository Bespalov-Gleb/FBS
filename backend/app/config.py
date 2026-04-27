"""
Конфигурация приложения
"""
import json
import os
from typing import List, Optional

from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "FBS Order Management System"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    DEV_AUTH_BYPASS: bool = False

    # API
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: List[str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Парсинг CORS origins"""
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return v
        return []

    # Security
    SECRET_KEY: str = "test-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: str = "8O_9cAwoS1hXb3W4_uJ86vr0HwgH0OXunrywgTbcv_U="  # Fernet key

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "fbs_user"
    POSTGRES_PASSWORD: str = "fbs_password"
    POSTGRES_DB: str = "fbs_db"
    DATABASE_URL: Optional[str] = None
    TESTING: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info) -> str:
        """Сборка DATABASE_URL из компонентов"""
        if isinstance(v, str) and v:
            return v
        values = info.data
        if os.environ.get("TESTING") == "1":
            return "sqlite:///:memory:"
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=values.get("POSTGRES_USER"),
                password=values.get("POSTGRES_PASSWORD"),
                host=values.get("POSTGRES_SERVER"),
                port=values.get("POSTGRES_PORT"),
                path=f"/{values.get('POSTGRES_DB') or 'fbs_db'}",
            )
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: Optional[RedisDsn] = None

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def assemble_redis_connection(cls, v: Optional[str], info) -> str:
        """Сборка REDIS_URL из компонентов"""
        if isinstance(v, str) and v:
            return v
        
        values = info.data
        password = values.get("REDIS_PASSWORD")
        auth = f":{password}@" if password else ""
        
        return f"redis://{auth}{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE_PATH: str = "logs/app.log"

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # Marketplaces API
    OZON_API_URL: str = "https://api-seller.ozon.ru"
    # Док. Ozon: лимиты по ключу; фактически 429 «per second» — держим низкий общий поток
    OZON_RATE_LIMIT: int = 20  # ориентир из доки (не используется как жёсткий счётчик)

    # Ozon: Redis — один интервал между ЛЮБЫМИ запросами на Client-Id (все процессы)
    OZON_REDIS_PACE_ENABLED: bool = True
    OZON_REDIS_PACE_MS: int = 380
    OZON_REDIS_PACE_SPIN_CAP_SEC: float = 90.0

    # Ozon: реже звать /v1/warehouse/list (список складов меняется редко)
    OZON_WAREHOUSE_SYNC_CACHE_SEC: int = 900

    WILDBERRIES_API_URL: str = "https://suppliers-api.wildberries.ru"
    WILDBERRIES_STATISTICS_URL: str = "https://statistics-api.wildberries.ru"
    WILDBERRIES_RATE_LIMIT: int = 100  # requests per minute

    # First superuser
    FIRST_SUPERUSER_EMAIL: str = "admin@fbs.example"
    FIRST_SUPERUSER_PASSWORD: str = "admin123"
    FIRST_SUPERUSER_FULLNAME: str = "System Administrator"

    # Monitoring
    SENTRY_DSN: Optional[str] = None
    ENABLE_PROMETHEUS: bool = False

    # Cache TTL (seconds)
    CACHE_TTL_ORDERS: int = 30
    CACHE_TTL_MARKETPLACES: int = 300
    CACHE_TTL_USER: int = 600
    CACHE_TTL_SEARCH: int = 60

    @property
    def database_url_sync(self) -> str:
        """Синхронный URL для SQLAlchemy"""
        return str(self.DATABASE_URL)

    @property
    def is_development(self) -> bool:
        """Проверка, что окружение - development"""
        return self.ENVIRONMENT.lower() in ("development", "dev", "local")

    @property
    def is_production(self) -> bool:
        """Проверка, что окружение - production"""
        return self.ENVIRONMENT.lower() in ("production", "prod")


# Singleton экземпляр настроек
settings = Settings()
