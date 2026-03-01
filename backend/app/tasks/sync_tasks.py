"""
Celery задачи синхронизации
"""
import asyncio

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.marketplace import Marketplace
from app.services.order_sync_service import OrderSyncService
from app.utils.logger import logger


def run_async(coro):
    """Запуск async функции в sync контексте"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True)
def sync_all_marketplaces(self):
    """
    Фоновая синхронизация заказов для всех активных маркетплейсов.
    
    Вызывается по расписанию (cron) или вручную.
    """
    db: Session = SessionLocal()
    try:
        marketplaces = db.query(Marketplace).filter(
            Marketplace.is_active == True,
        ).all()
        total = 0
        for mp in marketplaces:
            try:
                count = run_async(
                    OrderSyncService.sync_marketplace_orders(mp, db),
                )
                total += count
            except Exception as e:
                logger.error(
                    f"Sync failed for marketplace {mp.id}: {e}",
                    exc_info=True,
                )
        return {"synced": total, "marketplaces": len(marketplaces)}
    finally:
        db.close()


@celery_app.task(bind=True)
def sync_marketplace_orders_task(self, marketplace_id: int):
    """
    Синхронизация заказов для одного маркетплейса.
    """
    db: Session = SessionLocal()
    try:
        mp = db.query(Marketplace).filter(
            Marketplace.id == marketplace_id,
            Marketplace.is_active == True,
        ).first()
        if not mp:
            return {"synced": 0, "error": "Marketplace not found"}
        count = run_async(OrderSyncService.sync_marketplace_orders(mp, db))
        return {"synced": count, "marketplace_id": marketplace_id}
    finally:
        db.close()
