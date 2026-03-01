# Архитектура Backend FBS MVP

## Обзор

Проект построен на основе **модульной слоистой архитектуры** с использованием принципов Clean Architecture и SOLID.

## Технологический стек

- **FastAPI** 0.109+ - веб-фреймворк
- **PostgreSQL** 15+ - основная БД
- **Redis** 7+ - кэширование и очереди
- **Celery** 5+ - фоновые задачи
- **SQLAlchemy** 2.0+ - ORM
- **Alembic** - миграции БД
- **Pydantic** 2+ - валидация данных
- **Poetry** - управление зависимостями

## Структура проекта

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                      # Точка входа FastAPI
│   ├── config.py                    # Настройки приложения
│   │
│   ├── core/                        # Ядро приложения
│   │   ├── __init__.py
│   │   ├── security.py              # JWT, хеширование паролей
│   │   ├── dependencies.py          # DI контейнеры
│   │   ├── exceptions.py            # Кастомные исключения
│   │   ├── middleware.py            # Middleware (логирование, CORS)
│   │   └── database.py              # Подключение к БД
│   │
│   ├── models/                      # SQLAlchemy модели
│   │   ├── __init__.py
│   │   ├── base.py                  # Базовый класс моделей
│   │   ├── user.py                  # Пользователи
│   │   ├── marketplace.py           # Подключения к маркетплейсам
│   │   ├── order.py                 # Заказы
│   │   ├── warehouse.py             # Склады
│   │   └── audit_log.py             # Логи операций
│   │
│   ├── schemas/                     # Pydantic схемы (DTO)
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── marketplace.py
│   │   ├── order.py
│   │   ├── warehouse.py
│   │   └── common.py                # Общие схемы (пагинация и т.д.)
│   │
│   ├── repositories/                # Data Access Layer (Repository Pattern)
│   │   ├── __init__.py
│   │   ├── base.py                  # Базовый репозиторий с CRUD
│   │   ├── user.py
│   │   ├── marketplace.py
│   │   ├── order.py
│   │   └── warehouse.py
│   │
│   ├── services/                    # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── auth.py                  # Аутентификация
│   │   ├── user.py                  # Управление пользователями
│   │   ├── order.py                 # Бизнес-логика заказов
│   │   ├── marketplace/             # Интеграции с маркетплейсами
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # Базовый класс интеграции
│   │   │   ├── ozon.py              # Интеграция Озон
│   │   │   └── wildberries.py       # Интеграция Wildberries
│   │   └── printing.py              # Логика печати
│   │
│   ├── api/                         # API Layer (Controllers)
│   │   ├── __init__.py
│   │   ├── deps.py                  # Зависимости для endpoints
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py            # Главный роутер API v1
│   │       ├── auth.py              # Endpoints аутентификации
│   │       ├── users.py             # Endpoints пользователей
│   │       ├── orders.py            # Endpoints заказов
│   │       ├── marketplaces.py      # Endpoints маркетплейсов
│   │       └── printing.py          # Endpoints печати
│   │
│   ├── tasks/                       # Celery задачи
│   │   ├── __init__.py
│   │   ├── celery_app.py            # Конфигурация Celery
│   │   ├── sync_orders.py           # Синхронизация заказов
│   │   └── cleanup.py               # Очистка старых данных
│   │
│   └── utils/                       # Утилиты
│       ├── __init__.py
│       ├── logger.py                # Настройка логирования
│       ├── cache.py                 # Работа с Redis
│       └── validators.py            # Кастомные валидаторы
│
├── alembic/                         # Миграции БД
│   ├── versions/
│   └── env.py
│
├── tests/                           # Тесты
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docker/                          # Docker конфигурации
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
│
├── scripts/                         # Скрипты
│   ├── init_db.py
│   └── create_admin.py
│
├── .env.example
├── .gitignore
├── pyproject.toml                   # Poetry конфигурация
├── alembic.ini
└── README.md
```

## Архитектурные слои

### 1. API Layer (Controllers)
- **Ответственность**: Обработка HTTP запросов/ответов
- **Не содержит**: Бизнес-логику
- **Взаимодействует с**: Service Layer
- **Особенности**:
  - Валидация входных данных через Pydantic
  - Авторизация через dependencies
  - Сериализация ответов

### 2. Service Layer (Business Logic)
- **Ответственность**: Бизнес-логика приложения
- **Не содержит**: Детали работы с БД или HTTP
- **Взаимодействует с**: Repository Layer, внешние API
- **Особенности**:
  - Транзакционность
  - Валидация бизнес-правил
  - Оркестрация между репозиториями
  - Интеграции с маркетплейсами

### 3. Repository Layer (Data Access)
- **Ответственность**: Работа с базой данных
- **Не содержит**: Бизнес-логику
- **Взаимодействует с**: Models (SQLAlchemy)
- **Особенности**:
  - CRUD операции
  - Сложные запросы с фильтрацией
  - Паттерн Unit of Work для транзакций

### 4. Models Layer
- **Ответственность**: Определение структуры БД
- **Особенности**:
  - SQLAlchemy ORM модели
  - Связи между таблицами
  - Constraints и индексы

### 5. Schemas Layer (DTO)
- **Ответственность**: Валидация и сериализация данных
- **Особенности**:
  - Pydantic модели для API
  - Input/Output схемы
  - Автоматическая документация Swagger

## Паттерны проектирования

### Repository Pattern
```python
# Абстракция работы с данными
class BaseRepository:
    def get(self, id: int)
    def get_multi(self, skip: int, limit: int)
    def create(self, obj_in: Schema)
    def update(self, id: int, obj_in: Schema)
    def delete(self, id: int)
