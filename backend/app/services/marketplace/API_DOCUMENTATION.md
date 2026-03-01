# Документация API маркетплейсов

Этот документ содержит ссылки на официальную документацию API маркетплейсов, которая использовалась при разработке интеграций.

## Wildberries API

### Официальная документация
- **Главная страница**: https://dev.wildberries.ru/
- **FBS Orders (сборочные задания)**: https://dev.wildberries.ru/docs/openapi/orders-fbs
- **English version**: https://dev.wildberries.ru/en/openapi/orders-fbs

### Ключевые endpoints

#### Получение сборочных заданий
```
GET https://marketplace-api.wildberries.ru/api/v3/orders/new
```
Возвращает список всех новых сборочных заданий (статус `new`).

**Response format:**
```json
{
  "orders": [
    {
      "id": 13833711,
      "rid": "f884001e44e511edb8780242ac120002",
      "orderUid": "165918930_629fbc924b984618a44354475ca58675",
      "article": "one-ring-7548",
      "colorCode": "RAL 3017",
      "nmId": 123456789,
      "chrtId": 987654321,
      "warehouseId": 658434,
      "officeId": 123,
      "price": 1014,
      "finalPrice": 1014,
      "createdAt": "2022-05-04T07:56:29Z",
      "offices": ["Калуга"],
      "skus": ["6665956397512"],
      "requiredMeta": ["uin"],
      "optionalMeta": ["sgtin"],
      "deliveryType": "fbs",
      ...
    }
  ]
}
```

#### Получение стикеров
```
POST https://marketplace-api.wildberries.ru/api/v3/orders/stickers?type=svg&width=58&height=40
```
Возвращает стикеры для указанных сборочных заданий.

**Request body:**
```json
{
  "orders": [5346346]
}
```

**Response:**
```json
{
  "stickers": [
    {
      "orderId": 5346346,
      "partA": 231648,
      "partB": 9753,
      "barcode": "!uKEtQZVx",
      "file": "base64_encoded_data..."
    }
  ]
}
```

#### Добавление КИЗ (Data Matrix код)
```
PUT https://marketplace-api.wildberries.ru/api/v3/orders/{orderId}/meta/sgtin
```
Прикрепляет код маркировки Честный ЗНАК к сборочному заданию.

**Request body:**
```json
{
  "sgtins": ["1234567890123456"]
}
```

#### Отмена заказа
```
PATCH https://marketplace-api.wildberries.ru/api/v3/orders/{orderId}/cancel
```

### Статусы сборочных заданий

**supplierStatus** (статус со стороны продавца):
- `new` - Новый заказ
- `confirm` - В сборке (добавлен в поставку)
- `complete` - В доставке (поставка передана)
- `cancel` - Отменен продавцом

**wbStatus** (статус со стороны Wildberries):
- `waiting` - Подтвержден, WB еще не получил
- `sorted` - Отсортирован на складе WB
- `sold` - Продан
- `canceled` - Отменен продавцом
- `canceled_by_client` - Отменен покупателем при получении
- `declined_by_client` - Отменен покупателем в первый час
- `defect` - Отменен из-за брака
- `ready_for_pickup` - На ПВЗ, ожидает клиента

### Авторизация
- **Header**: `Authorization: <token>`
- Токен создается в личном кабинете продавца в категории **Marketplace**

### Rate Limits
- FBS assembly orders, supplies and passes: 300 requests per minute (200ms interval, burst 20)

---

## Ozon Seller API

### Официальная документация
- **Главная страница**: https://docs.ozon.ru/api/seller/
- **GitHub библиотека**: https://github.com/irenicaa/ozon-seller
- **PyPI пакет**: https://pypi.org/project/ozon-seller/

### Ключевые endpoints

#### Получение списка FBS заказов
```
POST https://api-seller.ozon.ru/v3/posting/fbs/list
```
Возвращает список FBS отправлений.

**Request body:**
```json
{
  "dir": "ASC",
  "filter": {
    "status": "awaiting_packaging",
    "warehouse_id": [123],
    "since": "2024-01-01T00:00:00Z",
    "to": "2024-01-31T23:59:59Z"
  },
  "limit": 1000,
  "offset": 0,
  "with": {
    "analytics_data": false,
    "barcodes": false,
    "financial_data": false,
    "translit": false
  }
}
```

