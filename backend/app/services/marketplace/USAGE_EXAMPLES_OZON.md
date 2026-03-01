# Примеры использования Ozon API Client

## Полный workflow сборки (согласно ТЗ)

```python
from app.services.marketplace import OzonClient

async def process_ozon_order_workflow():
    """Цикл обработки заказа Ozon - вкладка "Сборка" """
    
    async with OzonClient(
        api_key="your-api-key",
        client_id="your-client-id",
    ) as client:
        
        # 1. Получить заказы "Ожидают отгрузки" (согласно ТЗ)
        print("📦 Fetching orders awaiting deliver...")
        orders, has_next = await client.get_orders_awaiting_deliver(
            limit=100,
            offset=0,
        )
        print(f"Found {len(orders)} orders")
        
        if not orders:
            print("No orders to process")
            return
        
        # 2. Обработать каждый заказ
        for order in orders:
            print(f"\n🔨 Processing {order.posting_number}:")
            print(f"   Article: {order.article}")
            print(f"   Product: {order.product_name}")
            
            # 2.1 Печать FBS этикетки (PDF)
            print("   📄 Getting FBS label...")
            label_pdf = await client.get_order_label(order.posting_number)
            # TODO: Отправить на печать (Web Printing API)
            
            # 2.2 Получить штрихкоды товара для печати
            print("   📊 Getting product barcodes...")
            details = await client.get_posting_details(
                order.posting_number,
                with_barcodes=True,
            )
            barcodes = details.get("barcodes", {})
            upper_barcode = barcodes.get("upper_barcode")  # Штрихкод товара
            lower_barcode = barcodes.get("lower_barcode")  # FBS штрихкод
            # TODO: Печать обоих штрихкодов
            
            # 2.3 Отметить "Собрано"
            print("   ✓ Marking as shipped...")
            products = details.get("products", [])
            products_data = [
                {"product_id": p["sku"], "quantity": p["quantity"]}
                for p in products
            ]
            await client.ship_posting(order.posting_number, products_data)
            print("   ✓ Shipped!")
        
        print("\n✅ Workflow completed!")
```

## Пример 1: Получение заказов с фильтрацией

```python
async def get_filtered_ozon_orders():
    """Получение заказов с разными фильтрами"""
    
    async with OzonClient(api_key="...", client_id="...") as client:
        # Только "Ожидают отгрузки" (для вкладки Сборка)
        orders, has_next = await client.get_orders_awaiting_deliver()
        
        # С фильтром по складу
        orders_warehouse, _ = await client.get_orders_awaiting_deliver(
            warehouse_id="123",
        )
        
        # С периодом
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(days=7)
        to = datetime.utcnow()
        orders_period, _ = await client.get_orders_with_pagination(
            status="awaiting_deliver",
            since=since,
            to=to,
            limit=500,
        )
        
        print(f"Awaiting deliver: {len(orders)}")
        print(f"From warehouse 123: {len(orders_warehouse)}")
        print(f"Last 7 days: {len(orders_period)}")
```

## Пример 2: Пагинация

```python
async def fetch_all_ozon_orders():
    """Получение всех заказов с пагинацией"""
    
    async with OzonClient(api_key="...", client_id="...") as client:
        all_orders = []
        offset = 0
        limit = 1000
        
        while True:
            orders, has_next = await client.get_orders_with_pagination(
                status="awaiting_deliver",
                limit=limit,
                offset=offset,
            )
            all_orders.extend(orders)
            print(f"Fetched {len(orders)}, total: {len(all_orders)}")
            
            if not has_next:
                break
            
            offset += limit
        
        print(f"✓ Total: {len(all_orders)} orders")
        return all_orders
```

## Пример 3: Печать двух этикеток (согласно ТЗ)

