"""Docker virtual device and user quota reporting (same shape as quota.py / quota_zfs)."""

import pwd
import time
from typing import Any

from app.docker_quota.attribution_store import (
    get_container_attributions,
    set_container_attribution,
    delete_container_attribution,
    get_user_quota_limit,
    set_user_quota_limit,
    get_all_user_quota_limits,
    get_layer_attributions,
)
from app.docker_quota.docker_client import (
    get_docker_data_root,
    list_containers,
    list_images,
    get_system_df,
)
from app.quota_common import should_include_uid
from app.utils import get_logger

logger = get_logger(__name__)


def _user_quota_dict_docker(
    uid: int,
    used_bytes: int,
    block_hard_limit_1k: int,
) -> dict[str, Any]:
    """Build UserQuota-shaped dict for Docker (inode/time = 0)."""
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = f"user_{uid}"
    return {
        "uid": uid,
        "name": name,
        "block_hard_limit": block_hard_limit_1k,
        "block_soft_limit": block_hard_limit_1k,
        "block_current": used_bytes,
        "inode_hard_limit": 0,
        "inode_soft_limit": 0,
        "inode_current": 0,
        "block_time_limit": 0,
        "inode_time_limit": 0,
    }


def _reconcile_attributions(
    container_ids_from_docker: set[str],
    host_user_by_uid: dict[int, str],
) -> None:
    """Remove attribution rows for containers that no longer exist. Optionally backfill from labels."""
    attributions = get_container_attributions()
    for att in attributions:
        cid = att["container_id"]
        if cid not in container_ids_from_docker:
            delete_container_attribution(cid)
            logger.info("Removed attribution for gone container %s", cid[:12])


def _aggregate_usage_by_uid(
    data_root: str,
    reserved_bytes: int | None,
    container_ids: list[str] | None = None,
) -> tuple[dict[int, int], int, int]:
    """Aggregate Docker disk usage per uid. Returns (uid -> used_bytes, total_used, unattributed_bytes).
    total_used = sum of all container sizes + sum of all image layer sizes; 
    usage_by_uid = container usage + image layer usage (where user is first creator);
    unattributed = total_used - sum(usage_by_uid).
    
    Args:
        container_ids: Optional list of container IDs to avoid duplicate list_containers() call in get_system_df().
    """
    start_time = time.time()
    timings: dict[str, float] = {}
    
    df_start = time.time()
    df = get_system_df(container_ids=container_ids)
    timings["get_system_df"] = time.time() - df_start
    
    container_sizes = df.get("containers") or {}
    image_sizes = df.get("images") or {}
    
    attrib_start = time.time()
    attributions = get_container_attributions()
    layer_attributions = get_layer_attributions()
    timings["get_attributions"] = time.time() - attrib_start
    
    build_map_start = time.time()
    cid_to_user: dict[str, tuple[str, int | None]] = {}
    for att in attributions:
        cid_to_user[att["container_id"]] = (att["host_user_name"], att.get("uid"))
    name_to_uid: dict[str, int] = {}
    for att in attributions:
        name = att["host_user_name"]
        if name not in name_to_uid and att.get("uid") is not None:
            name_to_uid[name] = att["uid"]
    for att in attributions:
        name = att["host_user_name"]
        if name in name_to_uid:
            continue
        try:
            entry = pwd.getpwnam(name)
            name_to_uid[name] = entry.pw_uid
        except KeyError:
            pass
    timings["build_maps"] = time.time() - build_map_start
    
    # Container usage
    container_agg_start = time.time()
    usage_by_uid: dict[int, int] = {}
    total_container_used = 0
    for cid, size in container_sizes.items():
        total_container_used += size
        user = cid_to_user.get(cid)
        if not user:
            continue
        _name, uid = user
        if uid is not None:
            usage_by_uid[uid] = usage_by_uid.get(uid, 0) + size
        elif _name in name_to_uid:
            u = name_to_uid[_name]
            usage_by_uid[u] = usage_by_uid.get(u, 0) + size
    timings["container_aggregation"] = time.time() - container_agg_start
    
    # Image layer usage (first creator owns the layer)
    layer_agg_start = time.time()
    total_layer_used = 0
    for layer_att in layer_attributions:
        layer_size = layer_att.get("size_bytes", 0)
        total_layer_used += layer_size
        uid = layer_att.get("first_puller_uid")
        if uid is not None:
            usage_by_uid[uid] = usage_by_uid.get(uid, 0) + layer_size
    timings["layer_aggregation"] = time.time() - layer_agg_start
    
    # Total used = containers + image layers
    total_used = total_container_used + total_layer_used
    attributed_sum = sum(usage_by_uid.values())
    unattributed_bytes = max(0, total_used - attributed_sum)
    
    total_time = time.time() - start_time
    timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
    logger.debug(
        "Docker _aggregate_usage_by_uid: total=%.2fs [%s] (containers=%d, layers=%d, users=%d)",
        total_time, timing_str, len(container_sizes), len(layer_attributions), len(usage_by_uid)
    )
    return usage_by_uid, total_used, unattributed_bytes


