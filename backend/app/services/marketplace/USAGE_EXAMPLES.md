# Примеры использования Wildberries API Client

## Полный workflow сборки заказа

```python
from app.services.marketplace import WildberriesClient
from datetime import datetime

async def process_order_workflow():
    """Полный цикл обработки заказа"""
    
    # Инициализация клиента
    async with WildberriesClient(api_key="your-token") as client:
        
        # 1. Получить новые заказы
        print("📦 Fetching new orders...")
        new_orders = await client.get_new_orders()
        print(f"Found {len(new_orders)} new orders")
        
        if not new_orders:
            print("No orders to process")
            return
        
        # 2. Выбрать заказы для сборки
        orders_to_pack = new_orders[:5]  # Берем первые 5 заказов
        order_ids = [int(order.external_id) for order in orders_to_pack]
        
        # 3. Для каждого заказа
        for order in orders_to_pack:
            print(f"\n🔨 Processing order {order.external_id}:")
            print(f"   Article: {order.article}")
            print(f"   Product: {order.product_name}")
            
            # 3.1 Получить стикер для печати
            print("   📄 Getting sticker...")
            sticker = await client.get_order_label(
                order_id=order.external_id,
                sticker_type="svg",
                width=58,
                height=40,
            )
            # TODO: Отправить на печать
            
            # 3.2 Проверить нужны ли метаданные
            required_meta = order.metadata.get("required_meta", [])
            optional_meta = order.metadata.get("optional_meta", [])
            
            if "sgtin" in required_meta or "sgtin" in optional_meta:
                print("   🏷️  КИЗ required!")
                # Запросить скан КИЗ от пользователя
                kiz_code = input("   Scan КИЗ code: ")
                
                # Привязать КИЗ
                await client.add_kiz_code(
                    order_id=int(order.external_id),
                    kiz_code=kiz_code,
                )
                print("   ✓ КИЗ added")
        
        # 4. Создать поставку
        print("\n📦 Creating supply...")
        supply_name = f"Supply-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        supply_id = await client.create_supply(name=supply_name)
        print(f"✓ Created supply: {supply_id}")
        
        # 5. Добавить заказы в поставку (переводит в статус confirm)
        print(f"\n➕ Adding {len(order_ids)} orders to supply...")
        await client.add_orders_to_supply(
            supply_id=supply_id,
            order_ids=order_ids,
        )
        print("✓ Orders added to supply")
        
        # 6. Получить QR код поставки
        print("\n📊 Getting supply barcode...")
        barcode_data = await client.get_supply_barcode(supply_id)
        # TODO: Распечатать QR код на коробке
        print("✓ Barcode received")
        
        # 7. Передать поставку в доставку (переводит в статус complete)
        print(f"\n🚚 Delivering supply {supply_id}...")
        await client.deliver_supply(supply_id)
        print("✓ Supply delivered!")
        
        # 8. Проверить статусы заказов
        print("\n🔍 Checking order statuses...")
        statuses = await client.get_orders_statuses(order_ids)
        for order_id, status in statuses.items():
            print(f"   Order {order_id}: {status['supplier_status']} / {status['wb_status']}")
        
        print("\n✅ Workflow completed successfully!")

# Запуск
if __name__ == "__main__":
    import asyncio
    asyncio.run(process_order_workflow())
```

## Пример 1: Получение и фильтрация заказов

```python
async def get_filtered_orders():
    """Получение заказов с фильтрацией"""
    
    async with WildberriesClient(api_key="your-token") as client:
        # Получить все новые заказы
        new_orders = await client.get_new_orders()
        
        # Фильтрация по складу
        warehouse_id = 658434
        orders_from_warehouse = [
            order for order in new_orders
            if order.metadata.get("warehouse_id") == warehouse_id
        ]
        
        # Фильтрация по артикулу
        article = "MY-ARTICLE-123"
        orders_by_article = [
            order for order in new_orders
            if order.article == article
        ]
        
        # Заказы требующие КИЗ
        orders_need_kiz = [
            order for order in new_orders
            if "sgtin" in order.metadata.get("required_meta", [])
        ]
        
        print(f"Total new orders: {len(new_orders)}")
        print(f"From warehouse {warehouse_id}: {len(orders_from_warehouse)}")
        print(f"Article {article}: {len(orders_by_article)}")
        print(f"Need КИЗ: {len(orders_need_kiz)}")
```

