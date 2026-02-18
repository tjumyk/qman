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
        import os
        celery_app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        celery_app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND") or celery_app.conf.broker_url
        celery_app.conf.task_serializer = "json"
        celery_app.conf.accept_content = ["json"]
        celery_app.conf.result_serializer = "json"
        celery_app.conf.beat_schedule = {
            "enforce-docker-quota-periodic": {
                "task": "app.tasks.docker_quota_tasks.enforce_docker_quota",
                "schedule": schedule(run_every=_DEFAULT_INTERVAL),
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
celery_app = Celery("qman.slave")
make_celery()  # set defaults
