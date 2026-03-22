"""Celery task: enforce Docker quota by stopping containers when over limit; emit events to master."""

import json
import os
from typing import Any

import requests

from app.celery_app import celery_app
from app.docker_quota.attribution_store import (
    get_container_effective_attributions,
    get_all_user_quota_limits,
)
from app.docker_quota.docker_client import (
    get_system_df,
    list_containers,
    stop_container,
    _parse_created_iso,
)
from app.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_ORDER = "newest_first"
_VALID_ORDERS = ("newest_first", "oldest_first", "largest_first")


def _load_slave_config() -> tuple[str, str, str, str]:
    """Load host_id, master_url, secret, enforcement_order from CONFIG_PATH or env."""
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


def _container_status_may_run_workloads(status: str | None) -> bool:
    """True if the container might still be executing or holding resources worth stopping."""
    s = (status or "").strip().lower()
    if not s:
        return True
    if s in ("exited", "dead", "created"):
        return False
    return True


def _containers_by_uid_with_created(
    order: str,
    containers_list: list[dict[str, Any]] | None = None,
) -> dict[int, list[tuple[str, int, float]]]:
    """Return {uid: [(container_id, size_bytes, created_ts), ...]} sorted by order (newest_first, oldest_first, largest_first).
    If containers_list is provided, use it and pass container_ids to get_system_df to avoid duplicate list_containers."""
    if containers_list is not None:
        container_ids = [c["id"] for c in containers_list]
        df = get_system_df(container_ids=container_ids, use_cache=True)
    else:
        containers_list = list_containers(all_containers=True, use_cache=False)
        df = get_system_df(use_cache=False)
    container_sizes = df.get("containers") or {}
    cid_to_created: dict[str, float] = {}
    for c in containers_list:
        cid_to_created[c["id"]] = _parse_created_iso(c.get("created"))
    attributions = get_container_effective_attributions()
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
            timeout=60,
        )
        if resp.status_code // 100 != 2:
            logger.warning("Master event callback returned %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Master event callback failed: %s", e)


@celery_app.task(name="app.tasks.docker_quota_tasks.enforce_docker_quota", bind=True)
def enforce_docker_quota(self: Any) -> dict[str, Any]:
    """For each user over Docker quota: stop at most one running container per uid per run (no rm). Emit events."""
    host_id, master_url, secret, order = _load_slave_config()
    limits = get_all_user_quota_limits()
    if not limits:
        return {"enforced": 0, "containers_stopped": 0, "events": 0}
    from app.docker_quota.quota import _aggregate_usage_by_uid

    containers_list = list_containers(all_containers=True, use_cache=False)
    container_ids = [c["id"] for c in containers_list]
    usage_by_uid, _total_used, _unattributed = _aggregate_usage_by_uid(
        None, None, container_ids=container_ids, use_cache=False
    )
    uid_to_containers = _containers_by_uid_with_created(order, containers_list=containers_list)
    events: list[dict[str, Any]] = []
    total_stopped = 0
    for uid, limit_1k in limits.items():
        if limit_1k <= 0:
            continue
        containers_list = list_containers(all_containers=True, use_cache=True)
        limit_bytes = limit_1k * 1024
        total_used = usage_by_uid.get(uid, 0)
        if total_used <= limit_bytes:
            continue
        events.append(
            {
                "host_user_name": None,
                "event_type": "docker_quota_exceeded",
                "detail": {"uid": uid, "block_current": total_used, "block_hard_limit": limit_1k},
            }
        )
        try:
            import pwd

            events[-1]["host_user_name"] = pwd.getpwuid(uid).pw_name
        except KeyError:
            events[-1]["host_user_name"] = f"user_{uid}"
        stopped: list[str] = []
        containers = uid_to_containers.get(uid, [])
        cid_to_status = {c["id"]: c.get("status", "") for c in containers_list}

        # Stopping does not reduce qman's attributed usage (RW + image layers). One stop per uid per beat.
        current_total_used = total_used
        for cid, size, _created in containers:
            if not _container_status_may_run_workloads(cid_to_status.get(cid)):
                continue
            logger.info(
                "Enforcing Docker quota: stopping container %s (uid=%s, container_size=%s, total_usage=%s)",
                cid[:12],
                uid,
                size,
                current_total_used,
            )
            if stop_container(cid):
                total_stopped += 1
                stopped.append(cid)
                events.append(
                    {
                        "host_user_name": events[-1]["host_user_name"],
                        "event_type": "docker_container_stopped",
                        "detail": {
                            "container_id": cid[:12],
                            "size_bytes": size,
                            "block_current": current_total_used,
                            "block_hard_limit": limit_1k,
                        },
                    }
                )
                logger.info(
                    "Stopped container %s for quota; uid=%s attributed usage unchanged in model",
                    cid[:12],
                    uid,
                )
                break
        if stopped:
            events[-1]["detail"]["stopped_ids"] = stopped
        elif total_used > limit_bytes:
            logger.warning(
                "Docker quota: uid=%s over limit but no running/stoppable containers in enforcement list",
                uid,
            )
    if events:
        _post_events_to_master(events, host_id, master_url, secret)
    return {"enforced": total_stopped, "containers_stopped": total_stopped, "events": len(events)}


@celery_app.task(
    name="app.tasks.docker_quota_tasks.sync_docker_attribution",
    bind=True,
    time_limit=300,
    soft_time_limit=240,
)
def sync_docker_attribution(self: Any) -> dict[str, int]:
    """Sync container/image attribution from audit logs and Docker events (container create, image pull)."""
    from app.docker_quota.attribution_sync import run_sync_docker_attribution

    return run_sync_docker_attribution()


@celery_app.task(
    name="app.tasks.docker_quota_tasks.sync_volume_actual_disk",
    bind=True,
    time_limit=14400,
    soft_time_limit=12600,
)
def sync_volume_actual_disk(self: Any) -> dict[str, int]:
    """Collect actual disk usage of all Docker volumes via du -sb (low I/O priority, disk-wise parallelism)."""
    from app.docker_quota.volume_actual_disk import collect_volume_actual_disk

    return collect_volume_actual_disk()
