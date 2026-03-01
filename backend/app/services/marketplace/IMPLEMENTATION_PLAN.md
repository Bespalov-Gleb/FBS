# План реализации интеграции Wildberries

## Анализ требований из ТЗ

### Функциональность "Вкладка Сборка"
- [x] Получение заказов в статусе "На сборке" (`confirm`)
- [x] Получение стикеров (этикеток)
- [x] Привязка КИЗ кодов
- [ ] Отметка заказа как "Собрано" (добавление в поставку)

### Функциональность "Вкладка Маркетплейсы"
- [ ] Тестирование подключения (валидация API токена)
- [x] Ручная синхронизация заказов

## План методов для WildberriesClient

### ✅ Уже реализовано
1. `get_orders()` - получение новых заказов (статус `new`)
2. `get_order_label()` - получение стикеров
3. `add_kiz_code()` - привязка КИЗ
4. `update_order_status()` - отмена заказа

### 🔄 Нужно реализовать

#### 1. Получение заказов по статусу
```python
async def get_orders_by_status(
    status: str,  # new, confirm, complete
    limit: int = 1000,
    next_cursor: int = 0,
) -> tuple[list[MarketplaceOrder], int]
```
**Endpoint**: `GET /api/v3/orders?limit=&next=`
**Назначение**: Получение заказов в определенном статусе для вкладки "Сборка"

#### 2. Получение статусов заказов
```python
async def get_orders_statuses(
    order_ids: list[int]
) -> dict[int, dict[str, str]]
```
**Endpoint**: `POST /api/v3/orders/status`
**Назначение**: Проверка текущего статуса заказов

#### 3. Управление поставками (supplies)

##### 3.1 Создание поставки
```python
async def create_supply(
    name: str
) -> str  # supply_id
```
**Endpoint**: `POST /api/v3/supplies`
**Назначение**: Создание новой поставки для группировки заказов

##### 3.2 Добавление заказов в поставку
```python
async def add_orders_to_supply(
    supply_id: str,
    order_ids: list[int]
) -> bool
```
**Endpoint**: `PATCH /api/marketplace/v3/supplies/{supplyId}/orders`
**Назначение**: Добавление собранных заказов в поставку (переводит в статус `confirm`)

##### 3.3 Передача поставки в доставку
```python
async def deliver_supply(
    supply_id: str
) -> bool
```
**Endpoint**: `PATCH /api/v3/supplies/{supplyId}/deliver`
**Назначение**: Отправка поставки (переводит заказы в статус `complete`)

##### 3.4 Получение QR кода поставки
```python
async def get_supply_barcode(
    supply_id: str
) -> bytes
```
**Endpoint**: `GET /api/v3/supplies/{supplyId}/barcode`
**Назначение**: Получение QR кода для печати на коробке

#### 4. Работа с метаданными

##### 4.1 Получение метаданных заказов
```python
async def get_orders_metadata(
    order_ids: list[int]
) -> dict[int, dict[str, Any]]
```
**Endpoint**: `POST /api/marketplace/v3/orders/meta`
**Назначение**: Получение всех метаданных (КИЗ и др.)

##### 4.2 Удаление метаданных
```python
async def delete_order_metadata(
    order_id: int,
    key: str  # sgtin, imei, uin, gtin
) -> bool
```
**Endpoint**: `DELETE /api/v3/orders/{orderId}/meta?key={key}`
**Назначение**: Удаление ошибочно введенных метаданных

#### 5. Утилиты

##### 5.1 Тест подключения
```python
async def test_connection() -> bool
```
**Назначение**: Валидация API токена через простой запрос

##### 5.2 Получение списка складов
```python
async def get_warehouses() -> list[dict[str, Any]]
```
**Endpoint**: Уточнить в документации
**Назначение**: Список складов для настроек

## Приоритеты реализации

### Высокий приоритет (для MVP)
1. ✅ `get_orders_by_status()` - критично для вкладки "Сборка"
2. ✅ `create_supply()` - нужно для завершения сборки
3. ✅ `add_orders_to_supply()` - перевод в "На сборке"
4. ✅ `deliver_supply()` - завершение процесса
5. ✅ `get_orders_statuses()` - для отображения актуальных статусов
6. ✅ `test_connection()` - для вкладки "Маркетплейсы"

### Средний приоритет
7. ✅ `get_supply_barcode()` - для печати QR
8. ✅ `get_orders_metadata()` - просмотр КИЗ

### Низкий приоритет (можно позже)
9. `delete_order_metadata()` - исправление ошибок
10. `get_warehouses()` - улучшение UX

## Workflow сборки заказа в WB

```
1. Новый заказ (status: new)
   ↓
2. Получить через get_orders() или get_orders_by_status('new')
   ↓
3. Упаковщик берет в работу:
   - Печатает стикер get_order_label()
   - Если нужен КИЗ: add_kiz_code()
   ↓
4. Создать поставку create_supply()
   ↓
5. Добавить заказ в поставку add_orders_to_supply()
   (статус меняется: new → confirm)
   ↓
6. Передать поставку deliver_supply()
   (статус меняется: confirm → complete)
   ↓
7. Готово! Заказ в доставке
```

## Технические детали

### Rate Limits
- FBS orders/supplies/passes: 300 req/min (200ms interval, 20 burst)
- Нужно добавить rate limiter

### Пагинация
- Используется cursor-based: `next` параметр
- Максимум 1000 записей за запрос

### Обработка ошибок
- HTTP 409: считается как 10 запросов (особое внимание!)
- Нужен retry для временных ошибок

---

Статус: В процессе реализации
Дата: 2026-02-13