```

### Dependency Injection
```python
# Внедрение зависимостей через FastAPI
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/orders")
async def get_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ...
```

### Service Layer Pattern
```python
# Изоляция бизнес-логики
class OrderService:
    def __init__(
        self,
        order_repo: OrderRepository,
        marketplace_service: MarketplaceService
    ):
        self.order_repo = order_repo
        self.marketplace_service = marketplace_service
    
    def complete_order(self, order_id: int, user_id: int):
        # Бизнес-логика
        order = self.order_repo.get(order_id)
        order.status = OrderStatus.COMPLETED
        order.completed_by = user_id
        order.completed_at = datetime.now()
        
        # Синхронизация с маркетплейсом
        self.marketplace_service.update_order_status(order)
        
        return self.order_repo.update(order)
```

### Strategy Pattern (для маркетплейсов)
```python
# Абстрактный интерфейс интеграции
class BaseMarketplaceClient(ABC):
    @abstractmethod
    def get_orders(self) -> List[Order]: ...
    
    @abstractmethod
    def get_label(self, order_id: str) -> bytes: ...
    
    @abstractmethod
    def update_status(self, order_id: str, status: str): ...

# Конкретные реализации
class OzonClient(BaseMarketplaceClient):
    def get_orders(self): ...
    
class WildberriesClient(BaseMarketplaceClient):
    def get_orders(self): ...
```

## Модель данных

### Основные сущности

#### User (Пользователи)
- id (PK)
- email (unique)
- hashed_password
- full_name
- role (admin/packer)
- is_active
- created_at, updated_at

#### Marketplace (Подключения к маркетплейсам)
- id (PK)
- user_id (FK -> User)
- type (ozon/wildberries)
- name (пользовательское название)
- api_key (encrypted)
- client_id
- warehouse_id
- warehouse_color (HEX)
- is_kiz_enabled (для WB)
- is_active
- last_sync_at
- created_at, updated_at

#### Order (Заказы)
- id (PK)
- marketplace_id (FK -> Marketplace)
- external_id (уникальный ID в маркетплейсе)
- posting_number (номер отправления)
- article (артикул товара)
- product_name
- quantity
- warehouse_name
- status (awaiting_packaging/packaging/completed/cancelled)
- marketplace_status (оригинальный статус из API)
- created_at (дата создания в маркетплейсе)
- assigned_at (когда взят в работу)
- completed_at (когда собран)
- assigned_to (FK -> User, кто собирает)
- completed_by (FK -> User, кто собрал)
- kiz_code (КИЗ для Wildberries)
- metadata (JSONB - дополнительные данные)
- updated_at

#### AuditLog (Логи операций)
- id (PK)
- user_id (FK -> User)
- action (login/logout/order_completed/etc)
- entity_type (order/user/marketplace)
- entity_id
- changes (JSONB - что изменилось)
- ip_address
- user_agent
- created_at

### Индексы для оптимизации
```sql
-- Быстрый поиск по артикулу
CREATE INDEX idx_orders_article ON orders(article);

-- Фильтрация по статусу и маркетплейсу
CREATE INDEX idx_orders_status_marketplace ON orders(status, marketplace_id);

-- Поиск активных заказов
CREATE INDEX idx_orders_active ON orders(status) WHERE status IN ('awaiting_packaging', 'packaging');

