# Модуль интеграций с маркетплейсами

Этот модуль предоставляет унифицированный интерфейс для работы с API различных маркетплейсов.

## Структура

```
marketplace/
├── __init__.py                 # Экспорты модуля
├── base.py                     # Базовый абстрактный класс
├── ozon.py                     # Клиент для Ozon Seller API
├── wildberries.py              # Клиент для Wildberries Marketplace API
├── API_DOCUMENTATION.md        # Подробная документация API
└── README.md                   # Этот файл
```

## Использование

### Ozon Client

```python
from app.services.marketplace import OzonClient

# Инициализация клиента
client = OzonClient(
    api_key="your-api-key",
    client_id="your-client-id",
    timeout=30,
)

# Получение FBS заказов в статусе "awaiting_packaging"
orders = await client.get_orders(
    status="awaiting_packaging",
    warehouse_id="123",
)

# Получение этикетки заказа
label_pdf = await client.get_order_label(posting_number="12345-0001-1")

# Закрытие клиента
await client.close()
```

### Wildberries Client

```python
from app.services.marketplace import WildberriesClient

# Инициализация клиента
client = WildberriesClient(
    api_key="your-marketplace-token",
    timeout=30,
)

# Получение новых сборочных заданий
orders = await client.get_orders()

# Получение стикера заказа
sticker = await client.get_order_label(
    order_id="13833711",
    sticker_type="svg",
    width=58,
    height=40,
)

# Добавление КИЗ кода
await client.add_kiz_code(
    order_id="13833711",
    kiz_code="01234567890123",
)

# Отмена заказа
await client.update_order_status(
    order_id="13833711",
    status=OrderStatus.CANCELLED,
)

# Закрытие клиента
await client.close()
```

## Унифицированный формат данных

Все клиенты возвращают заказы в едином формате `MarketplaceOrder`:

```python
@dataclass
class MarketplaceOrder:
    external_id: str              # ID в маркетплейсе
    posting_number: str           # Номер отправления
    article: str                  # Артикул товара
    product_name: str             # Название товара
    quantity: int                 # Количество
    warehouse_name: Optional[str] # Название склада
    status: str                   # Статус (унифицированный)
    created_at: Optional[datetime]# Дата создания
    metadata: dict[str, Any]      # Доп. данные (специфичные для MP)
```

## Статусы заказов

Модуль использует унифицированные статусы:

```python
class OrderStatus(str, Enum):
    AWAITING_PACKAGING = "awaiting_packaging"  # Ожидает упаковки
    PACKAGING = "packaging"                    # В процессе упаковки
    COMPLETED = "completed"                    # Собран
    CANCELLED = "cancelled"                    # Отменен
```

Маппинг статусов маркетплейсов в общий формат происходит автоматически.

## Обработка ошибок

Все клиенты выбрасывают `MarketplaceAPIException` при ошибках:

```python
from app.core.exceptions import MarketplaceAPIException

try:
    orders = await client.get_orders()
except MarketplaceAPIException as e:
    print(f"Ошибка API {e.marketplace}: {e.message}")
    print(f"Детали: {e.detail}")
```

## Логирование

Все операции логируются с использованием структурированного логирования:

```python
logger.info(
    "Fetching orders from marketplace",
    extra={
        "marketplace": "ozon",
        "status": "awaiting_packaging",
    },
)
```

## Async Context Manager

Рекомендуется использовать клиенты через async context manager:

```python
async with OzonClient(api_key="...", client_id="...") as client:
    orders = await client.get_orders()
    # client.close() вызовется автоматически
```

*Примечание: Реализация `__aenter__` и `__aexit__` будет добавлена позже.*

## Расширение функциональности

Для добавления нового маркетплейса:

1. Создайте класс, наследующий `BaseMarketplaceClient`
2. Реализуйте абстрактные методы:
   - `base_url` - базовый URL API
   - `marketplace_name` - название маркетплейса
   - `_get_headers()` - заголовки для авторизации
   - `get_orders()` - получение заказов
   - `get_order_label()` - получение этикетки
   - `update_order_status()` - обновление статуса
3. Добавьте маппинг статусов в `_map_*_status_to_common()`
4. Экспортируйте класс в `__init__.py`

## Тестирование

```bash
# Unit тесты
pytest tests/unit/services/marketplace/

# Integration тесты (требуются реальные API ключи)
pytest tests/integration/services/marketplace/
```

## Документация API

Подробная документация по endpoints и форматам данных находится в [API_DOCUMENTATION.md](./API_DOCUMENTATION.md).

## Лицензия

Использование API маркетплейсов регулируется их пользовательскими соглашениями:
- Ozon: https://seller.ozon.ru/legal/offer/
- Wildberries: https://seller.wildberries.ru/supplier-agreement

## Обновления

При изменении API маркетплейсов:
1. Проверьте официальную документацию
2. Обновите клиенты согласно изменениям
3. Обновите `API_DOCUMENTATION.md`
4. Добавьте запись в changelog