```python
async def print_order_labels(posting_number: str):
    """
    Печать штрихкода товара и FBS штрихкода
    Согласно ТЗ: "Автоматическая печать двух этикеток при клике на артикул"
    """
    async with OzonClient(api_key="...", client_id="...") as client:
        # 1. FBS этикетка (полная, PDF)
        fbs_label_pdf = await client.get_order_label(posting_number)
        # send_to_printer(fbs_label_pdf, type="pdf")
        
        # 2. Штрихкоды товара (из деталей)
        details = await client.get_posting_details(
            posting_number,
            with_barcodes=True,
        )
        barcodes = details.get("barcodes", {})
        
        # Верхний штрихкод - обычно штрихкод товара
        product_barcode = barcodes.get("upper_barcode")
        # Нижний - FBS штрихкод
        fbs_barcode = barcodes.get("lower_barcode")
        
        # Генерация и печать штрихкодов
        # print_barcode(product_barcode)
        # print_barcode(fbs_barcode)
        
        return {
            "fbs_label": fbs_label_pdf,
            "product_barcode": product_barcode,
            "fbs_barcode": fbs_barcode,
        }
```

## Пример 4: Заказ с маркировкой (mandatory_mark)

```python
async def ship_with_mandatory_mark():
    """Подтверждение отгрузки с кодом маркировки"""
    
    async with OzonClient(api_key="...", client_id="...") as client:
        posting_number = "12345-0001-1"
        
        # Данные из get_posting_details
        details = await client.get_posting_details(posting_number)
        products = details.get("products", [])
        
        # Коды маркировки (от сканера)
        mandatory_marks = [
            "01046007880063502115110410ab-cd-ef",
        ]
        
        products_data = [
            {
                "product_id": p["sku"],
                "quantity": p["quantity"],
            }
            for p in products
        ]
        
        await client.ship_posting(
            posting_number,
            products_data,
            mandatory_marks=mandatory_marks,
        )
        print("✓ Shipped with mandatory mark")
```

## Пример 5: Тест подключения

```python
async def test_ozon_connection():
    """Проверка подключения - вкладка Маркетплейсы"""
    
    async with OzonClient(api_key="...", client_id="...") as client:
        print("🔌 Testing Ozon connection...")
        
        is_ok = await client.test_connection()
        
        if is_ok:
            print("✅ Connection OK!")
            warehouses = await client.get_warehouses()
            print(f"   Warehouses: {len(warehouses)}")
        else:
            print("❌ Connection failed!")
```

## Пример 6: Список складов для настроек

```python
async def get_warehouses_for_settings():
    """Получение складов для настройки цветов (вкладка Маркетплейсы)"""
    
    async with OzonClient(api_key="...", client_id="...") as client:
        warehouses = await client.get_warehouses()
        
        for wh in warehouses:
            print(f"ID: {wh.get('warehouse_id')}, Name: {wh.get('name')}")
            # Сохранить в БД с настройкой цвета
```

## Пример 7: Универсальный update_order_status

```python
async def mark_order_completed(posting_number: str):
    """Отметить заказ как собранный через update_order_status"""
    
    from app.services.marketplace import OzonClient, OrderStatus
    
    async with OzonClient(api_key="...", client_id="...") as client:
        # update_order_status автоматически вызовет ship_posting
        success = await client.update_order_status(
            posting_number,
            OrderStatus.COMPLETED,
        )
        return success
```

## Пример 8: Обработка ошибок

```python
from app.core.exceptions import MarketplaceAPIException

async def safe_ozon_operations():
    async with OzonClient(api_key="...", client_id="...") as client:
        try:
            orders, _ = await client.get_orders_awaiting_deliver()
            return orders
            
        except MarketplaceAPIException as e:
            print(f"Ozon API Error: {e.message}")
            print(f"Details: {e.detail}")
            
            if "401" in str(e.detail) or "Unauthorized" in e.message:
                print("Check Client-Id and Api-Key")
            elif "429" in str(e.detail):
                print("Rate limit - wait and retry")
```