## Пример 2: Работа с пагинацией

```python
async def fetch_all_orders_with_pagination():
    """Получение всех заказов с пагинацией"""
    
    async with WildberriesClient(api_key="your-token") as client:
        all_orders = []
        next_cursor = 0
        
        while True:
            # Получить следующую порцию
            orders, next_cursor = await client.get_orders_by_status(
                limit=1000,
                next_cursor=next_cursor,
            )
            
            all_orders.extend(orders)
            print(f"Fetched {len(orders)} orders, total: {len(all_orders)}")
            
            # Если курсор 0 - больше данных нет
            if next_cursor == 0:
                break
        
        print(f"✓ Total orders fetched: {len(all_orders)}")
        return all_orders
```

## Пример 3: Массовое добавление КИЗ

```python
async def bulk_add_kiz_codes():
    """Массовое добавление КИЗ кодов"""
    
    # Данные: {order_id: kiz_code}
    kiz_data = {
        13833711: "01234567890123456",
        13833712: "01234567890123457",
        13833713: "01234567890123458",
    }
    
    async with WildberriesClient(api_key="your-token") as client:
        success_count = 0
        failed_count = 0
        
        for order_id, kiz_code in kiz_data.items():
            try:
                await client.add_kiz_code(order_id, kiz_code)
                success_count += 1
                print(f"✓ Order {order_id}: КИЗ added")
            except Exception as e:
                failed_count += 1
                print(f"✗ Order {order_id}: Failed - {e}")
        
        print(f"\nResults: {success_count} success, {failed_count} failed")
```

## Пример 4: Проверка статусов в реальном времени

```python
async def monitor_orders_status():
    """Мониторинг статусов заказов"""
    
    order_ids = [13833711, 13833712, 13833713]
    
    async with WildberriesClient(api_key="your-token") as client:
        while True:
            statuses = await client.get_orders_statuses(order_ids)
            
            print(f"\n📊 Status at {datetime.now().strftime('%H:%M:%S')}:")
            for order_id, status in statuses.items():
                supplier = status["supplier_status"]
                wb = status["wb_status"]
                print(f"   Order {order_id}: {supplier} / {wb}")
            
            # Проверить все ли доставлены
            all_completed = all(
                s["supplier_status"] == "complete" 
                for s in statuses.values()
            )
            
            if all_completed:
                print("\n✅ All orders completed!")
                break
            
            # Подождать перед следующей проверкой
            await asyncio.sleep(60)  # 1 минута
```

## Пример 5: Управление несколькими поставками

```python
async def manage_multiple_supplies():
    """Работа с несколькими поставками"""
    
    async with WildberriesClient(api_key="your-token") as client:
        # Получить все поставки
        supplies, _ = await client.get_supplies_list(limit=100)
        print(f"📦 Found {len(supplies)} supplies")
        
        # Фильтр: только активные (не доставленные)
        active_supplies = [
            s for s in supplies
            if not s.get("isDeleted", False)
        ]
        
        # Просмотреть детали каждой поставки
        for supply in active_supplies[:5]:  # Первые 5
            supply_id = supply.get("id")
            details = await client.get_supply_details(supply_id)
            
            print(f"\nSupply {supply_id}:")
            print(f"   Name: {details.get('name')}")
            print(f"   Created: {details.get('createdAt')}")
            print(f"   Status: {details.get('isDelivered')}")
```

## Пример 6: Тестирование подключения

```python
async def test_marketplace_connection():
    """Проверка подключения к маркетплейсу"""
    
    async with WildberriesClient(api_key="your-token") as client:
        print("🔌 Testing connection to Wildberries API...")
        
        is_connected = await client.test_connection()
        
        if is_connected:
            print("✅ Connection successful!")
            
            # Получить немного статистики
            new_orders = await client.get_new_orders()
            supplies, _ = await client.get_supplies_list(limit=10)
            
            print(f"\n📊 Quick stats:")
            print(f"   New orders: {len(new_orders)}")
            print(f"   Recent supplies: {len(supplies)}")
        else:
            print("❌ Connection failed!")
            print("Check your API token and try again.")
```

