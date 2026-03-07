"""Remote API routes: local quota read/set (for slaves)."""

import pwd
import time
from typing import Any

from flask import current_app, request, jsonify
from app.auth import requires_api_key
from app.models import quota_tuple_to_dict, SetUserQuotaRequest, BatchQuotaRequest, BatchQuotaResult
from app.utils import get_logger

logger = get_logger(__name__)


def _merge_quota_results(
    pyquota_results: list[dict[str, Any]],
    use_zfs: bool,
    use_docker_quota: bool,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Merge pyquota, ZFS, and Docker device lists. Sorted by name. Returns (results, timing_dict)."""
    timings: dict[str, float] = {}
    results = list(pyquota_results)
    
    if use_zfs:
        zfs_start = time.time()
        from app.quota_zfs import collect_remote_quotas as zfs_collect_remote_quotas
        zfs_datasets = current_app.config.get("ZFS_DATASETS")
        zfs_results = zfs_collect_remote_quotas(zfs_datasets)
        timings["zfs"] = time.time() - zfs_start
        results = results + zfs_results
        logger.debug("ZFS quota collection took %.2fs (%d devices)", timings["zfs"], len(zfs_results))
    
    if use_docker_quota:
        docker_start = time.time()
        from app.docker_quota import docker_collect_remote_quotas
        data_root = current_app.config.get("DOCKER_DATA_ROOT")
        reserved = current_app.config.get("DOCKER_QUOTA_RESERVED_BYTES")
        docker_results = docker_collect_remote_quotas(data_root, reserved)
        timings["docker"] = time.time() - docker_start
        results = results + docker_results
        logger.debug("Docker quota collection took %.2fs (%d devices)", timings["docker"], len(docker_results))
    
    sort_start = time.time()
    results.sort(key=lambda r: r["name"])
    timings["sort"] = time.time() - sort_start
    
    return results, timings


def _merge_quota_results_for_uid(
    uid: int,
    pyquota_results: list[dict[str, Any]],
    use_zfs: bool,
    use_docker_quota: bool,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Merge pyquota, ZFS, and Docker results for a single user. Sorted by name. Returns (results, timing_dict)."""
    timings: dict[str, float] = {}
    results = list(pyquota_results)
    
    if use_zfs:
        zfs_start = time.time()
        from app.quota_zfs import collect_remote_quotas_for_uid as zfs_collect_remote_quotas_for_uid
        zfs_datasets = current_app.config.get("ZFS_DATASETS")
        zfs_results = zfs_collect_remote_quotas_for_uid(uid, zfs_datasets)
        timings["zfs"] = time.time() - zfs_start
        results = results + zfs_results
        logger.debug("ZFS quota collection for uid=%d took %.2fs (%d devices)", uid, timings["zfs"], len(zfs_results))
    
    if use_docker_quota:
        docker_start = time.time()
        from app.docker_quota import docker_collect_remote_quotas_for_uid
        data_root = current_app.config.get("DOCKER_DATA_ROOT")
        reserved = current_app.config.get("DOCKER_QUOTA_RESERVED_BYTES")
        docker_results = docker_collect_remote_quotas_for_uid(uid, data_root, reserved)
        timings["docker"] = time.time() - docker_start
        results = results + docker_results
        logger.debug("Docker quota collection for uid=%d took %.2fs (%d devices)", uid, timings["docker"], len(docker_results))
    
    sort_start = time.time()
    results.sort(key=lambda r: r["name"])
    timings["sort"] = time.time() - sort_start
    
    return results, timings


def register_remote_api_routes(app: Any) -> None:
    """Register /remote-api/* routes on the Flask app."""

    @app.route("/remote-api/ping")
    @requires_api_key
    def remote_ping() -> Any:
        """Lightweight ping endpoint for health checks. Returns {"status": "ok"}."""
        return jsonify({"status": "ok"})

    @app.route("/remote-api/users")
    @requires_api_key
    def remote_get_users() -> Any:
        """Return list of host user names that have quotas (lightweight, no quota details)."""
        start_time = time.time()
        users: set[str] = set()
        
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import _get_mock_state
            mock_state = _get_mock_state()
            users.update(mock_state["users"].values())
            elapsed = time.time() - start_time
            logger.info("Fetched %d users (mock) in %.2fs", len(users), elapsed)
        else:
            from app.quota_common import should_include_uid
            for entry in pwd.getpwall():
                uid = entry.pw_uid
                if should_include_uid(uid):
                    users.add(entry.pw_name)
        
        result = sorted(list(users))
        total_time = time.time() - start_time
        logger.info("Fetched %d unique users in %.2fs", len(result), total_time)
        return jsonify(result)

    @app.route("/remote-api/users/resolve")
    @requires_api_key
    def remote_resolve_user() -> Any:
        """Resolve username to uid and name. Query param: username=."""
        import urllib.parse
        username = (request.args.get("username") or "").strip()
        if not username:
            return jsonify(msg="username query parameter required"), 400
        username = urllib.parse.unquote(username)
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import _uid_for_username_mock, _get_mock_state
            try:
                uid = _uid_for_username_mock(username)
                users = _get_mock_state()["users"]
                return jsonify({"uid": uid, "name": users.get(uid, username)})
            except KeyError:
                return jsonify(msg=f"user not found: {username}"), 404
        try:
            entry = pwd.getpwnam(username)
            return jsonify({"uid": entry.pw_uid, "name": entry.pw_name})
        except KeyError:
            return jsonify(msg=f"user not found: {username}"), 404

    @app.route("/remote-api/quotas")
    @requires_api_key
    def remote_get_quotas() -> Any:
        start_time = time.time()
        timings: dict[str, float] = {}
        
        if current_app.config.get("MOCK_QUOTA"):
            mock_start = time.time()
            from app.quota_mock import collect_remote_quotas_mock
            results = collect_remote_quotas_mock()
            timings["mock"] = time.time() - mock_start
            logger.info("Fetched all quotas (mock) in %.2fs (%d devices)", timings["mock"], len(results))
        else:
            # ext4-only: pyquota only. ZFS/Docker: merge when enabled.
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results: list[dict[str, Any]] = []
            if use_pyquota:
                pyquota_start = time.time()
                from app.quota import collect_remote_quotas
                pyquota_results = collect_remote_quotas()
                timings["pyquota"] = time.time() - pyquota_start
                logger.debug("Pyquota collection took %.2fs (%d devices)", timings["pyquota"], len(pyquota_results))
            
            merge_start = time.time()
            results, merge_timings = _merge_quota_results(
                pyquota_results,
                current_app.config.get("USE_ZFS", False),
                current_app.config.get("USE_DOCKER_QUOTA", False),
            )
            timings["merge"] = time.time() - merge_start
            timings.update(merge_timings)
        
        total_time = time.time() - start_time
        timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
        logger.info(
            "Fetched all quotas in %.2fs (%d devices) [%s]",
            total_time,
            len(results),
            timing_str,
        )
        return jsonify(results)

    @app.route("/remote-api/quotas/users/<int:uid>")
    @requires_api_key
    def remote_get_quotas_for_user(uid: int) -> Any:
        """Return only devices where this user has a quota (per-user fetch, no full scan)."""
        start_time = time.time()
        timings: dict[str, float] = {}
        
        if current_app.config.get("MOCK_QUOTA"):
            mock_start = time.time()
            from app.quota_mock import collect_remote_quotas_for_uid_mock
            results = collect_remote_quotas_for_uid_mock(uid)
            timings["mock"] = time.time() - mock_start
            logger.info("Fetched quotas for uid=%d (mock) in %.2fs (%d devices)", uid, timings["mock"], len(results))
        else:
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results = []
            if use_pyquota:
                pyquota_start = time.time()
                from app.quota import collect_remote_quotas_for_uid
                pyquota_results = collect_remote_quotas_for_uid(uid)
                timings["pyquota"] = time.time() - pyquota_start
                logger.debug("Pyquota collection for uid=%d took %.2fs (%d devices)", uid, timings["pyquota"], len(pyquota_results))
            
            merge_start = time.time()
            results, merge_timings = _merge_quota_results_for_uid(
                uid,
                pyquota_results,
                current_app.config.get("USE_ZFS", False),
                current_app.config.get("USE_DOCKER_QUOTA", False),
            )
            timings["merge"] = time.time() - merge_start
            timings.update(merge_timings)
        
        total_time = time.time() - start_time
        timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
        logger.info(
            "Fetched quotas for uid=%d in %.2fs (%d devices) [%s]",
            uid,
            total_time,
            len(results),
            timing_str,
        )
        return jsonify(results)

    @app.route("/remote-api/quotas/users/by-name/<username>")
    @requires_api_key
    def remote_get_quotas_for_user_by_name(username: str) -> Any:
        """Return quota for user by Linux username (resolved to uid on this host)."""
        import urllib.parse
        start_time = time.time()
        timings: dict[str, float] = {}
        
        username = urllib.parse.unquote(username)
        logger.debug("Fetching quotas for user=%s", username)
        
        if current_app.config.get("MOCK_QUOTA"):
            resolve_start = time.time()
            from app.quota_mock import _uid_for_username_mock, collect_remote_quotas_for_uid_mock
            try:
                uid = _uid_for_username_mock(username)
                timings["resolve"] = time.time() - resolve_start
            except KeyError:
                elapsed = time.time() - start_time
                logger.warning("User %s not found (mock) (took %.2fs)", username, elapsed)
                return jsonify(msg=f"user not found: {username}"), 404
            
            quota_start = time.time()
            results = collect_remote_quotas_for_uid_mock(uid)
            timings["quota"] = time.time() - quota_start
            logger.info("Fetched quotas for user=%s (mock, uid=%d) in %.2fs (%d devices)", username, uid, timings.get("quota", 0), len(results))
        else:
            resolve_start = time.time()
            try:
                uid = pwd.getpwnam(username).pw_uid
                timings["resolve"] = time.time() - resolve_start
                logger.debug("Resolved user=%s to uid=%d (took %.2fs)", username, uid, timings["resolve"])
            except KeyError:
                elapsed = time.time() - start_time
                logger.warning("User %s not found (took %.2fs)", username, elapsed)
                return jsonify(msg=f"user not found: {username}"), 404
            
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results = []
            if use_pyquota:
                pyquota_start = time.time()
                from app.quota import collect_remote_quotas_for_uid
                pyquota_results = collect_remote_quotas_for_uid(uid)
                timings["pyquota"] = time.time() - pyquota_start
                logger.debug("Pyquota collection for user=%s (uid=%d) took %.2fs (%d devices)", username, uid, timings["pyquota"], len(pyquota_results))
            
            merge_start = time.time()
            results, merge_timings = _merge_quota_results_for_uid(
                uid,
                pyquota_results,
                current_app.config.get("USE_ZFS", False),
                current_app.config.get("USE_DOCKER_QUOTA", False),
            )
            timings["merge"] = time.time() - merge_start
            timings.update(merge_timings)
        
        total_time = time.time() - start_time
        timing_str = ", ".join(f"{k}={v:.2f}s" for k, v in timings.items())
        logger.info(
            "Fetched quotas for user=%s in %.2fs (%d devices) [%s]",
            username,
            total_time,
            len(results),
            timing_str,
        )
        return jsonify(results)

    @app.route("/remote-api/quotas/users/<int:uid>", methods=["PUT"])
    @requires_api_key
    def remote_set_user_quota(uid: int) -> tuple[Any, int] | Any:
        start_time = time.time()
        body = request.get_json(silent=True) or {}
        try:
            params = SetUserQuotaRequest(
                block_hard_limit=body.get("block_hard_limit"),
                block_soft_limit=body.get("block_soft_limit"),
                inode_hard_limit=body.get("inode_hard_limit"),
                inode_soft_limit=body.get("inode_soft_limit"),
            )
        except Exception:
            params = SetUserQuotaRequest()

        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400

        logger.info("Setting quota for uid=%d, device=%s", uid, device)

        if current_app.config.get("MOCK_QUOTA"):
            mock_start = time.time()
            from app.quota_mock import set_user_quota_mock, get_user_quota_mock
            try:
                set_user_quota_mock(
                    device,
                    uid,
                    params.block_hard_limit,
                    params.block_soft_limit,
                    params.inode_hard_limit,
                    params.inode_soft_limit,
                )
                quota_dict = get_user_quota_mock(device, uid)
                elapsed = time.time() - mock_start
                logger.info("Set quota for uid=%d, device=%s (mock) in %.2fs", uid, device, elapsed)
                return jsonify(quota_dict)
            except ValueError as e:
                elapsed = time.time() - start_time
                logger.warning("Failed to set quota for uid=%d, device=%s (mock): %s (took %.2fs)", uid, device, str(e), elapsed)
                return jsonify(msg=str(e)), 500
        else:
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            use_zfs = current_app.config.get("USE_ZFS", False)
            
            # Check Docker virtual device first (before ZFS, since "docker" is not a ZFS dataset)
            if current_app.config.get("USE_DOCKER_QUOTA", False) and device == "docker":
                docker_start = time.time()
                from app.docker_quota import docker_set_user_quota
                try:
                    quota_dict = docker_set_user_quota(
                        uid=uid,
                        block_hard_limit=params.block_hard_limit or 0,
                        block_soft_limit=params.block_soft_limit or 0,
                    )
                    elapsed = time.time() - docker_start
                    logger.info("Set quota for uid=%d, device=%s (Docker) in %.2fs", uid, device, elapsed)
                    return jsonify(quota_dict)
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.warning("Failed to set quota for uid=%d, device=%s (Docker): %s (took %.2fs)", uid, device, str(e), elapsed)
                    return jsonify(msg=str(e)), 500
            
            # Block device (ext4/xfs with usrquota) -> pyquota
            if device.startswith("/dev/"):
                if not use_pyquota:
                    return jsonify(msg="USE_PYQUOTA is disabled; cannot set quota on block device"), 400
                pyquota_start = time.time()
                import pyquota as pq
                try:
                    pq.set_user_quota(
                        device,
                        uid,
                        params.block_hard_limit,
                        params.block_soft_limit,
                        params.inode_hard_limit,
                        params.inode_soft_limit,
                    )
                    quota = pq.get_user_quota(device, uid)
                    quota_dict = quota_tuple_to_dict(quota)
                    quota_dict["uid"] = uid
                    quota_dict["name"] = pwd.getpwuid(uid).pw_name
                    elapsed = time.time() - pyquota_start
                    logger.info("Set quota for uid=%d, device=%s (pyquota) in %.2fs", uid, device, elapsed)
                    return jsonify(quota_dict)
                except pq.APIError as e:
                    elapsed = time.time() - start_time
                    logger.warning("Failed to set quota for uid=%d, device=%s (pyquota): %s (took %.2fs)", uid, device, str(e), elapsed)
                    return jsonify(msg=str(e)), 500
            
            # Dataset name -> ZFS when USE_ZFS
            if use_zfs:
                zfs_start = time.time()
                from app.quota_zfs import set_user_quota as zfs_set_user_quota
                from app.quota_zfs import ZFSQuotaError
                try:
                    quota_dict = zfs_set_user_quota(
                        dataset=device,
                        uid=uid,
                        block_hard_limit=params.block_hard_limit or 0,
                        block_soft_limit=params.block_soft_limit or 0,
                        inode_hard_limit=params.inode_hard_limit,
                        inode_soft_limit=params.inode_soft_limit,
                    )
                    elapsed = time.time() - zfs_start
                    logger.info("Set quota for uid=%d, device=%s (ZFS) in %.2fs", uid, device, elapsed)
                    return jsonify(quota_dict)
                except ZFSQuotaError as e:
                    elapsed = time.time() - start_time
                    logger.warning("Failed to set quota for uid=%d, device=%s (ZFS): %s (took %.2fs)", uid, device, str(e), elapsed)
                    return jsonify(msg=str(e)), 500
            
            elapsed = time.time() - start_time
            logger.warning("Device %s not recognized for uid=%d (took %.2fs)", device, uid, elapsed)
            return jsonify(
                msg="device not recognized: use /dev/... for block devices, USE_ZFS for ZFS datasets, or device=docker when USE_DOCKER_QUOTA is enabled"
            ), 400

    @app.route("/remote-api/docker/containers")
    @requires_api_key
    def remote_get_docker_containers() -> Any:
        """Return detailed Docker container information with attribution."""
        start_time = time.time()
        
        if not current_app.config.get("USE_DOCKER_QUOTA", False):
            return jsonify(msg="Docker quota not enabled on this host"), 400
        
        from app.docker_quota.docker_client import get_container_details, get_system_df
        from app.docker_quota.attribution_store import get_container_attributions
        
        # Get container details from Docker API
        containers = get_container_details()
        container_ids = [c["id"] for c in containers]
        
        # Get container sizes
        df = get_system_df(container_ids=container_ids)
        container_sizes = df.get("containers", {})
        
        # Get attributions from database
        attributions = {a["container_id"]: a for a in get_container_attributions()}
        
        # Merge data
        result_containers = []
        total_bytes = 0
        attributed_bytes = 0
        
        for c in containers:
            cid = c["id"]
            size = container_sizes.get(cid, 0)
            total_bytes += size
            
            att = attributions.get(cid)
            host_user_name = att["host_user_name"] if att else None
            uid = att["uid"] if att else None
            created_at = att["created_at"].isoformat() if att and att.get("created_at") else None
            
            if att:
                attributed_bytes += size
            
            result_containers.append({
                "container_id": cid,
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "status": c.get("status", "unknown"),
                "host_user_name": host_user_name,
                "uid": uid,
                "size_bytes": size,
                "created_at": created_at,
            })
        
        unattributed_bytes = total_bytes - attributed_bytes
        
        elapsed = time.time() - start_time
        logger.info(
            "Docker containers detail: %.2fs (count=%d, total=%d, attributed=%d, unattributed=%d)",
            elapsed, len(result_containers), total_bytes, attributed_bytes, unattributed_bytes
        )
        
        return jsonify({
            "containers": result_containers,
            "total_bytes": total_bytes,
            "attributed_bytes": attributed_bytes,
            "unattributed_bytes": unattributed_bytes,
        })

    @app.route("/remote-api/docker/images")
    @requires_api_key
    def remote_get_docker_images() -> Any:
        """Return detailed Docker image and layer information with attribution.
        
        Returns ALL layers from Docker (not just attributed ones), with attribution
        info merged in where available. This allows the frontend to show both
        attributed and unattributed layers.
        """
        start_time = time.time()
        
        if not current_app.config.get("USE_DOCKER_QUOTA", False):
            return jsonify(msg="Docker quota not enabled on this host"), 400
        
        from app.docker_quota.docker_client import get_image_details, get_image_layers_with_sizes
        from app.docker_quota.attribution_store import get_layer_attributions, get_image_attributions
        
        # Get image details from Docker API
        images = get_image_details()
        
        # Get layer attributions from database (indexed by layer_id for lookup)
        layer_attributions_list = get_layer_attributions()
        layer_attributions_map = {la["layer_id"]: la for la in layer_attributions_list}
        
        # Get image attributions from database (indexed by image_id for lookup)
        image_attributions_list = get_image_attributions()
        image_attributions_map = {ia["image_id"]: ia for ia in image_attributions_list}
        
        # Build images response and collect ALL unique layers from Docker
        result_images = []
        total_image_bytes = 0
        all_layers: dict[str, int] = {}  # layer_id -> size_bytes (deduplicated)
        
        for img in images:
            size = img.get("size_bytes", 0)
            total_image_bytes += size
            
            # Get attribution for this image
            img_att = image_attributions_map.get(img["id"])
            
            result_images.append({
                "image_id": img["id"],
                "tags": img.get("tags", []),
                "size_bytes": size,
                "created": img.get("created"),
                "puller_host_user_name": img_att.get("puller_host_user_name") if img_att else None,
                "puller_uid": img_att.get("puller_uid") if img_att else None,
            })
            
            # Collect layers from this image
            try:
                layers_with_sizes = get_image_layers_with_sizes(img["id"])
                for layer_id, layer_size in layers_with_sizes:
                    if layer_id not in all_layers:
                        all_layers[layer_id] = layer_size
            except Exception as e:
                logger.warning("Failed to get layers for image %s: %s", img["id"][:12], e)
        
        # Build layers response: ALL layers from Docker, with attribution info if available
        result_layers = []
        attributed_layer_bytes = 0
        unattributed_layer_bytes = 0
        layers_by_user: dict[int, int] = {}
        
        for layer_id, size in all_layers.items():
            att = layer_attributions_map.get(layer_id)
            
            if att:
                # Layer has attribution
                attributed_layer_bytes += size
                uid = att.get("first_puller_uid")
                if uid is not None:
                    layers_by_user[uid] = layers_by_user.get(uid, 0) + size
                
                first_seen = att.get("first_seen_at")
                result_layers.append({
                    "layer_id": layer_id,
                    "size_bytes": size,
                    "first_puller_host_user_name": att.get("first_puller_host_user_name"),
                    "first_puller_uid": uid,
                    "creation_method": att.get("creation_method"),
                    "first_seen_at": first_seen.isoformat() if first_seen else None,
                })
            else:
                # Layer has no attribution
                unattributed_layer_bytes += size
                result_layers.append({
                    "layer_id": layer_id,
                    "size_bytes": size,
                    "first_puller_host_user_name": None,
                    "first_puller_uid": None,
                    "creation_method": None,
                    "first_seen_at": None,
                })
        
        # total_layer_bytes is the sum of unique layer sizes
        total_layer_bytes = attributed_layer_bytes + unattributed_layer_bytes
        
        elapsed = time.time() - start_time
        logger.info(
            "Docker images detail: %.2fs (images=%d, layers=%d, total_layer=%d, attributed=%d, unattributed=%d)",
            elapsed, len(result_images), len(result_layers), total_layer_bytes, attributed_layer_bytes, unattributed_layer_bytes
        )
        
        return jsonify({
            "images": result_images,
            "layers": result_layers,
            "total_image_bytes": total_image_bytes,
            "total_layer_bytes": total_layer_bytes,
            "attributed_layer_bytes": attributed_layer_bytes,
            "unattributed_layer_bytes": unattributed_layer_bytes,
            "layers_by_user": {str(k): v for k, v in layers_by_user.items()},
        })

    @app.route("/remote-api/docker/volumes")
    @requires_api_key
    def remote_get_docker_volumes() -> Any:
        """Return detailed Docker volume information with attribution."""
        start_time = time.time()
        
        if not current_app.config.get("USE_DOCKER_QUOTA", False):
            return jsonify(msg="Docker quota not enabled on this host"), 400
        
        from app.docker_quota.docker_client import get_system_df
        from app.docker_quota.attribution_store import get_volume_attributions, get_volume_disk_usage_all, get_volume_last_used_all
        
        # Get volume data from Docker API
        df = get_system_df(include_volumes=True)
        volumes_data = df.get("volumes", {})
        
        # Get attributions, disk usage, and last mounted from database
        attributions = {a["volume_name"]: a for a in get_volume_attributions()}
        disk_usage_list = get_volume_disk_usage_all()
        disk_usage_by_name = {u["volume_name"]: u for u in disk_usage_list}
        last_used_by_name = get_volume_last_used_all()
        
        # Build response
        result_volumes = []
        total_bytes = 0
        attributed_bytes = 0
        
        for vol_name, vol_info in volumes_data.items():
            reported_size = vol_info.get("size", 0)
            disk_usage = disk_usage_by_name.get(vol_name)
            actual_disk_bytes = disk_usage.get("actual_disk_bytes") if disk_usage else None
            size = actual_disk_bytes if actual_disk_bytes is not None else reported_size
            total_bytes += size
            
            att = attributions.get(vol_name)
            host_user_name = att["host_user_name"] if att else None
            uid = att["uid"] if att else None
            attribution_source = att["attribution_source"] if att else None
            first_seen = att.get("first_seen_at") if att else None
            
            if att:
                attributed_bytes += size
            
            def _iso(dt) -> str | None:
                if dt is None:
                    return None
                if hasattr(dt, "isoformat"):
                    return dt.isoformat()
                return str(dt)
            
            last_mounted = last_used_by_name.get(vol_name)
            result_volumes.append({
                "volume_name": vol_name,
                "size_bytes": size,
                "reported_size_bytes": reported_size,
                "actual_disk_bytes": actual_disk_bytes,
                "host_user_name": host_user_name,
                "uid": uid,
                "attribution_source": attribution_source,
                "ref_count": vol_info.get("ref_count", 0),
                "first_seen_at": first_seen.isoformat() if first_seen else None,
                "last_mounted_at": _iso(last_mounted) if last_mounted is not None else None,
                "scan_started_at": _iso(disk_usage.get("scan_started_at")) if disk_usage else None,
                "scan_finished_at": _iso(disk_usage.get("scan_finished_at")) if disk_usage else None,
                "pending_scan_started_at": _iso(disk_usage.get("pending_scan_started_at")) if disk_usage else None,
                "last_scan_started_at": _iso(disk_usage.get("last_scan_started_at")) if disk_usage else None,
                "last_scan_finished_at": _iso(disk_usage.get("last_scan_finished_at")) if disk_usage else None,
                "last_scan_status": disk_usage.get("last_scan_status") if disk_usage else None,
            })
        
        unattributed_bytes = total_bytes - attributed_bytes
        
        elapsed = time.time() - start_time
        logger.info(
            "Docker volumes detail: %.2fs (count=%d, total=%d, attributed=%d, unattributed=%d)",
            elapsed, len(result_volumes), total_bytes, attributed_bytes, unattributed_bytes
        )
        
        return jsonify({
            "volumes": result_volumes,
            "total_bytes": total_bytes,
            "attributed_bytes": attributed_bytes,
            "unattributed_bytes": unattributed_bytes,
        })

    @app.route("/remote-api/quotas/defaults")
    @requires_api_key
    def remote_get_default_quota() -> tuple[Any, int] | Any:
        """Get default user quota for a device. Query param: device=."""
        import urllib.parse
        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400
        device = urllib.parse.unquote(device)
        from app.default_quota_store import get_device_default_quota
        default = get_device_default_quota(device)
        return jsonify(default)

    @app.route("/remote-api/quotas/defaults", methods=["PUT"])
    @requires_api_key
    def remote_set_default_quota() -> tuple[Any, int] | Any:
        """Set default user quota for a device. Query param: device=. Body: block_soft_limit, block_hard_limit, inode_soft_limit, inode_hard_limit (optional, default 0)."""
        import urllib.parse
        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400
        device = urllib.parse.unquote(device)
        body = request.get_json(silent=True) or {}
        try:
            block_soft = int(body.get("block_soft_limit", 0) or 0)
            block_hard = int(body.get("block_hard_limit", 0) or 0)
            inode_soft = int(body.get("inode_soft_limit", 0) or 0)
            inode_hard = int(body.get("inode_hard_limit", 0) or 0)
        except (TypeError, ValueError):
            return jsonify(msg="quota limits must be integers"), 400
        if any(x < 0 for x in (block_soft, block_hard, inode_soft, inode_hard)):
            return jsonify(msg="quota limits must be non-negative"), 400
        from app.default_quota_store import set_device_default_quota
        try:
            result = set_device_default_quota(device, block_soft, block_hard, inode_soft, inode_hard)
            return jsonify(result)
        except Exception as e:
            logger.warning("Failed to set default quota for device=%s: %s", device, e)
            return jsonify(msg=str(e)), 500

    @app.route("/remote-api/quotas/batch", methods=["POST"])
    @requires_api_key
    def remote_set_batch_quota() -> tuple[Any, int] | Any:
        """Apply batch quota to all eligible users on a device."""
        start_time = time.time()
        body = request.get_json(silent=True) or {}
        
        try:
            params = BatchQuotaRequest(**body)
        except Exception as e:
            return jsonify(msg=f"Invalid request: {e}"), 400
        
        device = params.device
        if not device:
            return jsonify(msg="device is required"), 400
        
        logger.info("Batch quota setting for device=%s, preserve_nonzero=%s, preserve_usage_exceeds=%s",
                    device, params.preserve_if_nonzero, params.preserve_if_usage_exceeds)
        
        from app.quota_common import should_include_uid
        
        # Get all eligible users
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import _get_mock_state
            mock_state = _get_mock_state()
            users = [(uid, name) for uid, name in mock_state["users"].items() if should_include_uid(uid)]
        else:
            users = [(entry.pw_uid, entry.pw_name) for entry in pwd.getpwall() if should_include_uid(entry.pw_uid)]
        
        total_users = len(users)
        updated_users = 0
        skipped_users = 0
        errors: list[str] = []
        
        # Get current quotas for the device to check preserve conditions
        current_quotas: dict[int, dict[str, Any]] = {}
        
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import _get_mock_state
            mock_state = _get_mock_state()
            for dev in mock_state.get("devices", {}).values():
                if dev.get("name") == device:
                    for q in dev.get("user_quotas", []):
                        current_quotas[q["uid"]] = q
                    break
        else:
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            use_zfs = current_app.config.get("USE_ZFS", False)
            use_docker = current_app.config.get("USE_DOCKER_QUOTA", False)
            
            if device.startswith("/dev/") and use_pyquota:
                import pyquota as pq
                for uid, name in users:
                    try:
                        quota = pq.get_user_quota(device, uid)
                        q_dict = quota_tuple_to_dict(quota)
                        q_dict["uid"] = uid
                        q_dict["name"] = name
                        current_quotas[uid] = q_dict
                    except Exception:
                        pass
            elif device == "docker" and use_docker:
                from app.docker_quota import docker_collect_remote_quotas
                data_root = current_app.config.get("DOCKER_DATA_ROOT")
                reserved = current_app.config.get("DOCKER_QUOTA_RESERVED_BYTES")
                docker_results = docker_collect_remote_quotas(data_root, reserved)
                for dev in docker_results:
                    if dev.get("name") == device:
                        for q in dev.get("user_quotas", []):
                            current_quotas[q["uid"]] = q
                        break
            elif use_zfs:
                from app.quota_zfs import collect_remote_quotas as zfs_collect_remote_quotas
                zfs_datasets = current_app.config.get("ZFS_DATASETS")
                zfs_results = zfs_collect_remote_quotas(zfs_datasets)
                for dev in zfs_results:
                    if dev.get("name") == device:
                        for q in dev.get("user_quotas", []):
                            current_quotas[q["uid"]] = q
                        break
        
        # First pass: determine which users to update vs skip
        uids_to_update: list[int] = []
        for uid, name in users:
            current = current_quotas.get(uid, {})
            
            # Check preserve conditions
            should_skip = False
            
            if params.preserve_if_nonzero:
                # Skip if any current limit is non-zero
                if (current.get("block_hard_limit", 0) > 0 or 
                    current.get("block_soft_limit", 0) > 0 or
                    current.get("inode_hard_limit", 0) > 0 or
                    current.get("inode_soft_limit", 0) > 0):
                    should_skip = True
            
            if params.preserve_if_usage_exceeds and not should_skip:
                # Skip if current usage exceeds new default (block_current is in bytes, limits are in 1K blocks)
                block_current_kb = current.get("block_current", 0) / 1024
                if params.block_hard_limit is not None and block_current_kb > params.block_hard_limit:
                    should_skip = True
                elif params.block_soft_limit is not None and block_current_kb > params.block_soft_limit:
                    should_skip = True
            
            if should_skip:
                skipped_users += 1
            else:
                uids_to_update.append(uid)
        
        # Second pass: apply quotas (use batch for Docker, loop for others)
        if device == "docker" and current_app.config.get("USE_DOCKER_QUOTA", False) and uids_to_update:
            # Use optimized batch function for Docker
            from app.docker_quota import docker_batch_set_user_quota
            try:
                uid_limits = {uid: params.block_hard_limit or 0 for uid in uids_to_update}
                docker_batch_set_user_quota(uid_limits)
                updated_users = len(uids_to_update)
            except Exception as e:
                errors.append(f"Docker batch error: {str(e)}")
        else:
            # Apply quota to each user individually
            for uid in uids_to_update:
                try:
                    if current_app.config.get("MOCK_QUOTA"):
                        from app.quota_mock import set_user_quota_mock
                        set_user_quota_mock(
                            device, uid,
                            params.block_hard_limit, params.block_soft_limit,
                            params.inode_hard_limit, params.inode_soft_limit,
                        )
                    elif device.startswith("/dev/"):
                        import pyquota as pq
                        pq.set_user_quota(
                            device, uid,
                            params.block_hard_limit, params.block_soft_limit,
                            params.inode_hard_limit, params.inode_soft_limit,
                        )
                    elif current_app.config.get("USE_ZFS", False):
                        from app.quota_zfs import set_user_quota as zfs_set_user_quota
                        zfs_set_user_quota(
                            dataset=device,
                            uid=uid,
                            block_hard_limit=params.block_hard_limit or 0,
                            block_soft_limit=params.block_soft_limit or 0,
                            inode_hard_limit=params.inode_hard_limit,
                            inode_soft_limit=params.inode_soft_limit,
                        )
                    else:
                        errors.append(f"uid={uid}: device not recognized")
                        continue
                    updated_users += 1
                except Exception as e:
                    errors.append(f"uid={uid}: {str(e)}")
        
        result = BatchQuotaResult(
            total_users=total_users,
            updated_users=updated_users,
            skipped_users=skipped_users,
            errors=errors,
        )
        
        elapsed = time.time() - start_time
        logger.info(
            "Batch quota completed for device=%s in %.2fs: total=%d, updated=%d, skipped=%d, errors=%d",
            device, elapsed, total_users, updated_users, skipped_users, len(errors)
        )
        
        return jsonify(result.model_dump())
