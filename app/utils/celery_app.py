from celery import Celery
from app.database.config import settings

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.utils.celery_schedule"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.update(
    beat_schedule={
        "cancel_order": {
            "task": "app.utils.celery_schedule.cancel_order",
            "schedule": 600,
        }
    }
)
