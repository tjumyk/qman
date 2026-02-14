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
    if config.PORT is not None:
        app.config["PORT"] = config.PORT

    if config.MOCK_QUOTA:
        from app.quota_mock import init_mock_host
        init_mock_host()

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
