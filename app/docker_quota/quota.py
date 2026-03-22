"""Docker virtual device and user quota reporting (same shape as quota.py / quota_zfs)."""

import pwd
import time
from typing import Any

from app.docker_quota.attribution_store import (
    get_container_attributions,
    get_container_effective_attributions,
    set_container_attribution,
    delete_container_attribution,
    get_image_attributions,
    delete_image_attribution,
    get_volume_attributions,
    get_volume_effective_attributions,
    delete_volume_attribution,
    get_volume_disk_usage_all,
    get_user_quota_limit,
    set_user_quota_limit,
    batch_set_user_quota_limits,
    get_all_user_quota_limits,
    get_layer_attributions,
    get_layer_effective_attributions,
    delete_layer_attribution,
)
from app.docker_quota.docker_client import (
    get_docker_data_root,
    list_containers,
    list_images,
    get_system_df,
)
from app.quota_common import (
    build_name_to_uid_from_container_attributions,
    resolve_uid_for_docker_attribution,
    should_include_uid,
)
from app.utils import get_logger

logger = get_logger(__name__)


def _user_quota_dict_docker(
    uid: int,
    used_bytes: int,
    block_hard_limit_1k: int,
    *,
    docker_breakdown: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build UserQuota-shaped dict for Docker (inode/time = 0).

    Optional docker_breakdown: container / image layer / volume bytes attributed to this uid
    (for UI breakdown on My usage).
    """
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = f"user_{uid}"
    out: dict[str, Any] = {
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
    if docker_breakdown is not None:
        out["docker_container_bytes"] = int(docker_breakdown.get("container_bytes", 0))
        out["docker_image_layer_bytes"] = int(docker_breakdown.get("image_layer_bytes", 0))
        out["docker_volume_bytes"] = int(docker_breakdown.get("volume_bytes", 0))
    return out


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


def _reconcile_layer_attributions(layers_from_docker: set[str]) -> int:
    """Remove layer attribution rows for layers that no longer exist in any Docker image.
    
    Args:
        layers_from_docker: Set of layer IDs that exist in Docker (from all images).
    
    Returns:
        Number of layer attributions removed.
    """
    layer_attributions = get_layer_attributions()
    removed_count = 0
    for layer_att in layer_attributions:
        layer_id = layer_att["layer_id"]
        if layer_id not in layers_from_docker:
            delete_layer_attribution(layer_id)
            removed_count += 1
            logger.info("Removed attribution for gone layer %s (was attributed to uid=%s)", 
                       layer_id[:12], layer_att.get("first_puller_uid"))
    return removed_count


def _reconcile_image_attributions(image_ids_from_docker: set[str]) -> int:
    """Remove image attribution rows for images that no longer exist in Docker.
    
    Args:
        image_ids_from_docker: Set of image IDs that exist in Docker.
    
    Returns:
        Number of image attributions removed.
    """
    image_attributions = get_image_attributions()
    removed_count = 0
    for img_att in image_attributions:
        image_id = img_att["image_id"]
        if image_id not in image_ids_from_docker:
            delete_image_attribution(image_id)
            removed_count += 1
            logger.info("Removed attribution for gone image %s (was attributed to uid=%s)", 
                       image_id[:12], img_att.get("puller_uid"))
    return removed_count


def _reconcile_volume_attributions(volume_names_from_docker: set[str]) -> int:
    """Remove volume attribution rows for volumes that no longer exist in Docker.
    
    Args:
        volume_names_from_docker: Set of volume names that exist in Docker.
    
    Returns:
        Number of volume attributions removed.
    """
    volume_attributions = get_volume_attributions()
    removed_count = 0
    for vol_att in volume_attributions:
        volume_name = vol_att["volume_name"]
        if volume_name not in volume_names_from_docker:
            delete_volume_attribution(volume_name)
            removed_count += 1
            logger.info("Removed attribution for gone volume %s (was attributed to uid=%s)", 
                       volume_name, vol_att.get("uid"))
    return removed_count


def _aggregate_usage_by_uid(
    data_root: str,
    reserved_bytes: int | None,
    container_ids: list[str] | None = None,
    use_cache: bool = False,
) -> tuple[dict[int, int], int, int, dict[int, dict[str, int]]]:
    """Aggregate Docker disk usage per uid.

    Returns (uid -> used_bytes, total_used, unattributed_bytes, uid -> breakdown).
    Breakdown keys: container_bytes, image_layer_bytes, volume_bytes (sum == used per uid).
    total_used = sum of all container sizes + sum of all image layer sizes + sum of all volume sizes; 
    usage_by_uid = container usage + image layer usage + volume usage (where user is attributed);
    unattributed = total_used - sum(usage_by_uid).
    
    Args:
        container_ids: Deprecated/ignored. Previously used to optimize get_system_df(), but get_system_df()
                       now uses a single df() API call that returns all data efficiently.
        use_cache: If True, read df from Redis when valid; if False, force live df (still write-through).
            Default False so background paths get a live read unless they opt into cache reuse.
    """
    start_time = time.time()
    timings: dict[str, float] = {}
    
    df_start = time.time()
    df = get_system_df(container_ids=container_ids, include_volumes=True, use_cache=use_cache)
    timings["get_system_df"] = time.time() - df_start
    
    container_sizes = df.get("containers") or {}
    image_sizes = df.get("images") or {}
    volume_data = df.get("volumes") or {}
    
    attrib_start = time.time()
    attributions = get_container_effective_attributions()
    layer_attributions = get_layer_effective_attributions()
    volume_attributions = get_volume_effective_attributions()
    volume_disk_usage_list = get_volume_disk_usage_all()
    volume_disk_usage_by_name = {u["volume_name"]: u for u in volume_disk_usage_list}
    timings["get_attributions"] = time.time() - attrib_start
    
    build_map_start = time.time()
    cid_to_user: dict[str, tuple[str, int | None]] = {}
    for att in attributions:
        cid_to_user[att["container_id"]] = (att["host_user_name"], att.get("uid"))
    name_to_uid = build_name_to_uid_from_container_attributions(attributions)
    timings["build_maps"] = time.time() - build_map_start
    
    # Container usage
    container_agg_start = time.time()
    usage_by_uid: dict[int, int] = {}
    container_by_uid: dict[int, int] = {}
    total_container_used = 0
    for cid, size in container_sizes.items():
        total_container_used += size
        user = cid_to_user.get(cid)
        if not user:
            continue
        _name, uid = user
        uid_res = resolve_uid_for_docker_attribution(uid, _name, name_to_uid)
        if uid_res is not None:
            usage_by_uid[uid_res] = usage_by_uid.get(uid_res, 0) + size
            container_by_uid[uid_res] = container_by_uid.get(uid_res, 0) + size
    timings["container_aggregation"] = time.time() - container_agg_start
    
    # Image layer usage (first creator owns the layer)
    # total_image_used = ALL images from Docker (for total calculation)
    # attributed_layer_used = only layers with attribution (for user breakdown)
    layer_agg_start = time.time()
    total_image_used = sum(image_sizes.values())  # All Docker images
    layer_by_uid: dict[int, int] = {}
    attributed_layer_used = 0
    for layer_att in layer_attributions:
        layer_size = layer_att.get("size_bytes", 0)
        attributed_layer_used += layer_size
        uid = resolve_uid_for_docker_attribution(
            layer_att.get("first_puller_uid"),
            layer_att.get("first_puller_host_user_name"),
            name_to_uid,
        )
        if uid is not None:
            usage_by_uid[uid] = usage_by_uid.get(uid, 0) + layer_size
            layer_by_uid[uid] = layer_by_uid.get(uid, 0) + layer_size
    timings["layer_aggregation"] = time.time() - layer_agg_start
    
    # Volume usage: effective size = actual_disk_bytes from scan if present, else Docker-reported size
    volume_agg_start = time.time()
    total_volume_used = 0
    attributed_volume_used = 0
    vol_att_by_name = {att["volume_name"]: att for att in volume_attributions}
    volume_by_uid: dict[int, int] = {}
    for vol_name, vol_info in volume_data.items():
        reported_size = vol_info.get("size", 0)
        disk_usage = volume_disk_usage_by_name.get(vol_name)
        actual_bytes = disk_usage.get("actual_disk_bytes") if disk_usage else None
        vol_size = actual_bytes if actual_bytes is not None else reported_size
        total_volume_used += vol_size
        vol_att = vol_att_by_name.get(vol_name)
        if vol_att:
            attributed_volume_used += vol_size
            uid = resolve_uid_for_docker_attribution(
                vol_att.get("uid"),
                vol_att.get("host_user_name"),
                name_to_uid,
            )
            if uid is not None:
                usage_by_uid[uid] = usage_by_uid.get(uid, 0) + vol_size
                volume_by_uid[uid] = volume_by_uid.get(uid, 0) + vol_size
    timings["volume_aggregation"] = time.time() - volume_agg_start
    
    # Total used = containers (all) + images (all from Docker) + volumes (all)
    # Attributed = containers (with attribution) + layers (with attribution) + volumes (with attribution)
    # Unattributed = total - attributed
    total_used = total_container_used + total_image_used + total_volume_used
    attributed_sum = sum(usage_by_uid.values())
    unattributed_bytes = max(0, total_used - attributed_sum)
    
    total_time = time.time() - start_time
    timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
    logger.info(
        "Docker _aggregate_usage_by_uid: total=%.2fs [%s] "
        "(container_count=%d, container_bytes=%d, image_count=%d, image_bytes=%d, "
        "attributed_layers=%d, attributed_layer_bytes=%d, "
        "volume_count=%d, volume_bytes=%d, attributed_volume_bytes=%d, "
        "total_used=%d, attributed=%d, unattributed=%d, users_with_usage=%d)",
        total_time, timing_str,
        len(container_sizes), total_container_used,
        len(image_sizes), total_image_used,
        len(layer_attributions), attributed_layer_used,
        len(volume_data), total_volume_used, attributed_volume_used,
        total_used, attributed_sum, unattributed_bytes, len(usage_by_uid)
    )
    breakdown_uids = (
        set(usage_by_uid.keys())
        | set(container_by_uid.keys())
        | set(layer_by_uid.keys())
        | set(volume_by_uid.keys())
    )
    breakdown_by_uid: dict[int, dict[str, int]] = {}
    for u in breakdown_uids:
        breakdown_by_uid[u] = {
            "container_bytes": container_by_uid.get(u, 0),
            "image_layer_bytes": layer_by_uid.get(u, 0),
            "volume_bytes": volume_by_uid.get(u, 0),
        }
    return usage_by_uid, total_used, unattributed_bytes, breakdown_by_uid


def get_devices(
    data_root: str | None = None,
    reserved_bytes: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Return one virtual Docker device. Semantics:
    - If DOCKER_QUOTA_RESERVED_BYTES set: total=reserved, used=attributed, free=max(0, total - attributed - unattributed) in [0,total], percent=(total-free)/total in [0,100].
    - If not set: total=sum(user quota limits in bytes)+unattributed, used=attributed, free=max(0, total - attributed - unattributed), percent=(total-free)/total in [0,100].
    """
    root = data_root or get_docker_data_root()
    containers = list_containers(all_containers=True)
    container_ids = [c["id"] for c in containers]
    usage_by_uid, total_used, unattributed, _bd = _aggregate_usage_by_uid(
        root, reserved_bytes, container_ids=container_ids
    )
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
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Build list with one Docker device and user_quotas (same shape as quota.collect_remote_quotas).
    
    Args:
        use_cache: If True (default), use cached df() results for faster frontend response.
                   Background tasks should pass False for accurate enforcement/sync.
    """
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
    container_ids = [c["id"] for c in containers]
    aggregate_start = time.time()
    usage_by_uid, total_used, unattributed_bytes, breakdown_by_uid = _aggregate_usage_by_uid(
        root, reserved_bytes, container_ids=container_ids, use_cache=use_cache
    )
    timings["aggregate_usage"] = time.time() - aggregate_start
    
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
        user_quotas.append(
            _user_quota_dict_docker(
                uid, used, limit_1k, docker_breakdown=breakdown_by_uid.get(uid)
            )
        )
    timings["build_user_quotas"] = time.time() - build_quotas_start
    
    if reserved_bytes is not None and reserved_bytes > 0:
        total = reserved_bytes
        used = attributed + unattributed_bytes
        free = max(0, total - attributed - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
        logger.info(
            "Docker device total: mode=reserved_bytes, total=%d, attributed=%d, unattributed=%d, free=%d",
            total, attributed, unattributed_bytes, free
        )
    else:
        sum_quotas_bytes = sum(limit_1k * 1024 for limit_1k in limits.values())
        total = max(sum_quotas_bytes + unattributed_bytes, 1)
        used = attributed + unattributed_bytes
        free = max(0, total - attributed - unattributed_bytes)
        percent = ((total - free) / total * 100.0) if total else 0.0
        logger.info(
            "Docker device total: mode=sum_quotas, sum_quotas_bytes=%d (from %d user limits), unattributed=%d, total=%d, attributed=%d, free=%d",
            sum_quotas_bytes, len(limits), unattributed_bytes, total, attributed, free
        )
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
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Return Docker device only if this user has usage or quota (same shape as quota.collect_remote_quotas_for_uid).
    
    Args:
        use_cache: If True (default), use cached df() results for faster frontend response.
    """
    if not should_include_uid(uid):
        return []
    root = data_root or get_docker_data_root()
    containers = list_containers(all_containers=True)
    container_ids = [c["id"] for c in containers]
    usage_by_uid, total_used, unattributed_bytes, breakdown_by_uid = _aggregate_usage_by_uid(
        root, reserved_bytes, container_ids=container_ids, use_cache=use_cache
    )
    attributed_total = sum(usage_by_uid.values())
    used = usage_by_uid.get(uid, 0)
    limit_1k = get_user_quota_limit(uid)
    if used == 0 and limit_1k == 0:
        return []
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
    quota_dict = _user_quota_dict_docker(
        uid, used, limit_1k, docker_breakdown=breakdown_by_uid.get(uid)
    )
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
    containers = list_containers(all_containers=True)
    container_ids = [c["id"] for c in containers]
    usage_by_uid, _total, _unattributed, breakdown_by_uid = _aggregate_usage_by_uid(
        None, None, container_ids=container_ids, use_cache=True
    )
    used = usage_by_uid.get(uid, 0)
    return _user_quota_dict_docker(
        uid, used, block_hard_limit, docker_breakdown=breakdown_by_uid.get(uid)
    )


def batch_set_user_quota(uid_limits: dict[int, int]) -> list[dict[str, Any]]:
    """Set Docker quota for multiple uids at once (1K blocks). More efficient than calling set_user_quota in a loop.
    
    Args:
        uid_limits: dict mapping uid -> block_hard_limit (in 1K blocks)
    
    Returns:
        List of UserQuota-shaped dicts for all updated users
    """
    if not uid_limits:
        return []
    
    start_time = time.time()
    
    # Step 1: Set all limits in the database at once
    batch_set_user_quota_limits(uid_limits)
    
    # Step 2: Calculate usage once for all users (reuse df cache from collect in same batch request)
    containers = list_containers(all_containers=True)
    container_ids = [c["id"] for c in containers]
    usage_by_uid, _total, _unattributed, breakdown_by_uid = _aggregate_usage_by_uid(
        None, None, container_ids=container_ids, use_cache=True
    )

    # Step 3: Build result for each uid
    results = []
    for uid, block_hard_limit in uid_limits.items():
        used = usage_by_uid.get(uid, 0)
        results.append(
            _user_quota_dict_docker(
                uid, used, block_hard_limit, docker_breakdown=breakdown_by_uid.get(uid)
            )
        )
    
    elapsed = time.time() - start_time
    logger.info("Docker batch_set_user_quota: %d users in %.2fs", len(uid_limits), elapsed)
    
    return results
