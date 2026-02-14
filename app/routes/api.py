"""Master API routes: aggregate quotas from slaves, set user quota on slave."""

import urllib.parse
from typing import Any

import requests
from flask import current_app, jsonify, request

_REMOTE_API_TIMEOUT = 3  # seconds


def make_auth(slave: dict[str, Any]) -> tuple[str, str]:
    """Return (username, password) for slave HTTP Basic auth."""
    return "api", slave["api_key"]


def _fetch_all_quotas() -> dict[str, Any]:
    """Fetch aggregated quotas from all slaves. Returns { host_id: { results: [...] } or { error: {...} } }."""
    results: dict[str, Any] = {}
    for slave in current_app.config["SLAVES"]:
        slave_id = slave["id"]
        slave_url = slave["url"]
        try:
            resp = requests.get(
                f"{slave_url}/remote-api/quotas",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT,
            )
            if resp.status_code // 100 != 2:
                results[slave_id] = {"error": resp.json()}
            else:
                results[slave_id] = {"results": resp.json()}
        except OSError as e:
            results[slave_id] = {"error": {"msg": str(e)}}
    return results


def _filter_quotas_for_uid(host_quotas: dict[str, Any], uid: int) -> dict[str, Any]:
    """Filter host-level quota data to only devices where the user has a quota, and only that user's entry."""
    out: dict[str, Any] = {}
    for host_id, payload in host_quotas.items():
        if "error" in payload:
            out[host_id] = payload
            continue
        devices = payload.get("results") or []
        filtered_devices = []
        for dev in devices:
            user_quotas = dev.get("user_quotas") or []
            mine = [q for q in user_quotas if q.get("uid") == uid]
            if not mine:
                continue
            dev_copy = {k: v for k, v in dev.items() if k != "user_quotas"}
            dev_copy["user_quotas"] = mine
            filtered_devices.append(dev_copy)
        out[host_id] = {"results": filtered_devices}
    return out


def register_api_routes(app: Any) -> None:
    """Register /api/* routes on the Flask app (requires app for config and oauth)."""
    from auth_connect import oauth

    @app.route("/api/me")
    @oauth.requires_login
    def get_me() -> tuple[Any, int] | Any:
        try:
            user = oauth.get_user()
        except Exception:
            user = None
        uid = oauth.get_uid()
        if user is not None:
            is_admin = any(
                getattr(g, "name", None) == "admin" for g in (getattr(user, "groups", None) or [])
            )
            return jsonify({"uid": user.id, "name": user.name, "is_admin": is_admin})
        if uid is not None:
            return jsonify({"uid": uid, "name": f"user_{uid}", "is_admin": False})
        return jsonify(msg="user info required"), 401

    @app.route("/api/me/quotas")
    @oauth.requires_login
    def get_me_quotas() -> tuple[Any, int] | Any:
        uid = oauth.get_uid()
        if uid is None:
            return jsonify(msg="user info required"), 401
        raw = _fetch_all_quotas()
        filtered = _filter_quotas_for_uid(raw, uid)
        return jsonify(filtered)

    @app.route("/api/quotas")
    @oauth.requires_login
    def get_quotas() -> tuple[Any, int] | Any:
        return jsonify(_fetch_all_quotas())

    @app.route("/api/quotas/<string:slave_id>/users/<int:uid>", methods=["PUT"])
    @oauth.requires_admin
    def set_user_quota(slave_id: str, uid: int) -> tuple[Any, int]:
        slave = None
        for _slave in current_app.config["SLAVES"]:
            if _slave["id"] == slave_id:
                slave = _slave
                break

        if not slave:
            return jsonify(msg="slave not found"), 404

        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400

        try:
            url = f"{slave['url']}/remote-api/quotas/users/{uid}?device={urllib.parse.quote(device)}"
            resp = requests.put(
                url,
                json=request.get_json(silent=True) or {},
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT,
            )
            return jsonify(resp.json()), resp.status_code
        except OSError as e:
            return jsonify(msg=str(e)), 500
