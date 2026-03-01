# FBS Order Management System - Backend

Backend для системы управления FBS-заказами маркетплейсов (Ozon, Wildberries).

## Технологический стек

- **Python 3.11+**
- **FastAPI** - веб-фреймворк
- **PostgreSQL** - основная БД
- **Redis** - кэширование и очереди
- **Celery** - фоновые задачи
- **SQLAlchemy 2.0** - ORM
- **Alembic** - миграции БД

## Архитектура

Проект использует модульную слоистую архитектуру:

```
app/
├── api/            # API endpoints (Controllers)
├── services/       # Бизнес-логика
│   └── marketplace/  # ✓ Интеграции с маркетплейсами (Ozon, Wildberries)
├── repositories/   # Data Access Layer
├── models/         # SQLAlchemy модели
├── schemas/        # Pydantic схемы (DTO)
├── core/           # Ядро (database, security, exceptions)
├── tasks/          # Celery задачи
└── utils/          # Утилиты
```

Подробная документация архитектуры: [ARCHITECTURE.md](../ARCHITECTURE.md)

### Интеграции с маркетплейсами

Модуль `services/marketplace/` содержит готовые интеграции:
- **Ozon Seller API** - получение FBS заказов, этикеток
- **Wildberries Marketplace API** - получение сборочных заданий, стикеров, работа с КИЗ

Подробнее: [services/marketplace/README.md](app/services/marketplace/README.md)

## Установка

### Требования

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Poetry (для управления зависимостями)

### Установка Poetry

```bash
# Windows (PowerShell)
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -

# Linux/macOS
curl -sSL https://install.python-poetry.org | python3 -
```

### Установка зависимостей

```bash
# Установка зависимостей
poetry install

# Активация виртуального окружения
poetry shell
```

## Настройка

### 1. Создание файла .env

```bash
# Копирование примера конфигурации
cp .env.example .env
```

### 2. Генерация ключей безопасности

```python
# SECRET_KEY (минимум 32 символа)
import secrets
print(secrets.token_urlsafe(32))

# ENCRYPTION_KEY (для шифрования API ключей маркетплейсов)
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

Вставьте сгенерированные ключи в файл `.env`.

### 3. Настройка базы данных

Убедитесь, что PostgreSQL запущен и создайте базу данных:

```sql
CREATE DATABASE fbs_db;
CREATE USER fbs_user WITH PASSWORD 'fbs_password';
GRANT ALL PRIVILEGES ON DATABASE fbs_db TO fbs_user;
```

Обновите настройки подключения в `.env`.

### 4. Применение миграций

```bash
# Создание миграций
alembic revision --autogenerate -m "Initial migration"

# Применение миграций
alembic upgrade head
```

### 5. Создание первого администратора

```bash
python scripts/create_admin.py
```

## Запуск

### Разработка (локально)

```bash
# Запуск API с hot reload
uvicorn app.main:app --reload --port 8000

# В другом терминале: Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# В третьем терминале: Celery beat (планировщик)
celery -A app.tasks.celery_app beat --loglevel=info
```

Документация API будет доступна по адресу: http://localhost:8000/api/docs

### Docker Compose (рекомендуется для разработки)

```bash
# Запуск всех сервисов
docker-compose -f docker/docker-compose.dev.yml up

# Запуск в фоновом режиме
docker-compose -f docker/docker-compose.dev.yml up -d

# Просмотр логов
docker-compose -f docker/docker-compose.dev.yml logs -f

# Остановка
docker-compose -f docker/docker-compose.dev.yml down
```

### Production

```bash
# Сборка Docker образа
docker build -f docker/Dockerfile -t fbs-backend:latest .

# Запуск через docker-compose
docker-compose -f docker/docker-compose.yml up -d
```

## Тестирование

```bash
# Запуск всех тестов
pytest

# С покрытием кода
pytest --cov=app --cov-report=html

# Только unit тесты
pytest tests/unit

# Только integration тесты
pytest tests/integration
```

## Линтеры и форматирование

```bash
# Black (форматирование)
black app tests

# Ruff (линтер)
ruff check app tests

# Ruff (автоисправление)
ruff check --fix app tests

