"""
Celery приложение
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "fbs",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.sync_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule_filename="/app/logs/celerybeat-schedule",  # записываемая директория (избегаем Permission denied)
    beat_schedule={
        "sync-orders-every-5-min": {
            "task": "app.tasks.sync_tasks.sync_all_marketplaces",
            "schedule": 300.0,  # каждые 5 минут
        },
    },
)
