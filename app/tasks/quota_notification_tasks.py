"""Celery task: scan non-Docker disk quotas and emit notification events to master."""

import os
import time
from typing import Any, Dict, List, Tuple

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models_db import DiskQuotaNotificationState
from app.quota_common import should_include_uid
from app.utils import get_logger

logger = get_logger(__name__)


_DEFAULT_GRACE_ALERT_WINDOW_SECONDS = 86400  # 24 hours


def _load_quota_config() -> dict[str, Any]:
    """Reuse quota config loading from quota_default_tasks (without importing Celery there)."""
    from app.tasks.quota_default_tasks import _load_quota_config as _inner_load_quota_config

    return _inner_load_quota_config()


def _load_slave_identity() -> Tuple[str, str, str]:
    """Load host_id, master_url, secret from CONFIG_PATH or env (reuse docker_quota_tasks logic)."""
    from app.tasks.docker_quota_tasks import _load_slave_config

    host_id, master_url, secret, _order = _load_slave_config()
    return host_id, master_url, secret


def _collect_non_docker_user_quotas(config: dict[str, Any]) -> List[dict[str, Any]]:
    """Collect user quotas for all non-Docker devices (pyquota + ZFS or mock)."""
    devices: list[dict[str, Any]] = []

    if config.get("MOCK_QUOTA"):
        from app.quota_mock import collect_remote_quotas_mock

        devices = collect_remote_quotas_mock()
    else:
        if config.get("USE_PYQUOTA", True):
            from app.quota import collect_remote_quotas

            devices.extend(collect_remote_quotas())
        if config.get("USE_ZFS", False):
            from app.quota_zfs import collect_remote_quotas as zfs_collect_remote_quotas

            zfs_datasets = config.get("ZFS_DATASETS")
            devices.extend(zfs_collect_remote_quotas(zfs_datasets))

    # Explicitly skip Docker virtual device if present
    return [d for d in devices if d.get("name") != "docker"]


def _compute_status_for_quota(
    quota: Dict[str, Any],
    device: Dict[str, Any],
    now_ts: int,
    grace_alert_window: int,
) -> Tuple[str, int | None, int | None]:
    """Return (status, block_time_limit, inode_time_limit) for one user quota on a device."""
    block_soft = int(quota.get("block_soft_limit", 0) or 0)
    block_hard = int(quota.get("block_hard_limit", 0) or 0)
    block_current = int(quota.get("block_current", 0) or 0)

    inode_soft = int(quota.get("inode_soft_limit", 0) or 0)
    inode_hard = int(quota.get("inode_hard_limit", 0) or 0)
    inode_current = int(quota.get("inode_current", 0) or 0)

    block_time_limit = int(quota.get("block_time_limit", 0) or 0)
    inode_time_limit = int(quota.get("inode_time_limit", 0) or 0)

    over_soft_block = block_soft > 0 and block_current >= block_soft * 1024
    over_soft_inode = inode_soft > 0 and inode_current >= inode_soft
    over_hard_block = block_hard > 0 and block_current >= block_hard * 1024
    over_hard_inode = inode_hard > 0 and inode_current >= inode_hard

    over_soft = over_soft_block or over_soft_inode
    over_hard = over_hard_block or over_hard_inode

    if not over_soft and not over_hard:
        return "ok", block_time_limit or None, inode_time_limit or None
    if over_hard:
        return "hard_over", block_time_limit or None, inode_time_limit or None

    # Soft over: inspect grace
    # Device-level grace durations (seconds) are informative but we mostly care about absolute end.
    block_grace = int((device.get("user_quota_info") or {}).get("block_grace", 0) or 0)
    inode_grace = int((device.get("user_quota_info") or {}).get("inode_grace", 0) or 0)

    # Choose the earliest non-zero grace end among block/inode
    grace_end_candidates: list[int] = []
    if block_time_limit > 0:
        grace_end_candidates.append(block_time_limit)
    if inode_time_limit > 0:
        grace_end_candidates.append(inode_time_limit)

    if not grace_end_candidates:
        # No grace timestamps available but over soft: treat as expired for safety
        return "soft_over_grace_expired", None, None

    grace_end = min(grace_end_candidates)
    seconds_until_end = grace_end - now_ts

    effective_window = min(
        grace_alert_window,
        max(block_grace, inode_grace) or grace_alert_window,
    )

    if seconds_until_end <= 0:
        return "soft_over_grace_expired", block_time_limit or None, inode_time_limit or None
    if seconds_until_end <= effective_window:
        return "soft_over_grace_ending", block_time_limit or None, inode_time_limit or None
    return "soft_over_in_grace", block_time_limit or None, inode_time_limit or None


