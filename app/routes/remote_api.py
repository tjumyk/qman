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
            # Block device (ext4/xfs with usrquota) -> pyquota; dataset name -> ZFS when USE_ZFS
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
            elapsed = time.time() - start_time
            logger.warning("Device %s not recognized for uid=%d (took %.2fs)", device, uid, elapsed)
            return jsonify(
                msg="device not recognized: use /dev/... for block devices, USE_ZFS for ZFS datasets, or device=docker when USE_DOCKER_QUOTA is enabled"
            ), 400