# MyPy (проверка типов)
mypy app
```

## Структура API

### Аутентификация
- `POST /api/v1/auth/login` - Вход
- `POST /api/v1/auth/refresh` - Обновление токена
- `POST /api/v1/auth/logout` - Выход

### Пользователи
- `GET /api/v1/users` - Список пользователей (admin)
- `POST /api/v1/users` - Создание пользователя (admin)
- `GET /api/v1/users/{id}` - Получение пользователя
- `PUT /api/v1/users/{id}` - Обновление пользователя
- `DELETE /api/v1/users/{id}` - Удаление пользователя (admin)

### Маркетплейсы
- `GET /api/v1/marketplaces` - Список подключений
- `POST /api/v1/marketplaces` - Добавление подключения
- `GET /api/v1/marketplaces/{id}` - Получение подключения
- `PUT /api/v1/marketplaces/{id}` - Обновление подключения
- `DELETE /api/v1/marketplaces/{id}` - Удаление подключения
- `POST /api/v1/marketplaces/{id}/sync` - Синхронизация заказов

### Заказы
- `GET /api/v1/orders` - Список заказов (с фильтрацией)
- `GET /api/v1/orders/{id}` - Получение заказа
- `POST /api/v1/orders/{id}/assign` - Взять заказ в работу
- `POST /api/v1/orders/{id}/complete` - Отметить как собранный
- `GET /api/v1/orders/search` - Поиск по артикулу

### Печать
- `GET /api/v1/printing/label/{order_id}` - Получение этикетки
- `GET /api/v1/printing/barcode/{article}` - Получение штрихкода товара

## Переменные окружения

Основные переменные (см. `.env.example` для полного списка):

| Переменная | Описание | Пример |
|------------|----------|--------|
| `DEBUG` | Режим отладки | `True` |
| `SECRET_KEY` | Секретный ключ для JWT | `your-secret-key...` |
| `ENCRYPTION_KEY` | Ключ шифрования API ключей | `fernet-key...` |
| `DATABASE_URL` | URL подключения к PostgreSQL | `postgresql://user:pass@localhost/db` |
| `REDIS_URL` | URL подключения к Redis | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Broker для Celery | `redis://localhost:6379/1` |

## Миграции базы данных

```bash
# Создание новой миграции
alembic revision --autogenerate -m "Description"

# Применение миграций
alembic upgrade head

# Откат последней миграции
alembic downgrade -1

# Просмотр истории миграций
alembic history
```

## Celery задачи

### Периодические задачи

- **Синхронизация заказов**: каждые 2 минуты
- **Очистка старых заказов**: раз в день (ночью)
- **Мониторинг подключений**: каждые 5 минут

### Запуск отдельных задач

```python
from app.tasks.sync_orders import sync_marketplace_orders

# Синхронизация заказов конкретного маркетплейса
sync_marketplace_orders.delay(marketplace_id=1)
```

## Логирование

Логи сохраняются в:
- `logs/app.log` - все логи
- `logs/error.log` - только ошибки
- `logs/celery.log` - логи Celery задач

Формат логов:
```
timestamp=2026-02-13 15:30:00 | level=INFO | logger=app.services.order | message=Order completed | trace_id=abc-123 | order_id=456
```

## Отладка

### Включение SQL логирования

В `.env`:
```
DEBUG=True
```

SQLAlchemy будет выводить все SQL запросы в консоль.

### Просмотр Redis данных

```bash
redis-cli
> KEYS *
> GET user:1
```

### Мониторинг Celery

```bash
# Инспекция workers
celery -A app.tasks.celery_app inspect active

# Статистика
celery -A app.tasks.celery_app inspect stats

# Flower (веб-интерфейс)
celery -A app.tasks.celery_app flower
```

## Troubleshooting

### Ошибка подключения к БД

```bash
# Проверка, что PostgreSQL запущен
pg_isready

# Проверка подключения
psql -U fbs_user -d fbs_db -h localhost
```

### Ошибка подключения к Redis

```bash
# Проверка, что Redis запущен
redis-cli ping

# Должен вернуть: PONG
```

### Ошибки миграций

```bash
# Откат всех миграций
alembic downgrade base

# Применение заново
alembic upgrade head
```

## Полезные ссылки

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Celery Documentation](https://docs.celeryproject.org/)
- [Poetry Documentation](https://python-poetry.org/docs/)

## Контакты и поддержка

При возникновении вопросов или проблем создавайте issue в репозитории проекта.
