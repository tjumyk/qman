"""Master API routes: aggregate quotas from slaves, set user quota on slave."""

import re
import urllib.parse
from typing import Any

import requests
from flask import current_app, g, jsonify, request

from app.db import SessionLocal
from app.models_db import OAuthHostUserMapping, OAuthUserCache

_REMOTE_API_TIMEOUT = 3  # seconds

# Host user name: non-empty, printable ASCII (no control chars). Relaxed to allow letters, numbers, dash, underscore, dot.
_HOST_USER_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,255}$")


def make_auth(slave: dict[str, Any]) -> tuple[str, str]:
    """Return (username, password) for slave HTTP Basic auth."""
    return "api", slave["api_key"]


def _slave_by_id(host_id: str) -> dict[str, Any] | None:
    """Return slave config for host_id or None."""
    for slave in current_app.config["SLAVES"]:
        if slave["id"] == host_id:
            return slave
    return None


def _fetch_quotas_for_host_user(host_id: str, host_user_name: str) -> dict[str, Any]:
    """Fetch quota for one (host_id, host_user_name) from that slave's by-name endpoint. Returns { host_id: { results } or { error } }."""
    slave = _slave_by_id(host_id)
    if not slave:
        return {host_id: {"error": {"msg": "host not found"}}}
    encoded_name = urllib.parse.quote(host_user_name, safe="")
    try:
        resp = requests.get(
            f"{slave['url']}/remote-api/quotas/users/by-name/{encoded_name}",
            auth=make_auth(slave),
            timeout=_REMOTE_API_TIMEOUT,
        )
        if resp.status_code // 100 != 2:
            return {host_id: {"error": resp.json() if resp.content else {"msg": resp.reason}}}
        return {host_id: {"results": resp.json()}}
    except OSError as e:
        return {host_id: {"error": {"msg": str(e)}}}


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


