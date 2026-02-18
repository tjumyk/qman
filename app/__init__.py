"""Flask application factory."""

import json
import os
from typing import Any

from flask import Flask, redirect

from app.models import AppConfig
from app.routes import api as api_routes
from app.routes import remote_api as remote_api_routes
from app.utils import get_logger

logger = get_logger(__name__)

# Static folder is at project root (parent of app package), not inside app/
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_STATIC_FOLDER = os.path.join(_PROJECT_ROOT, "static")


def load_config(path: str | None = None) -> AppConfig:
    """Load and validate app config from JSON file."""
    config_path = path or "config.json"
    logger.info(f"Loading config from {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    logger.debug(f"Config:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
    return AppConfig.model_validate(data)


def create_app(config_path: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config.json")
    
    config = load_config(config_path)
    app = Flask(__name__, static_folder=_STATIC_FOLDER)

    # Flask config from Pydantic model
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SESSION_COOKIE_NAME"] = config.SESSION_COOKIE_NAME
    app.config["SLAVES"] = [s.model_dump() for s in config.SLAVES]
    app.config["API_KEY"] = config.API_KEY
    app.config["MOCK_QUOTA"] = config.MOCK_QUOTA
    if config.MOCK_HOST_ID is not None:
        app.config["MOCK_HOST_ID"] = config.MOCK_HOST_ID
    app.config["USE_PYQUOTA"] = config.USE_PYQUOTA
    app.config["USE_ZFS"] = config.USE_ZFS
    if not config.MOCK_QUOTA and not config.USE_PYQUOTA and not config.USE_ZFS and not config.USE_DOCKER_QUOTA:
        raise ValueError(
            "At least one of USE_PYQUOTA, USE_ZFS, USE_DOCKER_QUOTA must be enabled when MOCK_QUOTA is false"
        )
    if config.ZFS_DATASETS is not None:
        app.config["ZFS_DATASETS"] = config.ZFS_DATASETS
    if config.PORT is not None:
        app.config["PORT"] = config.PORT
    # Docker quota (slave)
    app.config["USE_DOCKER_QUOTA"] = config.USE_DOCKER_QUOTA
    if config.DOCKER_DATA_ROOT is not None:
        app.config["DOCKER_DATA_ROOT"] = config.DOCKER_DATA_ROOT
    if config.DOCKER_QUOTA_RESERVED_BYTES is not None:
        app.config["DOCKER_QUOTA_RESERVED_BYTES"] = config.DOCKER_QUOTA_RESERVED_BYTES
    if config.CELERY_BROKER_URL is not None:
        app.config["CELERY_BROKER_URL"] = config.CELERY_BROKER_URL
    if config.CELERY_RESULT_BACKEND is not None:
        app.config["CELERY_RESULT_BACKEND"] = config.CELERY_RESULT_BACKEND
    if config.DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS is not None:
        app.config["DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS"] = config.DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS
    if config.DOCKER_QUOTA_ENFORCEMENT_ORDER is not None:
        app.config["DOCKER_QUOTA_ENFORCEMENT_ORDER"] = config.DOCKER_QUOTA_ENFORCEMENT_ORDER
    if config.SLAVE_HOST_ID is not None:
        app.config["SLAVE_HOST_ID"] = config.SLAVE_HOST_ID
    if config.MASTER_EVENT_CALLBACK_URL is not None:
        app.config["MASTER_EVENT_CALLBACK_URL"] = config.MASTER_EVENT_CALLBACK_URL
    if config.MASTER_EVENT_CALLBACK_SECRET is not None:
        app.config["MASTER_EVENT_CALLBACK_SECRET"] = config.MASTER_EVENT_CALLBACK_SECRET
    # Notifications (master)
    if config.SMTP_HOST is not None:
        app.config["SMTP_HOST"] = config.SMTP_HOST
    if config.SMTP_PORT is not None:
        app.config["SMTP_PORT"] = config.SMTP_PORT
    if config.SMTP_USER is not None:
        app.config["SMTP_USER"] = config.SMTP_USER
    if config.SMTP_PASSWORD is not None:
        app.config["SMTP_PASSWORD"] = config.SMTP_PASSWORD
    if config.NOTIFICATION_FROM is not None:
        app.config["NOTIFICATION_FROM"] = config.NOTIFICATION_FROM
    if config.NOTIFICATION_OAUTH_ACCESS_TOKEN is not None:
        app.config["NOTIFICATION_OAUTH_ACCESS_TOKEN"] = config.NOTIFICATION_OAUTH_ACCESS_TOKEN
    if config.SLAVE_EVENT_SECRET is not None:
        app.config["SLAVE_EVENT_SECRET"] = config.SLAVE_EVENT_SECRET

    if config.MOCK_QUOTA:
        from app.quota_mock import init_mock_host
        init_mock_host()

    if config.USE_DOCKER_QUOTA and config.CELERY_BROKER_URL:
        from app.celery_app import make_celery
        make_celery(app)

    from auth_connect import oauth
    oauth.init_app(app, config_file=os.path.join(_PROJECT_ROOT, "oauth.config.json"))

    @app.route("/account/logout", methods=["GET"])
    def logout() -> Any:
        oauth.clear_user()
        return redirect("/")

    # Web: SPA index
    @app.route("/")
    def index(path: str | None = None) -> Any:
        return 'backend server', {'Content-Type': 'text/plain'}

    # API and remote-api routes
    api_routes.register_api_routes(app)
    remote_api_routes.register_remote_api_routes(app)

    return app
