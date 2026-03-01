"""
Скрипт для тестирования интеграций с маркетплейсами

Использование:
    python scripts/test_marketplace_integration.py --marketplace ozon
    python scripts/test_marketplace_integration.py --marketplace wildberries
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Добавление корня проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.core.security import decrypt_api_key
from app.services.marketplace import OzonClient, WildberriesClient
from app.utils.logger import logger


async def test_ozon_integration(api_key: str, client_id: str) -> None:
    """
    Тестирование интеграции с Ozon
    
    Args:
        api_key: API ключ Ozon
        client_id: Client ID Ozon
    """
    logger.info("Testing Ozon integration...")
    
    async with OzonClient(api_key=api_key, client_id=client_id) as client:
        try:
            # Тест 1: Получение заказов
            logger.info("Test 1: Fetching FBS orders...")
            orders = await client.get_orders(
                status="awaiting_packaging",
            )
            logger.info(f"✓ Received {len(orders)} orders")
            
            if orders:
                first_order = orders[0]
                logger.info(f"First order: {first_order.posting_number}")
                
                # Тест 2: Получение этикетки (если есть заказы)
                logger.info("Test 2: Fetching order label...")
                try:
                    label = await client.get_order_label(first_order.posting_number)
                    logger.info(f"✓ Received label (size: {len(label)} bytes)")
                except Exception as e:
                    logger.warning(f"✗ Failed to fetch label: {e}")
            
            logger.info("✓ Ozon integration test completed successfully")
            
        except Exception as e:
            logger.error(f"✗ Ozon integration test failed: {e}", exc_info=True)
            raise


async def test_wildberries_integration(api_key: str) -> None:
    """
    Тестирование интеграции с Wildberries
    
    Args:
        api_key: API токен Wildberries (Marketplace категория)
    """
    logger.info("Testing Wildberries integration...")
    
    async with WildberriesClient(api_key=api_key) as client:
        try:
            # Тест 1: Получение новых заказов
            logger.info("Test 1: Fetching new FBS orders...")
            orders = await client.get_orders()
            logger.info(f"✓ Received {len(orders)} orders")
            
            if orders:
                first_order = orders[0]
                logger.info(f"First order: {first_order.external_id}")
                
                # Тест 2: Получение стикера (если есть заказы)
                logger.info("Test 2: Fetching order sticker...")
                try:
                    sticker = await client.get_order_label(
                        order_id=first_order.external_id,
                        sticker_type="svg",
                    )
                    logger.info(f"✓ Received sticker (size: {len(sticker)} bytes)")
                except Exception as e:
                    logger.warning(f"✗ Failed to fetch sticker: {e}")
            
            logger.info("✓ Wildberries integration test completed successfully")
            
        except Exception as e:
            logger.error(f"✗ Wildberries integration test failed: {e}", exc_info=True)
            raise


def main() -> None:
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description="Test marketplace API integrations"
    )
    parser.add_argument(
        "--marketplace",
        choices=["ozon", "wildberries"],
        required=True,
        help="Marketplace to test",
    )
    parser.add_argument(
        "--api-key",
        help="API key (if not in environment)",
    )
    parser.add_argument(
        "--client-id",
        help="Client ID (for Ozon, if not in environment)",
    )
    
    args = parser.parse_args()
    
    if args.marketplace == "ozon":
        api_key = args.api_key or input("Enter Ozon API Key: ")
        client_id = args.client_id or input("Enter Ozon Client ID: ")
        
        asyncio.run(test_ozon_integration(api_key, client_id))
        
    elif args.marketplace == "wildberries":
        api_key = args.api_key or input("Enter Wildberries API Token: ")
        
        asyncio.run(test_wildberries_integration(api_key))


if __name__ == "__main__":
    main()
