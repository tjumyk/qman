"""Celery task: apply default user quota to users with all-empty limits (all disk types)."""

import json
import math
import os
import pwd
from typing import Any

from app.celery_app import celery_app
from app.default_quota_store import get_devices_with_nonempty_default
from app.models import quota_tuple_to_dict
from app.quota_common import should_include_uid
from app.utils import get_logger

logger = get_logger(__name__)


def _load_quota_config() -> dict[str, Any]:
    """Load quota-related config from CONFIG_PATH or env. Used when running without Flask app."""
    config: dict[str, Any] = {
        "MOCK_QUOTA": False,
        "USE_PYQUOTA": True,
        "USE_ZFS": False,
        "USE_DOCKER_QUOTA": False,
        "ZFS_DATASETS": None,
        "DOCKER_DATA_ROOT": None,
        "DOCKER_QUOTA_RESERVED_BYTES": None,
    }
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            config["MOCK_QUOTA"] = bool(data.get("MOCK_QUOTA", False))
            config["USE_PYQUOTA"] = bool(data.get("USE_PYQUOTA", True))
            config["USE_ZFS"] = bool(data.get("USE_ZFS", False))
            config["USE_DOCKER_QUOTA"] = bool(data.get("USE_DOCKER_QUOTA", False))
            config["ZFS_DATASETS"] = data.get("ZFS_DATASETS")
            config["DOCKER_DATA_ROOT"] = data.get("DOCKER_DATA_ROOT")
            config["DOCKER_QUOTA_RESERVED_BYTES"] = data.get("DOCKER_QUOTA_RESERVED_BYTES")
        except Exception as e:
            logger.warning("Could not load config from %s: %s", config_path, e)
    return config


def _get_eligible_users(mock_quota: bool) -> list[tuple[int, str]]:
    """Return list of (uid, name) for eligible host users."""
    if mock_quota:
        from app.quota_mock import _get_mock_state
        mock_state = _get_mock_state()
        return [(uid, name) for uid, name in mock_state["users"].items() if should_include_uid(uid)]
    return [(entry.pw_uid, entry.pw_name) for entry in pwd.getpwall() if should_include_uid(entry.pw_uid)]


