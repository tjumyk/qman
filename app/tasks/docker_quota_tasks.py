"""Celery task: enforce Docker quota (stop/remove containers when over limit) and emit events to master."""

import json
import os
from typing import Any

import requests

from app.celery_app import celery_app
from app.docker_quota.attribution_store import (
    get_container_attributions,
    get_all_user_quota_limits,
    delete_container_attribution,
)
from app.docker_quota.docker_client import (
    get_system_df,
    list_containers,
    stop_container,
    remove_container,
    _parse_created_iso,
)
from app.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_ORDER = "newest_first"
_VALID_ORDERS = ("newest_first", "oldest_first", "largest_first")


def _load_slave_config() -> tuple[str, str, str, str]:
    """Load host_id, master_url, secret, enforcement_order from CONFIG_PATH (default config.json) or env. Returns (host_id, url, secret, order)."""
    host_id = os.environ.get("SLAVE_HOST_ID", "slave")
    master_url = os.environ.get("MASTER_EVENT_CALLBACK_URL", "")
    secret = os.environ.get("MASTER_EVENT_CALLBACK_SECRET", "")
    order = os.environ.get("DOCKER_QUOTA_ENFORCEMENT_ORDER", _DEFAULT_ORDER)
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            host_id = data.get("SLAVE_HOST_ID") or host_id
            master_url = data.get("MASTER_EVENT_CALLBACK_URL") or master_url
            secret = data.get("MASTER_EVENT_CALLBACK_SECRET") or secret
            order = data.get("DOCKER_QUOTA_ENFORCEMENT_ORDER") or order
        except Exception as e:
            logger.warning("Could not load config from %s: %s", config_path, e)
    if order not in _VALID_ORDERS:
        order = _DEFAULT_ORDER
    return host_id, master_url, secret, order


def _containers_by_uid_with_created(
    order: str,
) -> dict[int, list[tuple[str, int, float]]]:
    """Return {uid: [(container_id, size_bytes, created_ts), ...]} sorted by order (newest_first, oldest_first, largest_first)."""
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    containers_list = list_containers(all_containers=True)
    cid_to_created: dict[str, float] = {}
    for c in containers_list:
        cid_to_created[c["id"]] = _parse_created_iso(c.get("created"))
    attributions = get_container_attributions()
    uid_to_containers: dict[int, list[tuple[str, int, float]]] = {}
    for att in attributions:
        uid = att.get("uid")
        if uid is None:
            try:
                import pwd
                uid = pwd.getpwnam(att["host_user_name"]).pw_uid
            except KeyError:
                continue
        cid = att["container_id"]
        size = container_sizes.get(cid, 0)
        created = cid_to_created.get(cid, 0.0)
        uid_to_containers.setdefault(uid, []).append((cid, size, created))
    for uid in uid_to_containers:
        lst = uid_to_containers[uid]
        if order == "newest_first":
            lst.sort(key=lambda x: -x[2])  # created desc
        elif order == "oldest_first":
            lst.sort(key=lambda x: x[2])  # created asc
        else:  # largest_first
            lst.sort(key=lambda x: -x[1])  # size desc
    return uid_to_containers


def _post_events_to_master(events: list[dict[str, Any]], host_id: str, master_url: str, secret: str) -> None:
    """POST events to master callback URL. No-op if url/secret not set."""
    if not master_url or not secret:
        logger.debug("Master event callback not configured; skipping POST")
        return
    url = master_url.rstrip("/") + "/api/internal/slave-events"
    try:
        resp = requests.post(
            url,
            json={"host_id": host_id, "events": events},
            headers={"X-API-Key": secret, "Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code // 100 != 2:
            logger.warning("Master event callback returned %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Master event callback failed: %s", e)


@celery_app.task(name="app.tasks.docker_quota_tasks.enforce_docker_quota", bind=True)
def enforce_docker_quota(self: Any) -> dict[str, Any]:
    """For each user with Docker quota, if over limit (container + image layer usage), stop and remove containers until under. Emit events to master."""
    host_id, master_url, secret, order = _load_slave_config()
    limits = get_all_user_quota_limits()
    if not limits:
        return {"enforced": 0, "events": 0}
    # Get total usage per uid (containers + image layers)
    from app.docker_quota.quota import _aggregate_usage_by_uid
    usage_by_uid, _total_used, _unattributed = _aggregate_usage_by_uid(None, None)
    uid_to_containers = _containers_by_uid_with_created(order)
    events: list[dict[str, Any]] = []
    total_removed = 0
    for uid, limit_1k in limits.items():
        if limit_1k <= 0:
            continue
        limit_bytes = limit_1k * 1024
        # Total usage includes containers + image layers
        total_used = usage_by_uid.get(uid, 0)
        if total_used <= limit_bytes:
            continue
        events.append({
            "host_user_name": None,
            "event_type": "quota_exceeded",
            "detail": {"uid": uid, "block_current": total_used, "block_hard_limit": limit_1k},
        })
        try:
            import pwd
            events[-1]["host_user_name"] = pwd.getpwuid(uid).pw_name
        except KeyError:
            events[-1]["host_user_name"] = f"user_{uid}"
        removed: list[str] = []
        containers = uid_to_containers.get(uid, [])
        for cid, size, _created in containers:
            # Recompute total_used after each removal (includes image layers)
            current_usage_by_uid, _, _ = _aggregate_usage_by_uid(None, None)
            current_total_used = current_usage_by_uid.get(uid, 0)
            if current_total_used <= limit_bytes:
                break
            logger.info(
                "Enforcing Docker quota: stopping then removing container %s (uid=%s, container_size=%s, total_usage=%s)",
                cid[:12], uid, size, current_total_used,
            )
            if stop_container(cid):
                if remove_container(cid, force=True):
                    delete_container_attribution(cid)
                    # Recompute after removal
                    updated_usage_by_uid, _, _ = _aggregate_usage_by_uid(None, None)
                    new_total_used = updated_usage_by_uid.get(uid, 0)
                    total_removed += 1
                    removed.append(cid)
                    events.append({
                        "host_user_name": events[-1]["host_user_name"],
                        "event_type": "container_removed",
                        "detail": {"container_id": cid[:12], "size_bytes": size, "new_usage": new_total_used},
                    })
                    logger.info(
                        "Container %s removed due to quota; uid=%s new_usage=%s (includes image layers)",
                        cid[:12], uid, new_total_used,
                    )
        if removed:
            events[-1]["detail"]["removed_ids"] = removed
    if events:
        _post_events_to_master(events, host_id, master_url, secret)
    return {"enforced": total_removed, "events": len(events)}


@celery_app.task(name="app.tasks.docker_quota_tasks.sync_docker_attribution", bind=True)
def sync_docker_attribution(self: Any) -> dict[str, int]:
    """Sync container/image attribution from audit logs and Docker events (container create, image pull)."""
    from app.docker_quota.attribution_sync import run_sync_docker_attribution
    return run_sync_docker_attribution()