def _determine_event_type(previous: str | None, current: str) -> str | None:
    """Map a (previous_status, current_status) pair to a notification event_type."""
    prev = previous or "ok"

    if prev == "ok" and current in ("soft_over_in_grace", "soft_over_grace_ending"):
        return "disk_soft_limit_exceeded"
    if prev == "soft_over_in_grace" and current == "soft_over_grace_ending":
        return "disk_soft_grace_ending"
    if prev in ("soft_over_in_grace", "soft_over_grace_ending") and current == "soft_over_grace_expired":
        return "disk_soft_grace_expired"
    if current == "hard_over" and prev != "hard_over":
        return "disk_hard_limit_reached"
    if prev in ("soft_over_in_grace", "soft_over_grace_ending", "soft_over_grace_expired", "hard_over") and current == "ok":
        return "disk_back_to_ok"
    return None


def _post_events_to_master(events: List[Dict[str, Any]], host_id: str, master_url: str, secret: str) -> None:
    """Reuse existing helper from docker_quota_tasks for POSTing events to master."""
    from app.tasks.docker_quota_tasks import _post_events_to_master as _inner_post

    _inner_post(events, host_id, master_url, secret)


@celery_app.task(
    name="app.tasks.quota_notification_tasks.scan_disk_quota_notifications",
    bind=True,
)
def scan_disk_quota_notifications(self: Any) -> dict[str, Any]:
    """Scan non-Docker disk quotas, detect state transitions, and emit events to master."""
    config = _load_quota_config()
    host_id, master_url, secret = _load_slave_identity()
    grace_alert_window = int(
        os.environ.get("QUOTA_NOTIFICATION_GRACE_ALERT_WINDOW_SECONDS", _DEFAULT_GRACE_ALERT_WINDOW_SECONDS)
    )

    devices = _collect_non_docker_user_quotas(config)
    if not devices:
        return {"devices": 0, "users": 0, "events": 0}

    now_ts = int(time.time())
    db = SessionLocal()

    # Load existing state
    existing_rows = db.query(DiskQuotaNotificationState).all()
    state_by_key: Dict[Tuple[str, int], DiskQuotaNotificationState] = {
        (row.device_name, row.uid): row for row in existing_rows
    }

    events: list[dict[str, Any]] = []
    users_seen: set[Tuple[str, int]] = set()

    try:
        for device in devices:
            device_name = device.get("name") or ""
            user_quotas = device.get("user_quotas") or []
            if isinstance(user_quotas, dict):
                # quota_mock uses dict keyed by uid
                items = user_quotas.items()
            else:
                # list of quota dicts with uid/name
                items = [(q.get("uid"), q) for q in user_quotas]

            for uid, q in items:
                if uid is None:
                    uid = int(q.get("uid", -1))
                if not should_include_uid(int(uid)):
                    continue
                key = (device_name, int(uid))
                users_seen.add(key)

                status, block_time_limit, inode_time_limit = _compute_status_for_quota(
                    q,
                    device,
                    now_ts,
                    grace_alert_window,
                )
                prev_row = state_by_key.get(key)
                prev_status = prev_row.last_status if prev_row else None
                event_type = _determine_event_type(prev_status, status)

                # Update or create state row
                if prev_row is None:
                    prev_row = DiskQuotaNotificationState(
                        device_name=device_name,
                        uid=int(uid),
                        last_status=status,
                        last_block_time_limit=block_time_limit,
                        last_inode_time_limit=inode_time_limit,
                    )
                    db.add(prev_row)
                    state_by_key[key] = prev_row
                else:
                    prev_row.last_status = status
                    prev_row.last_block_time_limit = block_time_limit
                    prev_row.last_inode_time_limit = inode_time_limit

                if not event_type:
                    continue

                host_user_name = q.get("name") or f"user_{uid}"
                detail = {
                    "uid": int(uid),
                    "device_name": device_name,
                    "block_current": int(q.get("block_current", 0) or 0),
                    "block_soft_limit": int(q.get("block_soft_limit", 0) or 0),
                    "block_hard_limit": int(q.get("block_hard_limit", 0) or 0),
                    "inode_current": int(q.get("inode_current", 0) or 0),
                    "inode_soft_limit": int(q.get("inode_soft_limit", 0) or 0),
                    "inode_hard_limit": int(q.get("inode_hard_limit", 0) or 0),
                    "block_time_limit": block_time_limit,
                    "inode_time_limit": inode_time_limit,
                    "user_quota_info": device.get("user_quota_info"),
                }
                events.append(
                    {
                        "host_user_name": host_user_name,
                        "event_type": event_type,
                        "detail": detail,
                    }
                )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if events:
        _post_events_to_master(events, host_id, master_url, secret)

    return {"devices": len(devices), "users": len(users_seen), "events": len(events)}