def _fetch_quotas_for_uid(uid: int) -> dict[str, Any]:
    """Fetch per-user quotas from all slaves (one GET per slave, no full scan). Returns same shape as _fetch_all_quotas."""
    results: dict[str, Any] = {}
    for slave in current_app.config["SLAVES"]:
        slave_id = slave["id"]
        slave_url = slave["url"]
        try:
            resp = requests.get(
                f"{slave_url}/remote-api/quotas/users/{uid}",
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

    @app.route("/api/me/mappings", methods=["GET"])
    @oauth.requires_login
    def get_me_mappings() -> tuple[Any, int] | Any:
        oauth_uid = oauth.get_uid()
        if oauth_uid is None:
            return jsonify(msg="user info required"), 401
        db = SessionLocal()
        try:
            rows = (
                db.query(OAuthHostUserMapping)
                .filter(OAuthHostUserMapping.oauth_user_id == oauth_uid)
                .order_by(OAuthHostUserMapping.host_id, OAuthHostUserMapping.host_user_name)
                .all()
            )
            return jsonify([{"host_id": r.host_id, "host_user_name": r.host_user_name} for r in rows])
        finally:
            db.close()

    @app.route("/api/me/mappings", methods=["POST"])
    @oauth.requires_login
    def post_me_mappings() -> tuple[Any, int] | Any:
        oauth_uid = oauth.get_uid()
        if oauth_uid is None:
            return jsonify(msg="user info required"), 401
        body = request.get_json(silent=True) or {}
        host_id = body.get("host_id") or request.args.get("host_id")
        host_user_name = body.get("host_user_name") or request.args.get("host_user_name")
        if not host_id or not host_user_name:
            return jsonify(msg="host_id and host_user_name required"), 400
        if not _HOST_USER_NAME_RE.match(host_user_name):
            return jsonify(msg="invalid host_user_name"), 400
        if not _slave_by_id(host_id):
            return jsonify(msg="host not found"), 404
        db = SessionLocal()
        try:
            existing = (
                db.query(OAuthHostUserMapping)
                .filter(
                    OAuthHostUserMapping.oauth_user_id == oauth_uid,
                    OAuthHostUserMapping.host_id == host_id,
                    OAuthHostUserMapping.host_user_name == host_user_name,
                )
                .first()
            )
            if existing:
                return jsonify(msg="mapping already exists"), 400
            db.add(
                OAuthHostUserMapping(
                    oauth_user_id=oauth_uid,
                    host_id=host_id,
                    host_user_name=host_user_name,
                )
            )
            db.commit()
            return jsonify({"host_id": host_id, "host_user_name": host_user_name}), 201
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.route("/api/me/mappings", methods=["DELETE"])
    @oauth.requires_login
    def delete_me_mappings() -> tuple[Any, int] | Any:
        oauth_uid = oauth.get_uid()
        if oauth_uid is None:
            return jsonify(msg="user info required"), 401
        body = request.get_json(silent=True) or {}
        host_id = body.get("host_id") or request.args.get("host_id")
        host_user_name = body.get("host_user_name") or request.args.get("host_user_name")
        if not host_id or not host_user_name:
            return jsonify(msg="host_id and host_user_name required"), 400
        db = SessionLocal()
        try:
            row = (
                db.query(OAuthHostUserMapping)
                .filter(
                    OAuthHostUserMapping.oauth_user_id == oauth_uid,
                    OAuthHostUserMapping.host_id == host_id,
                    OAuthHostUserMapping.host_user_name == host_user_name,
                )
                .first()
            )
            if not row:
                return jsonify(msg="mapping not found"), 404
            db.delete(row)
            db.commit()
            return jsonify(msg="ok"), 200
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.route("/api/me/quotas")
    @oauth.requires_login
    def get_me_quotas() -> tuple[Any, int] | Any:
        oauth_uid = oauth.get_uid()
        if oauth_uid is None:
            return jsonify(msg="user info required"), 401
        host_id = request.args.get("host_id")
        host_user_name = request.args.get("host_user_name")
        db = SessionLocal()
        try:
            mappings = (
                db.query(OAuthHostUserMapping)
                .filter(OAuthHostUserMapping.oauth_user_id == oauth_uid)
                .order_by(OAuthHostUserMapping.host_id, OAuthHostUserMapping.host_user_name)
                .all()
            )
        finally:
            db.close()
        if not mappings:
            return jsonify({})
        if host_id and host_user_name:
            if not any(m.host_id == host_id and m.host_user_name == host_user_name for m in mappings):
                return jsonify(msg="mapping not found for this user"), 403
            key = f"{host_id}|{host_user_name}"
            payload = _fetch_quotas_for_host_user(host_id, host_user_name)
            return jsonify({key: next(iter(payload.values()))})
        # Return quotas for all mappings in one response (key = "host_id|host_user_name")
        result: dict[str, Any] = {}
        for m in mappings:
            key = f"{m.host_id}|{m.host_user_name}"
            payload = _fetch_quotas_for_host_user(m.host_id, m.host_user_name)
            result[key] = next(iter(payload.values()))
        return jsonify(result)

    @app.route("/api/quotas")
    @oauth.requires_login
    def get_quotas() -> tuple[Any, int] | Any:
        return jsonify(_fetch_all_quotas())

    @app.route("/api/quotas/<string:slave_id>/users/resolve")
    @oauth.requires_admin
    def resolve_host_user(slave_id: str) -> tuple[Any, int] | Any:
        """Resolve username to uid and name on the given host. Query param: username=."""
        slave = _slave_by_id(slave_id)
        if not slave:
            return jsonify(msg="host not found"), 404
        username = (request.args.get("username") or "").strip()
        if not username:
            return jsonify(msg="username query parameter required"), 400
        try:
            url = f"{slave['url']}/remote-api/users/resolve?username={urllib.parse.quote(username)}"
            resp = requests.get(url, auth=make_auth(slave), timeout=_REMOTE_API_TIMEOUT)
            if resp.status_code == 404:
                return jsonify(msg=resp.json().get("msg", "user not found")), 404
            if resp.status_code // 100 != 2:
                return jsonify(msg=resp.json().get("msg", "resolve failed")), resp.status_code
            return jsonify(resp.json())
        except OSError as e:
            return jsonify(msg=str(e)), 502

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

    @app.route("/api/hosts")
    @oauth.requires_login
    def get_hosts() -> tuple[Any, int] | Any:
        """List host ids from config (for host selector in mapping UIs)."""
        slaves = current_app.config.get("SLAVES", [])
        return jsonify([{"id": s["id"]} for s in slaves])

    @app.route("/api/hosts/<string:host_id>/users")
    @oauth.requires_login
    def get_host_users(host_id: str) -> tuple[Any, int] | Any:
        """List host user names on that host (from slave quotas)."""
        slave = _slave_by_id(host_id)
        if not slave:
            return jsonify(msg="host not found"), 404
        try:
            resp = requests.get(
                f"{slave['url']}/remote-api/quotas",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT,
            )
        except OSError as e:
            return jsonify(msg=str(e)), 502
        if resp.status_code // 100 != 2:
            return jsonify(msg="failed to fetch host quotas"), 502
        data = resp.json()
        names: set[str] = set()
        for device in data:
            for uq in device.get("user_quotas") or []:
                if uq.get("name"):
                    names.add(uq["name"])
        return jsonify([{"host_user_name": n} for n in sorted(names)])

    def _oauth_name_for_id(oauth_user_id: int) -> str | None:
        """Return OAuth user name from cache or OAuth server."""
        db = SessionLocal()
        try:
            row = db.query(OAuthUserCache).filter(OAuthUserCache.id == oauth_user_id).first()
            if row:
                return row.name
        finally:
            db.close()
        try:
            user = oauth.get_user_by_id(oauth_user_id)
            if user:
                name = user.name
                db2 = SessionLocal()
                try:
                    row = db2.query(OAuthUserCache).filter(OAuthUserCache.id == oauth_user_id).first()
                    if row:
                        row.name = name
                    else:
                        db2.add(OAuthUserCache(id=oauth_user_id, name=name))
                    db2.commit()
                except Exception:
                    db2.rollback()
                finally:
                    db2.close()
                return name
        except Exception:
            pass
        return None

    @app.route("/api/admin/mappings", methods=["GET"])
    @oauth.requires_admin
    def get_admin_mappings() -> tuple[Any, int] | Any:
        """All mappings with OAuth user info for admin table."""
        db = SessionLocal()
        try:
            rows = (
                db.query(OAuthHostUserMapping)
                .order_by(
                    OAuthHostUserMapping.host_id,
                    OAuthHostUserMapping.host_user_name,
                    OAuthHostUserMapping.oauth_user_id,
                )
                .all()
            )
            out = []
            for r in rows:
                name = _oauth_name_for_id(r.oauth_user_id)
                out.append(
                    {
                        "oauth_user_id": r.oauth_user_id,
                        "oauth_user_name": name,
                        "host_id": r.host_id,
                        "host_user_name": r.host_user_name,
                    }
                )
            return jsonify(out)
        finally:
            db.close()

    @app.route("/api/admin/mappings", methods=["POST"])
    @oauth.requires_admin
    def post_admin_mappings() -> tuple[Any, int] | Any:
        body = request.get_json(silent=True) or {}
        oauth_user_id = body.get("oauth_user_id")
        host_id = body.get("host_id")
        host_user_name = body.get("host_user_name")
        if oauth_user_id is None or not host_id or not host_user_name:
            return jsonify(msg="oauth_user_id, host_id and host_user_name required"), 400
        if not _HOST_USER_NAME_RE.match(host_user_name):
            return jsonify(msg="invalid host_user_name"), 400
        if not _slave_by_id(host_id):
            return jsonify(msg="host not found"), 404
        db = SessionLocal()
        try:
            existing = (
                db.query(OAuthHostUserMapping)
                .filter(
                    OAuthHostUserMapping.oauth_user_id == oauth_user_id,
                    OAuthHostUserMapping.host_id == host_id,
                    OAuthHostUserMapping.host_user_name == host_user_name,
                )
                .first()
            )
            if existing:
                return jsonify(msg="mapping already exists"), 400
            db.add(
                OAuthHostUserMapping(
                    oauth_user_id=int(oauth_user_id),
                    host_id=host_id,
                    host_user_name=host_user_name,
                )
            )
            db.commit()
            return jsonify({"oauth_user_id": oauth_user_id, "host_id": host_id, "host_user_name": host_user_name}), 201
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.route("/api/admin/mappings", methods=["DELETE"])
    @oauth.requires_admin
    def delete_admin_mappings() -> tuple[Any, int] | Any:
        body = request.get_json(silent=True) or {}
        oauth_user_id = body.get("oauth_user_id") or request.args.get("oauth_user_id")
        host_id = body.get("host_id") or request.args.get("host_id")
        host_user_name = body.get("host_user_name") or request.args.get("host_user_name")
        if oauth_user_id is None or not host_id or not host_user_name:
            return jsonify(msg="oauth_user_id, host_id and host_user_name required"), 400
        db = SessionLocal()
        try:
            row = (
                db.query(OAuthHostUserMapping)
                .filter(
                    OAuthHostUserMapping.oauth_user_id == int(oauth_user_id),
                    OAuthHostUserMapping.host_id == host_id,
                    OAuthHostUserMapping.host_user_name == host_user_name,
                )
                .first()
            )
            if not row:
                return jsonify(msg="mapping not found"), 404
            db.delete(row)
            db.commit()
            return jsonify(msg="ok"), 200
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.route("/api/admin/oauth-users")
    @oauth.requires_admin
    def get_admin_oauth_users() -> tuple[Any, int] | Any:
        """List OAuth users from OAuth server for admin dropdown."""
        try:
            users = oauth.get_users()
        except Exception as e:
            return jsonify(msg=str(e)), 502
        return jsonify([{"id": u.id, "name": u.name} for u in users])

    @app.route("/api/admin/host-users")
    @oauth.requires_admin
    def get_admin_host_users() -> tuple[Any, int] | Any:
        """For each slave, collect (host_id, host_user_name) from quotas; merge with mapped host users."""
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, str]] = []
        for slave in current_app.config.get("SLAVES", []):
            host_id = slave["id"]
            try:
                resp = requests.get(
                    f"{slave['url']}/remote-api/quotas",
                    auth=make_auth(slave),
                    timeout=_REMOTE_API_TIMEOUT,
                )
            except OSError:
                continue
            if resp.status_code // 100 != 2:
                continue
            for device in resp.json():
                for uq in device.get("user_quotas") or []:
                    name = uq.get("name")
                    if name and (host_id, name) not in seen:
                        seen.add((host_id, name))
                        result.append({"host_id": host_id, "host_user_name": name})
        db = SessionLocal()
        try:
            rows = db.query(OAuthHostUserMapping).distinct().all()
            for r in rows:
                if (r.host_id, r.host_user_name) not in seen:
                    seen.add((r.host_id, r.host_user_name))
                    result.append({"host_id": r.host_id, "host_user_name": r.host_user_name})
        finally:
            db.close()
        result.sort(key=lambda x: (x["host_id"], x["host_user_name"]))
        return jsonify(result)