## Пример 7: Обработка ошибок

```python
from app.core.exceptions import MarketplaceAPIException

async def handle_api_errors():
    """Правильная обработка ошибок API"""
    
    async with WildberriesClient(api_key="your-token") as client:
        try:
            # Попытка получить заказы
            orders = await client.get_new_orders()
            
        except MarketplaceAPIException as e:
            print(f"❌ API Error: {e.message}")
            print(f"   Marketplace: {e.marketplace}")
            print(f"   Details: {e.detail}")
            
            # Можно добавить retry логику
            if e.status_code == 429:  # Too Many Requests
                print("   Rate limit exceeded, waiting...")
                await asyncio.sleep(60)
                # Повторить запрос
            
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
```

## Пример 8: Интеграция с базой данных

```python
from sqlalchemy.orm import Session
from app.models import Order, Marketplace

async def sync_orders_to_database(db: Session, marketplace_id: int):
    """Синхронизация заказов с базой данных"""
    
    # Получить настройки маркетплейса из БД
    marketplace = db.query(Marketplace).filter_by(id=marketplace_id).first()
    if not marketplace:
        raise ValueError("Marketplace not found")
    
    # Расшифровать API ключ
    from app.core.security import decrypt_api_key
    api_key = decrypt_api_key(marketplace.api_key)
    
    async with WildberriesClient(api_key=api_key) as client:
        # Получить заказы из API
        wb_orders = await client.get_new_orders()
        
        # Синхронизация с БД
        new_orders_count = 0
        updated_orders_count = 0
        
        for wb_order in wb_orders:
            # Проверить существует ли заказ
            existing_order = db.query(Order).filter_by(
                external_id=wb_order.external_id,
                marketplace_id=marketplace_id,
            ).first()
            
            if existing_order:
                # Обновить существующий
                existing_order.status = wb_order.status
                existing_order.metadata = wb_order.metadata
                updated_orders_count += 1
            else:
                # Создать новый
                new_order = Order(
                    marketplace_id=marketplace_id,
                    external_id=wb_order.external_id,
                    posting_number=wb_order.posting_number,
                    article=wb_order.article,
                    product_name=wb_order.product_name,
                    quantity=wb_order.quantity,
                    warehouse_name=wb_order.warehouse_name,
                    status=wb_order.status,
                    marketplace_created_at=wb_order.created_at,
                    metadata=wb_order.metadata,
                )
                db.add(new_order)
                new_orders_count += 1
        
        # Сохранить изменения
        db.commit()
        
        # Обновить время последней синхронизации
        marketplace.last_sync_at = datetime.utcnow()
        db.commit()
        
        print(f"✓ Sync completed:")
        print(f"   New orders: {new_orders_count}")
        print(f"   Updated orders: {updated_orders_count}")
```

## Полезные советы

### 1. Rate Limiting
```python
# Добавить задержку между запросами
import asyncio

for order_id in order_ids:
    await client.add_kiz_code(order_id, kiz_codes[order_id])
    await asyncio.sleep(0.2)  # 200ms между запросами
```

### 2. Batch операции
```python
# Обрабатывать заказы пакетами
from itertools import islice

def batched(iterable, n):
    """Разбить итератор на пакеты по n элементов"""
    iterator = iter(iterable)
    while batch := list(islice(iterator, n)):
        yield batch

# Получить статусы пакетами по 100
for batch in batched(all_order_ids, 100):
    statuses = await client.get_orders_statuses(batch)
    process_statuses(statuses)
```

### 3. Логирование
```python
import logging

# Настроить логирование для отладки
logging.basicConfig(level=logging.DEBUG)

# Теперь все API вызовы будут логироваться
async with WildberriesClient(api_key="your-token") as client:
    orders = await client.get_new_orders()
```

---

Эти примеры покрывают все основные сценарии использования API Wildberries для вашего приложения.