def _get_current_quotas_for_device(
    device: str,
    users: list[tuple[int, str]],
    config: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """Build uid -> current quota dict for the device. Missing uid = all zeros."""
    current: dict[int, dict[str, Any]] = {}
    if config["MOCK_QUOTA"]:
        from app.quota_mock import _get_mock_state
        mock_state = _get_mock_state()
        for dev in mock_state.get("devices", {}).values():
            if dev.get("name") == device:
                for q in dev.get("user_quotas", []):
                    current[q["uid"]] = q
                break
        return current
    if device.startswith("/dev/") and config["USE_PYQUOTA"]:
        import pyquota as pq
        for uid, name in users:
            try:
                quota = pq.get_user_quota(device, uid)
                q_dict = quota_tuple_to_dict(quota)
                q_dict["uid"] = uid
                q_dict["name"] = name
                current[uid] = q_dict
            except Exception:
                pass
        return current
    if device == "docker" and config["USE_DOCKER_QUOTA"]:
        from app.docker_quota import docker_collect_remote_quotas
        from app.docker_quota.attribution_store import get_user_quota_limit
        data_root = config.get("DOCKER_DATA_ROOT")
        reserved = config.get("DOCKER_QUOTA_RESERVED_BYTES")
        docker_results = docker_collect_remote_quotas(data_root, reserved)
        for dev in docker_results:
            if dev.get("name") == device:
                for q in dev.get("user_quotas", []):
                    current[q["uid"]] = q
                break
        # Ensure every eligible user has an entry (limit 0 if not in list)
        for uid, name in users:
            if uid not in current:
                limit = get_user_quota_limit(uid)
                current[uid] = {
                    "uid": uid,
                    "name": name,
                    "block_hard_limit": limit,
                    "block_soft_limit": limit,
                    "block_current": 0,
                    "inode_hard_limit": 0,
                    "inode_soft_limit": 0,
                    "inode_current": 0,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                }
        return current
    if config["USE_ZFS"]:
        from app.quota_zfs import collect_remote_quotas as zfs_collect_remote_quotas
        zfs_datasets = config.get("ZFS_DATASETS")
        zfs_results = zfs_collect_remote_quotas(zfs_datasets)
        for dev in zfs_results:
            if dev.get("name") == device:
                for q in dev.get("user_quotas", []):
                    current[q["uid"]] = q
                break
    return current


def _current_usage_bytes(q: dict[str, Any], device_name: str, config: dict[str, Any]) -> int:
    """Return current block usage in bytes. Pyquota reports block_current in 1K blocks; others in bytes."""
    raw = q.get("block_current", 0) or 0
    if device_name.startswith("/dev/") and config.get("USE_PYQUOTA"):
        return int(raw) * 1024
    return int(raw)


def _dynamic_limits_1k(usage_bytes: int) -> tuple[int, int]:
    """Return (soft_1k, hard_1k) from usage in bytes: soft = ceil((usage+1GB)/1GB)*1024^2, hard = ceil((usage+2GB)/1GB)*1024^2."""
    one_gb = 1024**3
    soft_gb = math.ceil((usage_bytes + one_gb) / one_gb)
    hard_gb = math.ceil((usage_bytes + 2 * one_gb) / one_gb)
    blocks_per_gb = 1024 * 1024
    return (soft_gb * blocks_per_gb, hard_gb * blocks_per_gb)


def _all_limits_empty(q: dict[str, Any], device: str, config: dict[str, Any]) -> bool:
    """True if block and inode limits are all 0. For Docker/ZFS only block matters."""
    if device == "docker" or (not device.startswith("/dev/") and config["USE_ZFS"]):
        return (q.get("block_hard_limit", 0) == 0 and q.get("block_soft_limit", 0) == 0)
    return (
        q.get("block_hard_limit", 0) == 0
        and q.get("block_soft_limit", 0) == 0
        and q.get("inode_hard_limit", 0) == 0
        and q.get("inode_soft_limit", 0) == 0
    )


@celery_app.task(name="app.tasks.quota_default_tasks.apply_default_user_quota", bind=True)
def apply_default_user_quota(self: Any) -> dict[str, Any]:
    """For each device with non-empty default quota, find users with all-empty limits and apply the default."""
    config = _load_quota_config()
    devices = get_devices_with_nonempty_default()
    if not devices:
        return {"devices_processed": 0, "total_applied": 0, "by_device": {}}
    users = _get_eligible_users(config["MOCK_QUOTA"])
    total_applied = 0
    by_device: dict[str, dict[str, Any]] = {}
    for dev_default in devices:
        device_name = dev_default["device_name"]
        block_soft = dev_default["block_soft_limit"]
        block_hard = dev_default["block_hard_limit"]
        inode_soft = dev_default["inode_soft_limit"]
        inode_hard = dev_default["inode_hard_limit"]
        current = _get_current_quotas_for_device(device_name, users, config)
        uids_empty: list[int] = []
        for uid, _name in users:
            q = current.get(uid, {})
            if _all_limits_empty(q, device_name, config):
                uids_empty.append(uid)
        if not uids_empty:
            by_device[device_name] = {"applied": 0, "errors": []}
            continue

        soft_bytes = block_soft * 1024
        hard_bytes = block_hard * 1024
        uids_default: list[int] = []
        dynamic_limits: dict[int, tuple[int, int]] = {}  # uid -> (soft_1k, hard_1k)
        for uid in uids_empty:
            q = current.get(uid, {})
            usage_bytes = _current_usage_bytes(q, device_name, config)
            use_default = (
                (block_soft == 0 or usage_bytes < soft_bytes)
                and (block_hard == 0 or usage_bytes < hard_bytes)
            )
            if use_default:
                uids_default.append(uid)
            else:
                soft_1k, hard_1k = _dynamic_limits_1k(usage_bytes)
                dynamic_limits[uid] = (soft_1k, hard_1k)

        errors: list[str] = []
        applied = 0
        if config["MOCK_QUOTA"]:
            from app.quota_mock import set_user_quota_mock
            for uid in uids_default:
                try:
                    set_user_quota_mock(
                        device_name, uid,
                        block_hard, block_soft,
                        inode_hard, inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
            for uid in dynamic_limits:
                soft_1k, hard_1k = dynamic_limits[uid]
                try:
                    set_user_quota_mock(
                        device_name, uid,
                        hard_1k, soft_1k,
                        inode_hard, inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
        elif device_name.startswith("/dev/") and config["USE_PYQUOTA"]:
            import pyquota as pq
            for uid in uids_default:
                try:
                    pq.set_user_quota(
                        device_name, uid,
                        block_hard, block_soft,
                        inode_hard, inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
            for uid in dynamic_limits:
                soft_1k, hard_1k = dynamic_limits[uid]
                try:
                    pq.set_user_quota(
                        device_name, uid,
                        hard_1k, soft_1k,
                        inode_hard, inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
        elif device_name == "docker" and config["USE_DOCKER_QUOTA"]:
            from app.docker_quota.attribution_store import batch_set_user_quota_limits
            uid_limits: dict[int, int] = {}
            for uid in uids_default:
                uid_limits[uid] = block_hard
            for uid in dynamic_limits:
                _soft_1k, hard_1k = dynamic_limits[uid]
                uid_limits[uid] = hard_1k
            try:
                if uid_limits:
                    batch_set_user_quota_limits(uid_limits)
                    applied = len(uid_limits)
            except Exception as e:
                errors.append(str(e))
        elif config["USE_ZFS"]:
            from app.quota_zfs import set_user_quota as zfs_set_user_quota
            for uid in uids_default:
                try:
                    zfs_set_user_quota(
                        dataset=device_name,
                        uid=uid,
                        block_hard_limit=block_hard,
                        block_soft_limit=block_soft,
                        inode_hard_limit=inode_hard,
                        inode_soft_limit=inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
            for uid in dynamic_limits:
                _soft_1k, hard_1k = dynamic_limits[uid]
                try:
                    zfs_set_user_quota(
                        dataset=device_name,
                        uid=uid,
                        block_hard_limit=hard_1k,
                        block_soft_limit=hard_1k,
                        inode_hard_limit=inode_hard,
                        inode_soft_limit=inode_soft,
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {e}")
        else:
            errors.append("backend not enabled for this device")
        total_applied += applied
        by_device[device_name] = {"applied": applied, "errors": errors}
        if applied or errors:
            logger.info(
                "apply_default_user_quota device=%s applied=%d default=%d dynamic=%d errors=%d",
                device_name, applied, len(uids_default), len(dynamic_limits), len(errors),
            )
    return {
        "devices_processed": len(devices),
        "total_applied": total_applied,
        "by_device": by_device,
    }
