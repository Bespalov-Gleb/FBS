# План реализации интеграции Ozon

## Анализ требований из ТЗ

### Функциональность "Вкладка Сборка"
- [x] Получение заказов в статусе "Ожидают отгрузки" (`awaiting_deliver`)
- [x] Печать этикеток (штрихкод товара + FBS штрихкод)
- [ ] Отметка заказа как "Собрано" (подтверждение отгрузки)

**Примечание**: КИЗ - только для Wildberries. Ozon использует mandatory_mark для маркировки.

### Функциональность "Вкладка Маркетплейсы"
- [ ] Тестирование подключения
- [x] Ручная синхронизация заказов
- [ ] Список складов (для настроек цветов)

## План методов для OzonClient

### Источники документации
- https://docs.ozon.ru/api/seller/
- https://github.com/irenicaa/ozon-seller (официальная Python библиотека)
- https://en.openintegrations.dev/docs/Instructions/Ozon

### Endpoints Ozon Seller API

| Endpoint | Метод | Назначение |
|----------|-------|------------|
| POST /v3/posting/fbs/list | get_orders | Список FBS заказов |
| POST /v3/posting/fbs/get | get_posting_details | Детали заказа + штрихкоды |
| POST /v2/posting/fbs/package-label | get_order_label | Этикетка FBS (PDF) |
| POST /v3/posting/fbs/ship | ship_posting | Подтверждение отгрузки |
| POST /v1/warehouse/list | get_warehouses | Список складов |

### Статусы Ozon FBS
- `awaiting_packaging` - Ожидает упаковки
- `awaiting_approve` - Ожидает подтверждения
- `awaiting_deliver` - **Ожидает отгрузки** (для вкладки "Сборка")
- `delivering` - В доставке
- `delivered` - Доставлен
- `cancelled` - Отменен

### Авторизация
- Header: `Client-Id`
- Header: `Api-Key`

## Реализуемые методы

### 1. get_orders() / get_orders_awaiting_deliver() ✅
**Endpoint**: POST /v3/posting/fbs/list

**Filter**:
- status: "awaiting_deliver" (для ТЗ)
- warehouse_id: [int]
- since, to: ISO datetime

**Пагинация**: offset, limit (max 1000), has_next

### 2. get_posting_details() ✅
**Endpoint**: POST /v3/posting/fbs/get

**Request**: {"posting_number": "...", "with": {"barcodes": true}}

**Response**: Полные данные + barcodes (upper_barcode, lower_barcode) для печати штрихкода товара

### 3. get_order_label() ✅
**Endpoint**: POST /v2/posting/fbs/package-label

**Request**: {"posting_number": ["..."]}

**Response**: PDF bytes (raw content)

### 4. ship_posting() ✅
**Endpoint**: POST /v3/posting/fbs/ship

**Request**: packages с products, exemplar_info для маркировки

**Назначение**: Подтверждение отгрузки ("Собрано")

### 5. get_warehouses() ✅
**Endpoint**: POST /v1/warehouse/list

**Response**: Список складов компании

### 6. test_connection() ✅
Проверка валидности Client-Id + Api-Key

## Workflow сборки заказа в Ozon

```
1. Заказ в статусе awaiting_deliver (Ожидает отгрузки)
   ↓
2. Получить через get_orders(status="awaiting_deliver")
   ↓
3. Упаковщик берет в работу:
   - Печатает FBS этикетку get_order_label()
   - Печатает штрихкод товара из get_posting_details().barcodes
   ↓
4. Подтвердить отгрузку ship_posting()
   (статус меняется: awaiting_deliver → delivering)
   ↓
5. Готово! Заказ в доставке
```

## Отличия от Wildberries

| Аспект | Ozon | Wildberries |
|--------|------|-------------|
| Статус для "Сборка" | awaiting_deliver | new, confirm |
| Маркировка | mandatory_mark | КИЗ (sgtin) |
| Подтверждение | ship_posting | add_to_supply + deliver |
| Этикетка | PDF (package-label) | SVG/PNG (stickers) |
| Пагинация | offset/limit | cursor (next) |
