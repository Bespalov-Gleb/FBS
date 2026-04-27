"""
Гарант синхронизации заказов:
- не допускает параллельный sync одного маркетплейса;
- даёт приоритет ручному sync;
- позволяет кооперативно останавливать авто sync.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

from app.utils.cache import get_redis_client
from app.utils.logger import logger


class SyncCooldownError(Exception):
    """Синхронизацию нельзя запускать чаще минимального интервала."""

    def __init__(self, seconds_left: int) -> None:
        self.seconds_left = max(0, int(seconds_left))
        super().__init__(f"Sync cooldown: wait {self.seconds_left}s")


class AutoSyncCancelled(Exception):
    """Автосинк отменён из-за ручного синка."""


class ManualSyncLockTimeout(Exception):
    """Ручной синк не смог дождаться освобождения lock."""


class OrderSyncGuard:
    """Redis-lock для синка заказов по marketplace_id."""

    _LOCK_TTL_SEC = int(os.environ.get("ORDER_SYNC_LOCK_TTL_SEC", "7200") or 7200)
    _MANUAL_INTENT_TTL_SEC = int(
        os.environ.get("ORDER_SYNC_MANUAL_INTENT_TTL_SEC", "1800") or 1800
    )
    _AUTO_CANCEL_TTL_SEC = int(
        os.environ.get("ORDER_SYNC_AUTO_CANCEL_TTL_SEC", "1800") or 1800
    )
    _MANUAL_WAIT_TIMEOUT_SEC = float(
        os.environ.get("ORDER_SYNC_MANUAL_WAIT_TIMEOUT_SEC", "90") or 90
    )
    _WAIT_STEP_SEC = 0.25

    @staticmethod
    def _lock_key(marketplace_id: int) -> str:
        return f"fbs:ordersync:lock:{marketplace_id}"

    @staticmethod
    def _manual_intent_key(marketplace_id: int) -> str:
        return f"fbs:ordersync:manual:intent:{marketplace_id}"

    @staticmethod
    def _cancel_auto_key(marketplace_id: int) -> str:
        return f"fbs:ordersync:cancel:auto:{marketplace_id}"

    @staticmethod
    def request_manual_priority(marketplace_id: int) -> None:
        """Пометить, что ручной sync должен получить приоритет для marketplace."""
        try:
            r = get_redis_client()
            r.setex(
                OrderSyncGuard._manual_intent_key(marketplace_id),
                OrderSyncGuard._MANUAL_INTENT_TTL_SEC,
                "1",
            )
            r.setex(
                OrderSyncGuard._cancel_auto_key(marketplace_id),
                OrderSyncGuard._AUTO_CANCEL_TTL_SEC,
                "1",
            )
        except Exception as e:
            logger.warning(
                "Order sync guard: failed to set manual priority for %s: %s",
                marketplace_id,
                e,
            )

    @staticmethod
    def clear_manual_priority(marketplace_id: int) -> None:
        """Очистить флаги приоритета ручного sync."""
        try:
            r = get_redis_client()
            r.delete(
                OrderSyncGuard._manual_intent_key(marketplace_id),
                OrderSyncGuard._cancel_auto_key(marketplace_id),
            )
        except Exception as e:
            logger.warning(
                "Order sync guard: failed to clear manual priority for %s: %s",
                marketplace_id,
                e,
            )

    @staticmethod
    def should_skip_auto(marketplace_id: int) -> bool:
        """Нужно ли пропустить авто sync из-за ручного приоритета."""
        try:
            r = get_redis_client()
            return (
                r.exists(OrderSyncGuard._manual_intent_key(marketplace_id)) > 0
                or r.exists(OrderSyncGuard._cancel_auto_key(marketplace_id)) > 0
            )
        except Exception:
            return False

    @staticmethod
    def ensure_auto_not_cancelled(marketplace_id: int) -> None:
        """Проверить, что автосинк не отменён ручным sync."""
        try:
            if get_redis_client().exists(OrderSyncGuard._cancel_auto_key(marketplace_id)) > 0:
                raise AutoSyncCancelled(
                    f"Auto sync cancelled by manual priority (marketplace_id={marketplace_id})"
                )
        except AutoSyncCancelled:
            raise
        except Exception:
            # Если Redis временно недоступен — не валим синк.
            return

    @staticmethod
    def acquire_lock(marketplace_id: int, mode: str) -> Optional[str]:
        """
        Захватить lock синка.
        Возвращает token lock либо None, если для авто lock занят.
        Для manual — ждёт освобождения lock в пределах timeout, иначе бросает исключение.
        """
        token = f"{mode}:{uuid.uuid4().hex}"
        lock_key = OrderSyncGuard._lock_key(marketplace_id)
        wait_timeout = OrderSyncGuard._MANUAL_WAIT_TIMEOUT_SEC if mode == "manual" else 0.0
        deadline = time.monotonic() + wait_timeout
        r = get_redis_client()

        while True:
            ok = r.set(lock_key, token, nx=True, ex=OrderSyncGuard._LOCK_TTL_SEC)
            if ok:
                return token
            if mode != "manual":
                return None

            # Ручной sync перехватывает приоритет: просим авто остановиться.
            r.setex(
                OrderSyncGuard._cancel_auto_key(marketplace_id),
                OrderSyncGuard._AUTO_CANCEL_TTL_SEC,
                "1",
            )
            if time.monotonic() >= deadline:
                raise ManualSyncLockTimeout(
                    f"Could not acquire sync lock for marketplace {marketplace_id}"
                )
            time.sleep(OrderSyncGuard._WAIT_STEP_SEC)

    @staticmethod
    def release_lock(marketplace_id: int, token: Optional[str]) -> None:
        """Освободить lock только если token совпадает."""
        if not token:
            return
        try:
            r = get_redis_client()
            lock_key = OrderSyncGuard._lock_key(marketplace_id)
            current = r.get(lock_key)
            if current == token:
                r.delete(lock_key)
        except Exception as e:
            logger.warning(
                "Order sync guard: failed to release lock for %s: %s",
                marketplace_id,
                e,
            )
