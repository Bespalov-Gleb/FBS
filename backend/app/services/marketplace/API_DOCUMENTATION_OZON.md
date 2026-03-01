# Документация Ozon Seller API

## Источники

- **Официальная документация**: https://docs.ozon.ru/api/seller/
- **Python библиотека**: https://github.com/irenicaa/ozon-seller
- **Open Integrations**: https://en.openintegrations.dev/docs/Instructions/Ozon

## Авторизация

```
Header: Client-Id: <client_id>
Header: Api-Key: <api_key>
Header: Content-Type: application/json
```

Получение: Ozon Seller → Настройки → API Keys

## Endpoints

### 1. POST /v3/posting/fbs/unfulfilled/list
**Список необработанных отправлений** (официальная док. docs.ozon.ru)

Период — не больше 1 года. Фильтр: **cutoff_from/cutoff_to** (время сборки) ИЛИ **delivering_date_from/delivering_date_to**. Нельзя использовать оба вместе.

**Request:**
```json
{
  "dir": "asc",
  "filter": {
    "cutoff_from": "2024-01-01T00:00:00.000Z",
    "cutoff_to": "2024-01-31T23:59:59.000Z"
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

**Response:**
```json
{
  "result": {
    "postings": [...],
    "has_next": false
  }
}
```

**Статусы filter.status:**
- `awaiting_packaging` - Ожидает упаковки
- `awaiting_approve` - Ожидает подтверждения
- `awaiting_deliver` - **Ожидает отгрузки** (для ТЗ)
- `delivering` - В доставке
- `delivered` - Доставлен
- `cancelled` - Отменен

### 2. POST /v3/posting/fbs/get
**Детали заказа + штрихкоды**

**Request:**
```json
{
  "posting_number": "12345-0001-1",
  "with": {
    "analytics_data": false,
    "barcodes": true,
    "financial_data": false,
    "translit": false
  }
}
```

**Response (result):**
```json
{
  "posting_number": "12345-0001-1",
  "order_id": 12345678,
  "status": "awaiting_deliver",
  "products": [
    {
      "offer_id": "article-123",
      "name": "Product Name",
      "sku": 123456789,
      "quantity": 1
    }
  ],
  "barcodes": {
    "upper_barcode": "2000000000000",
    "lower_barcode": "2000000000001"
  },
  "delivery_method": {
    "warehouse": "Warehouse Name",
    "warehouse_id": 456
  }
}
```

### 3. POST /v2/posting/fbs/package-label
**Этикетка FBS (PDF)**

**Request:**
```json
{
  "posting_number": ["12345-0001-1"]
}
```

**Response:** Binary PDF (Content-Type: application/pdf)

### 4. POST /v3/posting/fbs/ship
**Подтверждение отгрузки**

**Request:**
```json
{
  "posting_number": "12345-0001-1",
  "packages": [
    {
      "products": [
        {
          "product_id": 123456789,
          "quantity": 1,
          "exemplar_info": [
            {
              "is_gtd_absent": true
            }
          ]
        }
      ]
    }
  ]
}
```

**С маркировкой:**
```json
{
  "exemplar_info": [
    {
      "mandatory_mark": "01046007880063502115110410ab-cd-ef",
      "is_gtd_absent": false
    }
  ]
}
```

### 5. POST /v3/product/info/list
**Информация о товарах (в т.ч. фото)**

Request: `{ "offer_id": ["article1", "article2"] }` или `{ "product_id": [id1, id2] }` или `{ "sku": [sku1, sku2] }`

Response: `result.items[]` с полями `primary_image` (URL главного фото), `images`, `images360`, `color_image`.

### 6. POST /v1/warehouse/list
**Список складов**

**Request:** `{}`

**Response:**
```json
{
  "result": [
    {
      "warehouse_id": 123,
      "name": "Warehouse Name"
    }
  ]
}
```

## Workflow для вкладки "Сборка"

1. `get_orders_awaiting_deliver()` - заказы "Ожидают отгрузки"
2. `get_order_label()` - PDF этикетка
3. `get_posting_details(with_barcodes=true)` - штрихкоды товара
4. `ship_posting()` - подтверждение "Собрано"

## Rate Limits

Согласно документации Ozon: ~20 запросов в секунду на аккаунт.

## Отличия от Wildberries

| Аспект | Ozon | Wildberries |
|--------|------|-------------|
| Статус для "Сборка" | awaiting_deliver | new, confirm |
| Маркировка | mandatory_mark | КИЗ (sgtin) |
| Подтверждение | ship (один запрос) | supply + deliver |
| Этикетка | PDF | SVG/PNG |
| Пагинация | offset/limit | cursor |
