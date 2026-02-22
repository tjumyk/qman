"""Remote API routes: local quota read/set (for slaves)."""

import pwd
import time
from typing import Any

from flask import current_app, request, jsonify
from app.auth import requires_api_key
from app.models import quota_tuple_to_dict, SetUserQuotaRequest
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
        """Return detailed Docker image and layer information with attribution."""
        start_time = time.time()
        
        if not current_app.config.get("USE_DOCKER_QUOTA", False):
            return jsonify(msg="Docker quota not enabled on this host"), 400
        
        from app.docker_quota.docker_client import get_image_details
        from app.docker_quota.attribution_store import get_layer_attributions
        
        # Get image details from Docker API
        images = get_image_details()
        
        # Get layer attributions from database
        layer_attributions = get_layer_attributions()
        
        # Build images response
        result_images = []
        total_image_bytes = 0
        
        for img in images:
            size = img.get("size_bytes", 0)
            total_image_bytes += size
            result_images.append({
                "image_id": img["id"],
                "tags": img.get("tags", []),
                "size_bytes": size,
                "created": img.get("created"),
            })
        
        # Build layers response with attribution
        result_layers = []
        attributed_layer_bytes = 0
        layers_by_user: dict[int, int] = {}
        
        for layer in layer_attributions:
            size = layer.get("size_bytes", 0)
            uid = layer.get("first_puller_uid")
            
            attributed_layer_bytes += size
            if uid is not None:
                layers_by_user[uid] = layers_by_user.get(uid, 0) + size
            
            first_seen = layer.get("first_seen_at")
            result_layers.append({
                "layer_id": layer["layer_id"],
                "size_bytes": size,
                "first_puller_host_user_name": layer.get("first_puller_host_user_name"),
                "first_puller_uid": uid,
                "creation_method": layer.get("creation_method"),
                "first_seen_at": first_seen.isoformat() if first_seen else None,
            })
        
        # Note: total_image_bytes is sum of image sizes (which includes shared layers counted multiple times)
        # attributed_layer_bytes is sum of unique layer sizes that have attribution
        # unattributed = layers that exist but have no attribution entry
        unattributed_layer_bytes = max(0, total_image_bytes - attributed_layer_bytes)
        
        elapsed = time.time() - start_time
        logger.info(
            "Docker images detail: %.2fs (images=%d, layers=%d, total=%d, attributed=%d, unattributed=%d)",
            elapsed, len(result_images), len(result_layers), total_image_bytes, attributed_layer_bytes, unattributed_layer_bytes
        )
        
        return jsonify({
            "images": result_images,
            "layers": result_layers,
            "total_image_bytes": total_image_bytes,
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
        from app.docker_quota.attribution_store import get_volume_attributions
        
        # Get volume data from Docker API
        df = get_system_df(include_volumes=True)
        volumes_data = df.get("volumes", {})
        
        # Get attributions from database
        attributions = {a["volume_name"]: a for a in get_volume_attributions()}
        
        # Build response
        result_volumes = []
        total_bytes = 0
        attributed_bytes = 0
        
        for vol_name, vol_info in volumes_data.items():
            size = vol_info.get("size", 0)
            total_bytes += size
            
            att = attributions.get(vol_name)
            host_user_name = att["host_user_name"] if att else None
            uid = att["uid"] if att else None
            attribution_source = att["attribution_source"] if att else None
            first_seen = att.get("first_seen_at") if att else None
            
            if att:
                attributed_bytes += size
            
            result_volumes.append({
                "volume_name": vol_name,
                "size_bytes": size,
                "host_user_name": host_user_name,
                "uid": uid,
                "attribution_source": attribution_source,
                "ref_count": vol_info.get("ref_count", 0),
                "first_seen_at": first_seen.isoformat() if first_seen else None,
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
