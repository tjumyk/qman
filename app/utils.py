import json
import logging
import os
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_docker_quota_auto_stop_containers(config_data: dict[str, Any] | None = None) -> bool:
    """Whether the slave may stop Docker containers when over quota (env DOCKER_QUOTA_AUTO_STOP_CONTAINERS + JSON).

    If ``config_data`` is the already-loaded config dict, use it for the flag and do not read the file again.
    Default True (preserve historical behavior). Config file key overrides env when present.
    """
    auto_stop = True
    env_val = os.environ.get("DOCKER_QUOTA_AUTO_STOP_CONTAINERS")
    if env_val is not None:
        auto_stop = env_val.strip().lower() in ("1", "true", "yes", "on")
    if config_data is not None:
        if "DOCKER_QUOTA_AUTO_STOP_CONTAINERS" in config_data:
            auto_stop = bool(config_data["DOCKER_QUOTA_AUTO_STOP_CONTAINERS"])
        return auto_stop
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            if "DOCKER_QUOTA_AUTO_STOP_CONTAINERS" in data:
                auto_stop = bool(data["DOCKER_QUOTA_AUTO_STOP_CONTAINERS"])
        except Exception:
            pass
    return auto_stop
