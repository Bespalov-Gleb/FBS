"""
Pytest fixtures для тестов FBS backend
"""
import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from unittest.mock import MagicMock, patch

# Установить TESTING до импорта app
os.environ["TESTING"] = "1"
os.environ.setdefault("SECRET_KEY", "test-secret-key-32-chars-long!!!")
os.environ.setdefault("ENCRYPTION_KEY", "8O_9cAwoS1hXb3W4_uJ86vr0HwgH0OXunrywgTbcv_U=")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

from app.core.database import Base, engine, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models import audit_log, marketplace, order, print_settings, user, warehouse  # noqa: F401
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

# Используем engine приложения (sqlite при TESTING=1)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)




@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Свежая сессия БД для каждого теста"""
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """TestClient с переопределённой БД и замоканным Redis.
    Используем db_session напрямую — гарантирует доступ к таблицам и данным."""
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.utils.cache.get_redis_client") as mock_redis:
        mock_redis.return_value.ping.return_value = True
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def packer_user(db_session: Session) -> User:
    """Пользователь-упаковщик"""
    repo = UserRepository(db_session)
    user = repo.create(
        email="packer@test.com",
        hashed_password=get_password_hash("password123"),
        full_name="Test Packer",
        role=UserRole.PACKER,
    )
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session: Session) -> User:
    """Администратор"""
    repo = UserRepository(db_session)
    user = repo.create(
        email="admin@test.com",
        hashed_password=get_password_hash("admin123"),
        full_name="Test Admin",
        role=UserRole.ADMIN,
    )
    db_session.commit()
    return user


@pytest.fixture
def packer_headers(packer_user: User) -> dict:
    """Authorization header для packer"""
    token = create_access_token(subject=str(packer_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user: User) -> dict:
    """Authorization header для admin"""
    token = create_access_token(subject=str(admin_user.id))
    return {"Authorization": f"Bearer {token}"}
