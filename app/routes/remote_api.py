"""Remote API routes: local quota read/set (for slaves)."""

import pwd
from typing import Any

from flask import current_app, request, jsonify
from app.auth import requires_api_key
from app.models import quota_tuple_to_dict, SetUserQuotaRequest


def _merge_quota_results(pyquota_results: list[dict[str, Any]], use_zfs: bool) -> list[dict[str, Any]]:
    """Merge pyquota device list with ZFS dataset list when USE_ZFS is true. Sorted by name."""
    results = list(pyquota_results)
    if use_zfs:
        from app.quota_zfs import collect_remote_quotas as zfs_collect_remote_quotas
        zfs_datasets = current_app.config.get("ZFS_DATASETS")
        results = results + zfs_collect_remote_quotas(zfs_datasets)
    results.sort(key=lambda r: r["name"])
    return results


def _merge_quota_results_for_uid(uid: int, pyquota_results: list[dict[str, Any]], use_zfs: bool) -> list[dict[str, Any]]:
    """Merge pyquota and ZFS results for a single user. Sorted by name."""
    results = list(pyquota_results)
    if use_zfs:
        from app.quota_zfs import collect_remote_quotas_for_uid as zfs_collect_remote_quotas_for_uid
        zfs_datasets = current_app.config.get("ZFS_DATASETS")
        results = results + zfs_collect_remote_quotas_for_uid(uid, zfs_datasets)
    results.sort(key=lambda r: r["name"])
    return results


def register_remote_api_routes(app: Any) -> None:
    """Register /remote-api/* routes on the Flask app."""

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
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import collect_remote_quotas_mock
            results = collect_remote_quotas_mock()
        else:
            # ext4-only: pyquota only. ZFS-only: pyquota=[], ZFS list. Mixed: both.
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results: list[dict[str, Any]] = []
            if use_pyquota:
                from app.quota import collect_remote_quotas
                pyquota_results = collect_remote_quotas()
            results = _merge_quota_results(pyquota_results, current_app.config.get("USE_ZFS", False))
        return jsonify(results)

    @app.route("/remote-api/quotas/users/<int:uid>")
    @requires_api_key
    def remote_get_quotas_for_user(uid: int) -> Any:
        """Return only devices where this user has a quota (per-user fetch, no full scan)."""
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import collect_remote_quotas_for_uid_mock
            results = collect_remote_quotas_for_uid_mock(uid)
        else:
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results = []
            if use_pyquota:
                from app.quota import collect_remote_quotas_for_uid
                pyquota_results = collect_remote_quotas_for_uid(uid)
            results = _merge_quota_results_for_uid(uid, pyquota_results, current_app.config.get("USE_ZFS", False))
        return jsonify(results)

    @app.route("/remote-api/quotas/users/by-name/<username>")
    @requires_api_key
    def remote_get_quotas_for_user_by_name(username: str) -> Any:
        """Return quota for user by Linux username (resolved to uid on this host)."""
        import urllib.parse
        username = urllib.parse.unquote(username)
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import _uid_for_username_mock, collect_remote_quotas_for_uid_mock
            try:
                uid = _uid_for_username_mock(username)
            except KeyError:
                return jsonify(msg=f"user not found: {username}"), 404
            results = collect_remote_quotas_for_uid_mock(uid)
        else:
            try:
                uid = pwd.getpwnam(username).pw_uid
            except KeyError:
                return jsonify(msg=f"user not found: {username}"), 404
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            pyquota_results = []
            if use_pyquota:
                from app.quota import collect_remote_quotas_for_uid
                pyquota_results = collect_remote_quotas_for_uid(uid)
            results = _merge_quota_results_for_uid(uid, pyquota_results, current_app.config.get("USE_ZFS", False))
        return jsonify(results)

    @app.route("/remote-api/quotas/users/<int:uid>", methods=["PUT"])
    @requires_api_key
    def remote_set_user_quota(uid: int) -> tuple[Any, int] | Any:
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

        if current_app.config.get("MOCK_QUOTA"):
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
                return jsonify(quota_dict)
            except ValueError as e:
                return jsonify(msg=str(e)), 500
        else:
            use_pyquota = current_app.config.get("USE_PYQUOTA", True)
            use_zfs = current_app.config.get("USE_ZFS", False)
            # Block device (ext4/xfs with usrquota) -> pyquota; dataset name -> ZFS when USE_ZFS
            if device.startswith("/dev/"):
                if not use_pyquota:
                    return jsonify(msg="USE_PYQUOTA is disabled; cannot set quota on block device"), 400
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
                    return jsonify(quota_dict)
                except pq.APIError as e:
                    return jsonify(msg=str(e)), 500
            if use_zfs:
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
                    return jsonify(quota_dict)
                except ZFSQuotaError as e:
                    return jsonify(msg=str(e)), 500
            return jsonify(
                msg="device not recognized: use /dev/... for block devices, or set USE_ZFS=true for ZFS datasets"
            ), 400