-- Составной индекс для сортировки
CREATE INDEX idx_orders_created_status ON orders(created_at DESC, status);
```

## Безопасность

### Аутентификация
- JWT токены (access token + refresh token)
- Access token: срок жизни 15 минут
- Refresh token: срок жизни 7 дней
- Хранение refresh token в HttpOnly cookies

### Авторизация
- Role-Based Access Control (RBAC)
- Middleware для проверки прав
- Декораторы для endpoints

### Защита данных
- Шифрование API ключей (Fernet)
- Хеширование паролей (bcrypt)
- Параметризованные запросы (защита от SQL injection)
- Rate limiting (slowapi)
- CORS настройки
- HTTPS only в production

## Кэширование (Redis)

### Стратегии кэширования
1. **Список заказов**: cache-aside, TTL 30 сек
2. **Настройки маркетплейсов**: cache-aside, TTL 5 мин
3. **Данные пользователя**: cache-aside, TTL 10 мин
4. **Результаты поиска**: cache-aside, TTL 1 мин

### Инвалидация кэша
- При изменении данных - удаление кэша
- При ошибках API - сохранение старых данных
- Pattern для ключей: `{entity}:{id}:{field}`

## Фоновые задачи (Celery)

### Периодические задачи
1. **Синхронизация заказов**
   - Частота: каждые 2 минуты
   - Для каждого активного маркетплейса
   - С обработкой ошибок и retry

2. **Очистка старых заказов**
   - Частота: раз в день (ночью)
   - Архивация старых данных (> 30 дней)

3. **Мониторинг подключений**
   - Частота: каждые 5 минут
   - Проверка доступности API маркетплейсов

### Обработка ошибок
- Retry с экспоненциальной задержкой
- Max retries: 3
- Dead letter queue для failed задач

## Логирование

### Уровни логов
- **DEBUG**: детальная информация для разработки
- **INFO**: общий ход работы
- **WARNING**: предупреждения (лимиты API и т.д.)
- **ERROR**: ошибки с stacktrace
- **CRITICAL**: критические ошибки

### Структура логов
```json
{
  "timestamp": "2026-02-13T15:30:00Z",
  "level": "INFO",
  "logger": "app.services.marketplace.ozon",
  "message": "Synchronized 15 orders",
  "context": {
    "marketplace_id": 123,
    "orders_count": 15,
    "duration_ms": 450
  },
  "trace_id": "abc-123-def"
}
```

### Логирование в файлы
- `app.log` - общий лог
- `error.log` - только ошибки
- `celery.log` - логи фоновых задач
- `access.log` - HTTP запросы

## Мониторинг и метрики

### Prometheus метрики
- Количество запросов (по endpoint)
- Время ответа (percentiles: 50, 95, 99)
- Количество активных соединений с БД
- Размер очереди Celery
- Количество успешных/неудачных синхронизаций

### Health checks
- `/health` - общее здоровье приложения
- `/health/db` - доступность БД
- `/health/redis` - доступность Redis
- `/health/celery` - статус Celery workers

## Масштабирование

### Горизонтальное масштабирование
- Stateless API серверы (можно запускать N инстансов)
- Shared Redis для кэша и сессий
- Shared PostgreSQL
- Балансировщик нагрузки (Nginx)

### Вертикальное масштабирование
- Connection pooling для БД (20-50 соединений)
- Async operations где возможно
- Оптимизация запросов (eager loading, индексы)

### Производительность
- До 500 заказов/день: 1 инстанс
- До 5000 заказов/день: 2-3 инстанса + Read Replica БД
- Более 5000: sharding БД + кластер Redis

## Deployment

### Docker контейнеры
1. **api** - FastAPI приложение (можно несколько)
2. **celery-worker** - обработчик задач (можно несколько)
3. **celery-beat** - планировщик (один)
4. **postgres** - БД
5. **redis** - кэш и очереди
6. **nginx** - reverse proxy

### CI/CD
1. Git push в main
2. Запуск тестов
3. Сборка Docker образов
4. Деплой на сервер
5. Health check
6. Rollback при ошибках

## Тестирование

### Unit тесты
- Тестирование сервисов изолированно
- Мокирование репозиториев и внешних API
- Coverage > 80%

### Integration тесты
- Тестирование API endpoints
- Использование тестовой БД
- Проверка интеграций с маркетплейсами (с моками)

### E2E тесты
- Критические пользовательские сценарии
- Запуск в docker-compose окружении

## Дебаг и разработка

### Удобство отладки
1. **Подробные логи** с trace_id для отслеживания
2. **Swagger UI** для тестирования API
3. **SQL логирование** в dev режиме
4. **Hot reload** FastAPI в dev
5. **Debug toolbar** для профилирования
6. **Sentry** для отслеживания ошибок в production

### Локальная разработка
```bash
# Запуск всех сервисов
docker-compose -f docker-compose.dev.yml up

# Только БД и Redis для локальной разработки API
docker-compose -f docker-compose.dev.yml up postgres redis

# Запуск API локально с hot reload
poetry run uvicorn app.main:app --reload --port 8000

# Celery worker
poetry run celery -A app.tasks.celery_app worker --loglevel=info

# Celery beat
poetry run celery -A app.tasks.celery_app beat --loglevel=info
```

## Лучшие практики

### Код
- Type hints везде
- Docstrings для публичных функций/классов
- Линтеры: ruff, mypy
- Форматтер: black
- Pre-commit hooks

### Коммиты
- Conventional Commits формат
- Линейная история (rebase вместо merge)

### Безопасность
- Secrets в переменных окружения
- Регулярное обновление зависимостей
- Сканирование уязвимостей (safety, bandit)

### Производительность
- N+1 query detection
- Connection pooling
- Async где нужно
- Индексы на часто запрашиваемые поля

## Будущие улучшения

### Версия 1.1
- GraphQL API (альтернатива REST)
- WebSocket для real-time обновлений
- Advanced аналитика

### Версия 2.0
- Микросервисная архитектура
- Event-driven архитектура (RabbitMQ/Kafka)
- CQRS pattern для сложных запросов