**Response format:**
```json
{
  "result": {
    "postings": [
      {
        "order_id": 12345678,
        "order_number": "12345678-0001",
        "posting_number": "12345678-0001-1",
        "status": "awaiting_packaging",
        "products": [
          {
            "offer_id": "article-123",
            "name": "Product Name",
            "sku": 123456789,
            "quantity": 1,
            "price": "1000.00"
          }
        ],
        "delivery_method": {
          "id": 123,
          "name": "Method name",
          "warehouse": "Warehouse name",
          "warehouse_id": 456
        },
        "in_process_at": "2024-01-15T10:00:00Z",
        "tracking_number": "TRACK123",
        ...
      }
    ],
    "has_next": false
  }
}
```

#### Получение деталей заказа
```
POST https://api-seller.ozon.ru/v3/posting/fbs/get
```
Возвращает подробную информацию о конкретном отправлении.

**Request body:**
```json
{
  "posting_number": "12345678-0001-1",
  "with": {
    "analytics_data": true,
    "barcodes": true,
    "financial_data": true
  }
}
```

#### Получение этикетки
```
POST https://api-seller.ozon.ru/v2/posting/fbs/package-label
```
Возвращает этикетку для печати (PDF в Base64).

**Request body:**
```json
{
  "posting_number": ["12345678-0001-1"]
}
```

### Статусы FBS заказов

Основные статусы:
- `awaiting_packaging` - Ожидает упаковки
- `awaiting_deliver` - Ожидает отгрузки (упакован)
- `delivering` - В доставке
- `delivered` - Доставлен
- `cancelled` - Отменен

### Авторизация
- **Header**: `Client-Id: <client_id>`
- **Header**: `Api-Key: <api_key>`

Client-Id и Api-Key получаются в личном кабинете Ozon Seller в разделе "API Keys".

### Пагинация
Используется offset/limit:
- `limit`: максимум записей за запрос (до 1000)
- `offset`: смещение для пагинации
- `has_next`: флаг наличия следующей страницы

---

## Ozon Seller API

### Официальная документация
- **Главная**: https://docs.ozon.ru/api/seller/
- **Python библиотека**: https://github.com/irenicaa/ozon-seller
- **Open Integrations**: https://en.openintegrations.dev/docs/Instructions/Ozon

### Ключевые endpoints

#### Получение FBS заказов
```
POST https://api-seller.ozon.ru/v3/posting/fbs/list
```
**Request:** filter (status, warehouse_id, since, to), limit, offset

**Статусы**: awaiting_packaging, awaiting_approve, **awaiting_deliver**, delivering, delivered, cancelled

#### Детали заказа + штрихкоды
```
POST https://api-seller.ozon.ru/v3/posting/fbs/get
```
**Request:** posting_number, with.barcodes=true

**Response:** upper_barcode, lower_barcode для печати

#### Этикетка FBS (PDF)
```
POST https://api-seller.ozon.ru/v2/posting/fbs/package-label
```
**Request:** posting_number: ["..."]
**Response:** Binary PDF

#### Подтверждение отгрузки
```
POST https://api-seller.ozon.ru/v3/posting/fbs/ship
```
**Request:** posting_number, packages[products]

#### Список складов
```
POST https://api-seller.ozon.ru/v1/warehouse/list
```

### Авторизация
- **Header**: Client-Id, Api-Key

Подробнее: [API_DOCUMENTATION_OZON.md](./API_DOCUMENTATION_OZON.md)

---

## Общие рекомендации

### Обработка ошибок
- Всегда проверяйте HTTP статус код
- Логируйте детали ошибок для отладки
- Используйте retry с экспоненциальной задержкой для временных ошибок (5xx, network issues)

### Rate Limiting
- Соблюдайте лимиты запросов
- Реализуйте exponential backoff при получении 429 (Too Many Requests)
- Кэшируйте данные где возможно

### Безопасность
- Храните API ключи зашифрованными в БД
- Никогда не логируйте API ключи в открытом виде
- Используйте HTTPS для всех запросов

### Мониторинг
- Логируйте все API вызовы с временем выполнения
- Отслеживайте rate limits
- Мониторьте ошибки и неуспешные запросы

---

## Полезные ссылки

### Wildberries
- Developer Portal: https://dev.wildberries.ru/
- Telegram канал с обновлениями: https://t.me/wb_api_notifications
- Business Solutions: https://dev.wildberries.ru/business-solutions

### Ozon
- Seller Portal: https://seller.ozon.ru/
- API Documentation: https://docs.ozon.ru/api/seller/
- Python библиотека: https://github.com/irenicaa/ozon-seller

---

## История изменений

- **2026-02-13**: Начальная версия на основе официальной документации
  - Wildberries API: документация от dev.wildberries.ru
  - Ozon API: документация от docs.ozon.ru и библиотека ozon-seller

## Примечания

Вся информация взята из официальных источников и актуальна на момент разработки (февраль 2026).
При возникновении расхождений всегда обращайтесь к официальной документации маркетплейсов.
