"""Celery application and reliability configuration.

Delivery/ack settings explained
--------------------------------
* ``task_acks_late=True`` + ``task_reject_on_worker_lost=True``: a task is only
  acknowledged after it finishes. If a worker is killed mid-task the broker
  redelivers the message. Combined with the idempotent claim (stale-lock
  reclaim) this means a crashed task is safely reprocessed, not lost.
* ``worker_prefetch_multiplier=1``: each worker reserves one task at a time so a
  slow PDF render doesn't hoard a backlog another worker could handle.
* Beat runs two safety-net periodic tasks: the outbox dispatcher (publishes any
  recipient whose enqueue failed at request time) and the stale-recipient reaper
  (recovers work abandoned by crashed workers so jobs never hang).
"""
from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "bulk_certificate",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_default_queue="certificates",
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-outbox": {
            "task": "app.workers.tasks.dispatch_outbox",
            "schedule": 10.0,
        },
        "reap-stale-recipients": {
            "task": "app.workers.tasks.reap_stale_recipients",
            "schedule": 60.0,
        },
    },
)
