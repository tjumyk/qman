"""Remote API routes: local quota read/set (for slaves)."""

import pwd
from typing import Any

import pyquota as pq

from flask import current_app, request, jsonify
from app.auth import requires_api_key
from app.quota import collect_remote_quotas, collect_remote_quotas_for_uid
from app.models import quota_tuple_to_dict, SetUserQuotaRequest


def register_remote_api_routes(app: Any) -> None:
    """Register /remote-api/* routes on the Flask app."""

    @app.route("/remote-api/quotas")
    @requires_api_key
    def remote_get_quotas() -> Any:
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import collect_remote_quotas_mock
            results = collect_remote_quotas_mock()
        else:
            results = collect_remote_quotas()
        return jsonify(results)

    @app.route("/remote-api/quotas/users/<int:uid>")
    @requires_api_key
    def remote_get_quotas_for_user(uid: int) -> Any:
        """Return only devices where this user has a quota (per-user fetch, no full scan)."""
        if current_app.config.get("MOCK_QUOTA"):
            from app.quota_mock import collect_remote_quotas_for_uid_mock
            results = collect_remote_quotas_for_uid_mock(uid)
        else:
            results = collect_remote_quotas_for_uid(uid)
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
