"""Celery app for slave: Docker quota enforcement (and optional beat schedule)."""

from celery import Celery
from celery.schedules import schedule

from app.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_INTERVAL = 300.0  # 5 minutes


def make_celery(app=None) -> Celery:
    """Configure the global celery_app from Flask app config. Returns the same celery_app."""
    if app:
        celery_app.conf.update(
            broker_url=app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            result_backend=app.config.get("CELERY_RESULT_BACKEND") or app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_routes={
                "app.tasks.docker_quota_tasks.enforce_docker_quota": {"queue": "qman.docker"},
                "app.tasks.docker_quota_tasks.sync_docker_attribution": {"queue": "qman.docker"},
            },
        )
        interval_secs = float(app.config.get("DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS", _DEFAULT_INTERVAL))
        celery_app.conf.beat_schedule = {
            "enforce-docker-quota-periodic": {
                "task": "app.tasks.docker_quota_tasks.enforce_docker_quota",
                "schedule": schedule(run_every=interval_secs),
                "options": {"queue": "qman.docker"},
            },
            "sync-docker-attribution-periodic": {
                "task": "app.tasks.docker_quota_tasks.sync_docker_attribution",
                "schedule": schedule(run_every=120.0),
                "options": {"queue": "qman.docker"},
            },
        }
    else:
        import json
        import os
        broker_url = os.environ.get("CELERY_BROKER_URL")
        result_backend = os.environ.get("CELERY_RESULT_BACKEND")
        enforce_interval = _DEFAULT_INTERVAL
        config_path = os.environ.get("CONFIG_PATH", "config.json")
        if config_path and os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    data = json.load(f)
                if broker_url is None:
                    broker_url = data.get("CELERY_BROKER_URL")
                if result_backend is None:
                    result_backend = data.get("CELERY_RESULT_BACKEND")
                if data.get("DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS") is not None:
                    enforce_interval = float(data["DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS"])
            except Exception as e:
                logger.warning("Could not load Celery config from %s: %s", config_path, e)
        if broker_url is None:
            broker_url = "redis://localhost:6379/0"
        if result_backend is None:
            result_backend = broker_url
        celery_app.conf.broker_url = broker_url
        celery_app.conf.result_backend = result_backend
        celery_app.conf.task_serializer = "json"
        celery_app.conf.accept_content = ["json"]
        celery_app.conf.result_serializer = "json"
        celery_app.conf.beat_schedule = {
            "enforce-docker-quota-periodic": {
                "task": "app.tasks.docker_quota_tasks.enforce_docker_quota",
                "schedule": schedule(run_every=enforce_interval),
                "options": {"queue": "qman.docker"},
            },
            "sync-docker-attribution-periodic": {
                "task": "app.tasks.docker_quota_tasks.sync_docker_attribution",
                "schedule": schedule(run_every=120.0),
                "options": {"queue": "qman.docker"},
            },
        }
    return celery_app


# Global instance; make_celery(flask_app) updates its config when USE_DOCKER_QUOTA
#
# IMPORTANT: The worker must import task modules so @celery_app.task decorators run
# and tasks are registered. Without this, beat can enqueue tasks that the worker
# treats as "unregistered".
celery_app = Celery(
    "qman.slave",
    include=[
        "app.tasks.docker_quota_tasks",
    ],
)
make_celery()  # set defaults