def get_devices(
    data_root: str | None = None,
    reserved_bytes: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Return one virtual Docker device. Semantics:
    - If DOCKER_QUOTA_RESERVED_BYTES set: total=reserved, used=attributed, free=max(0, total - attributed - unattributed) in [0,total], percent=(total-free)/total in [0,100].
    - If not set: total=sum(user quota limits in bytes)+unattributed, used=attributed, free=max(0, total - attributed - unattributed), percent=(total-free)/total in [0,100].
    """
    root = data_root or get_docker_data_root()
    usage_by_uid, total_used, unattributed = _aggregate_usage_by_uid(root, reserved_bytes)
    attributed = sum(usage_by_uid.values())
    if reserved_bytes is not None and reserved_bytes > 0:
        total = reserved_bytes
        used = attributed
        free = max(0, total - attributed - unattributed)
        percent = ((total - free) / total * 100.0) if total else 0.0
    else:
        limits = get_all_user_quota_limits()
        sum_quotas_bytes = sum(limit_1k * 1024 for limit_1k in limits.values())
        total = max(sum_quotas_bytes + unattributed, 1)
        used = attributed
        free = max(0, total - attributed - unattributed)
        percent = ((total - free) / total * 100.0) if total else 0.0
    dev: dict[str, Any] = {
        "name": "docker",
        "mount_points": [root],
        "fstype": "docker",
        "opts": ["docker"],
        "usage": {"used": used, "total": total, "free": free, "percent": round(percent, 1)},
    }
    if unattributed > 0:
        dev["unattributed_usage"] = unattributed
    return {"docker": dev}


def collect_remote_quotas(
    data_root: str | None = None,
    reserved_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Build list with one Docker device and user_quotas (same shape as quota.collect_remote_quotas)."""
    start_time = time.time()
    timings: dict[str, float] = {}
    
    list_start = time.time()
    containers = list_containers(all_containers=True)
    timings["list_containers"] = time.time() - list_start
    
    container_ids = {c["id"] for c in containers}
    host_user_by_uid: dict[int, str] = {}
    
    reconcile_start = time.time()
    _reconcile_attributions(container_ids, host_user_by_uid)
    timings["reconcile_attributions"] = time.time() - reconcile_start
    
    # Ensure every container has an attribution when label present (backfill from labels)
    backfill_start = time.time()
    attributions_by_cid = {a["container_id"]: a for a in get_container_attributions()}
    backfill_count = 0
    for c in containers:
        cid = c["id"]
        if cid in attributions_by_cid:
            continue
        labels = c.get("labels") or {}
        qman_user = labels.get("qman.user")
        if qman_user:
            try:
                uid = pwd.getpwnam(qman_user).pw_uid
            except KeyError:
                uid = None
            set_container_attribution(cid, qman_user, uid, c.get("image"), 0)
            backfill_count += 1
    timings["backfill_labels"] = time.time() - backfill_start
    
    root = data_root or get_docker_data_root()
    # Pass container IDs to avoid duplicate list_containers() call in get_system_df()
    container_ids = [c["id"] for c in containers]
    usage_by_uid, total_used, unattributed_bytes = _aggregate_usage_by_uid(root, reserved_bytes, container_ids=container_ids)
    
    build_quotas_start = time.time()
    attributed = sum(usage_by_uid.values())
    limits = get_all_user_quota_limits()
    uids = set(limits.keys()) | set(usage_by_uid.keys())
    user_quotas: list[dict[str, Any]] = []
    for uid in sorted(uids):
        if not should_include_uid(uid):
            continue
        used = usage_by_uid.get(uid, 0)
        limit_1k = limits.get(uid, 0)
        user_quotas.append(_user_quota_dict_docker(uid, used, limit_1k))
    timings["build_user_quotas"] = time.time() - build_quotas_start
    
    if reserved_bytes is not None and reserved_bytes > 0:
        total = reserved_bytes
        used = attributed
        free = max(0, total - attributed - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
    else:
        sum_quotas_bytes = sum(limit_1k * 1024 for limit_1k in limits.values())
        total = max(sum_quotas_bytes + unattributed_bytes, 1)
        used = attributed
        free = max(0, total - attributed - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
    device: dict[str, Any] = {
        "name": "docker",
        "mount_points": [root],
        "fstype": "docker",
        "opts": ["docker"],
        "usage": {"used": used, "total": total, "free": free, "percent": round(percent, 1)},
        "user_quota_format": "docker",
        "user_quotas": user_quotas,
    }
    if unattributed_bytes > 0:
        device["unattributed_usage"] = unattributed_bytes
    
    total_time = time.time() - start_time
    timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
    logger.info(
        "Docker collect_remote_quotas: total=%.2fs [%s] (containers=%d, users=%d, backfilled=%d)",
        total_time, timing_str, len(containers), len(user_quotas), backfill_count
    )
    return [device]


def collect_remote_quotas_for_uid(
    uid: int,
    data_root: str | None = None,
    reserved_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Return Docker device only if this user has usage or quota (same shape as quota.collect_remote_quotas_for_uid)."""
    if not should_include_uid(uid):
        return []
    usage_by_uid, total_used, unattributed_bytes = _aggregate_usage_by_uid(
        data_root or get_docker_data_root(), reserved_bytes
    )
    attributed_total = sum(usage_by_uid.values())
    used = usage_by_uid.get(uid, 0)
    limit_1k = get_user_quota_limit(uid)
    if used == 0 and limit_1k == 0:
        return []
    root = data_root or get_docker_data_root()
    if reserved_bytes is not None and reserved_bytes > 0:
        total = reserved_bytes
        free = max(0, total - attributed_total - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
    else:
        limits_all = get_all_user_quota_limits()
        sum_quotas_bytes = sum(l * 1024 for l in limits_all.values())
        total = max(sum_quotas_bytes + unattributed_bytes, 1)
        free = max(0, total - attributed_total - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
    quota_dict = _user_quota_dict_docker(uid, used, limit_1k)
    device: dict[str, Any] = {
        "name": "docker",
        "mount_points": [root],
        "fstype": "docker",
        "opts": ["docker"],
        "usage": {"used": attributed_total, "total": total, "free": free, "percent": round(percent, 1)},
        "user_quota_format": "docker",
        "user_quotas": [quota_dict],
    }
    if unattributed_bytes > 0:
        device["unattributed_usage"] = unattributed_bytes
    return [device]


def set_user_quota(uid: int, block_hard_limit: int, block_soft_limit: int) -> dict[str, Any]:
    """Set Docker quota for uid (1K blocks). Ignores inode. Returns updated UserQuota-shaped dict."""
    set_user_quota_limit(uid, block_hard_limit)
    usage_by_uid, _total, _unattributed = _aggregate_usage_by_uid(None, None)
    used = usage_by_uid.get(uid, 0)
    return _user_quota_dict_docker(uid, used, block_hard_limit)
