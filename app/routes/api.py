"""Master API routes: aggregate quotas from slaves, set user quota on slave."""

import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import requests
from flask import current_app, g, jsonify, request

from app.db import SessionLocal
from app.models_db import OAuthHostUserMapping, OAuthUserCache
from app.utils import get_logger

logger = get_logger(__name__)

# Timeout configuration: (connect_timeout, read_timeout) in seconds
# Using separate timeouts allows faster detection of connection failures while allowing
# longer time for slow operations (e.g., Docker quota queries) to complete.
_REMOTE_API_TIMEOUT_PING = (5, 5)  # Fast timeout for health checks
_REMOTE_API_TIMEOUT_QUOTA = (10, 180)  # Quota fetching: 10s connect, 180s read (Docker operations can take ~1 min)
_REMOTE_API_TIMEOUT_USER_RESOLVE = (5, 10)  # User resolution: fast operation
_REMOTE_API_TIMEOUT_SET_QUOTA = (10, 120)  # Setting quota: 10s connect, 120s read (Docker quota setting can be slow)
_REMOTE_API_TIMEOUT_DEFAULT = (10, 60)  # Default for other operations: 10s connect, 60s read

# Backward compatibility: use default for code that hasn't been updated yet
_REMOTE_API_TIMEOUT = _REMOTE_API_TIMEOUT_DEFAULT

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
    start_time = time.time()
    slave = _slave_by_id(host_id)
    if not slave:
        logger.warning("Host %s not found for quota fetch", host_id)
        return {host_id: {"error": {"msg": "host not found"}}}
    encoded_name = urllib.parse.quote(host_user_name, safe="")
    logger.debug("Fetching quota for host=%s, user=%s", host_id, host_user_name)
    try:
        resp = requests.get(
            f"{slave['url']}/remote-api/quotas/users/by-name/{encoded_name}",
            auth=make_auth(slave),
            timeout=_REMOTE_API_TIMEOUT_QUOTA,
        )
        elapsed = time.time() - start_time
        if resp.status_code // 100 != 2:
            logger.warning("Slave %s returned error status %d for user=%s (took %.2fs)", host_id, resp.status_code, host_user_name, elapsed)
            return {host_id: {"error": resp.json() if resp.content else {"msg": resp.reason}}}
        logger.debug("Fetched quota for host=%s, user=%s (took %.2fs)", host_id, host_user_name, elapsed)
        return {host_id: {"results": resp.json()}}
    except (OSError, requests.exceptions.RequestException) as e:
        elapsed = time.time() - start_time
        logger.warning("Slave %s request failed for user=%s: %s (took %.2fs)", host_id, host_user_name, str(e), elapsed)
        return {host_id: {"error": {"msg": str(e)}}}


def _fetch_all_quotas() -> dict[str, Any]:
    """Fetch aggregated quotas from all slaves in parallel. Returns { host_id: { results: [...] } or { error: {...} } }."""
    start_time = time.time()
    results: dict[str, Any] = {}
    slaves = current_app.config["SLAVES"]
    logger.info("Fetching quotas from %d slave(s)", len(slaves))
    
    def fetch_slave_quota(slave: dict[str, Any]) -> tuple[str, dict[str, Any], float]:
        """Fetch quota from a single slave. Returns (slave_id, result_dict, elapsed_time)."""
        slave_id = slave["id"]
        slave_url = slave["url"]
        slave_start = time.time()
        try:
            resp = requests.get(
                f"{slave_url}/remote-api/quotas",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
            elapsed = time.time() - slave_start
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d (took %.2fs)", slave_id, resp.status_code, elapsed)
                return (slave_id, {"error": resp.json()}, elapsed)
            else:
                logger.debug("Slave %s quota fetched successfully (took %.2fs)", slave_id, elapsed)
                return (slave_id, {"results": resp.json()}, elapsed)
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - slave_start
            logger.warning("Slave %s request failed: %s (took %.2fs)", slave_id, str(e), elapsed)
            return (slave_id, {"error": {"msg": str(e)}}, elapsed)
    
    # Fetch from all slaves in parallel
    slave_times: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=len(slaves)) as executor:
        future_to_slave = {executor.submit(fetch_slave_quota, slave): slave for slave in slaves}
        for future in as_completed(future_to_slave):
            slave_id, result, elapsed = future.result()
            results[slave_id] = result
            slave_times[slave_id] = elapsed
    
    total_time = time.time() - start_time
    logger.info(
        "Fetched quotas from %d slave(s) in %.2fs (per-slave: %s)",
        len(slaves),
        total_time,
        ", ".join(f"{sid}={t:.2f}s" for sid, t in slave_times.items()),
    )
    return results


def _fetch_quotas_for_uid(uid: int) -> dict[str, Any]:
    """Fetch per-user quotas from all slaves in parallel (one GET per slave, no full scan). Returns same shape as _fetch_all_quotas."""
    start_time = time.time()
    results: dict[str, Any] = {}
    slaves = current_app.config["SLAVES"]
    logger.info("Fetching quotas for uid=%d from %d slave(s)", uid, len(slaves))
    
    def fetch_slave_quota_for_uid(slave: dict[str, Any], uid: int) -> tuple[str, dict[str, Any], float]:
        """Fetch quota for a uid from a single slave. Returns (slave_id, result_dict, elapsed_time)."""
        slave_id = slave["id"]
        slave_url = slave["url"]
        slave_start = time.time()
        try:
            resp = requests.get(
                f"{slave_url}/remote-api/quotas/users/{uid}",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
            elapsed = time.time() - slave_start
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d for uid=%d (took %.2fs)", slave_id, resp.status_code, uid, elapsed)
                return (slave_id, {"error": resp.json()}, elapsed)
            else:
                logger.debug("Slave %s quota for uid=%d fetched successfully (took %.2fs)", slave_id, uid, elapsed)
                return (slave_id, {"results": resp.json()}, elapsed)
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - slave_start
            logger.warning("Slave %s request failed for uid=%d: %s (took %.2fs)", slave_id, uid, str(e), elapsed)
            return (slave_id, {"error": {"msg": str(e)}}, elapsed)
    
    # Fetch from all slaves in parallel
    slave_times: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=len(slaves)) as executor:
        future_to_slave = {executor.submit(fetch_slave_quota_for_uid, slave, uid): slave for slave in slaves}
        for future in as_completed(future_to_slave):
            slave_id, result, elapsed = future.result()
            results[slave_id] = result
            slave_times[slave_id] = elapsed
    
    total_time = time.time() - start_time
    logger.info(
        "Fetched quotas for uid=%d from %d slave(s) in %.2fs (per-slave: %s)",
        uid,
        len(slaves),
        total_time,
        ", ".join(f"{sid}={t:.2f}s" for sid, t in slave_times.items()),
    )
    return results


def register_api_routes(app: Any) -> None:
    """Register /api/* routes on the Flask app (requires app for config and oauth)."""
    from auth_connect import oauth

    @app.route("/api/health")
    def health() -> Any:
        return jsonify({"status": "ok"})

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
        start_time = time.time()
        slave = _slave_by_id(slave_id)
        if not slave:
            logger.warning("Host %s not found for user resolve", slave_id)
            return jsonify(msg="host not found"), 404
        username = (request.args.get("username") or "").strip()
        if not username:
            return jsonify(msg="username query parameter required"), 400
        logger.debug("Resolving username=%s on host=%s", username, slave_id)
        try:
            url = f"{slave['url']}/remote-api/users/resolve?username={urllib.parse.quote(username)}"
            resp = requests.get(url, auth=make_auth(slave), timeout=_REMOTE_API_TIMEOUT_USER_RESOLVE)
            elapsed = time.time() - start_time
            if resp.status_code == 404:
                logger.debug("User %s not found on host=%s (took %.2fs)", username, slave_id, elapsed)
                return jsonify(msg=resp.json().get("msg", "user not found")), 404
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d when resolving username=%s (took %.2fs)", slave_id, resp.status_code, username, elapsed)
                return jsonify(msg=resp.json().get("msg", "resolve failed")), resp.status_code
            logger.debug("Resolved username=%s on host=%s (took %.2fs)", username, slave_id, elapsed)
            return jsonify(resp.json())
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to resolve username=%s on host=%s: %s (took %.2fs)", username, slave_id, str(e), elapsed)
            return jsonify(msg=str(e)), 502

    @app.route("/api/quotas/<string:slave_id>/users/<int:uid>", methods=["PUT"])
    @oauth.requires_admin
    def set_user_quota(slave_id: str, uid: int) -> tuple[Any, int]:
        start_time = time.time()
        slave = None
        for _slave in current_app.config["SLAVES"]:
            if _slave["id"] == slave_id:
                slave = _slave
                break

        if not slave:
            logger.warning("Host %s not found for quota set", slave_id)
            return jsonify(msg="slave not found"), 404

        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400

        logger.info("Setting quota for host=%s, uid=%d, device=%s", slave_id, uid, device)
        try:
            url = f"{slave['url']}/remote-api/quotas/users/{uid}?device={urllib.parse.quote(device)}"
            resp = requests.put(
                url,
                json=request.get_json(silent=True) or {},
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_SET_QUOTA,
            )
            elapsed = time.time() - start_time
            if resp.status_code // 100 == 2:
                logger.info("Successfully set quota for host=%s, uid=%d, device=%s (took %.2fs)", slave_id, uid, device, elapsed)
            else:
                logger.warning("Slave %s returned error status %d when setting quota for uid=%d, device=%s (took %.2fs)", slave_id, resp.status_code, uid, device, elapsed)
            return jsonify(resp.json()), resp.status_code
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to set quota for host=%s, uid=%d, device=%s: %s (took %.2fs)", slave_id, uid, device, str(e), elapsed)
            return jsonify(msg=str(e)), 500

    @app.route("/api/quotas/<string:slave_id>/batch", methods=["POST"])
    @oauth.requires_admin
    def set_batch_quota(slave_id: str) -> tuple[Any, int]:
        """Apply batch quota to all eligible users on a device (admin only)."""
        start_time = time.time()
        slave = _slave_by_id(slave_id)

        if not slave:
            logger.warning("Host %s not found for batch quota set", slave_id)
            return jsonify(msg="slave not found"), 404

        body = request.get_json(silent=True) or {}
        device = body.get("device")
        if not device:
            return jsonify(msg="device is required in request body"), 400

        logger.info("Setting batch quota for host=%s, device=%s", slave_id, device)
        try:
            url = f"{slave['url']}/remote-api/quotas/batch"
            resp = requests.post(
                url,
                json=body,
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_SET_QUOTA,
            )
            elapsed = time.time() - start_time
            if resp.status_code // 100 == 2:
                logger.info("Successfully set batch quota for host=%s, device=%s (took %.2fs)", slave_id, device, elapsed)
            else:
                logger.warning("Slave %s returned error status %d when setting batch quota for device=%s (took %.2fs)", slave_id, resp.status_code, device, elapsed)
            return jsonify(resp.json()), resp.status_code
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to set batch quota for host=%s, device=%s: %s (took %.2fs)", slave_id, device, str(e), elapsed)
            return jsonify(msg=str(e)), 500

    @app.route("/api/quotas/<string:slave_id>/default-quota")
    @oauth.requires_admin
    def get_default_quota(slave_id: str) -> tuple[Any, int]:
        """Get default user quota for a device on a host. Query param: device=."""
        slave = _slave_by_id(slave_id)
        if not slave:
            return jsonify(msg="slave not found"), 404
        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400
        try:
            url = f"{slave['url']}/remote-api/quotas/defaults?device={urllib.parse.quote(device)}"
            resp = requests.get(url, auth=make_auth(slave), timeout=_REMOTE_API_TIMEOUT_QUOTA)
            return jsonify(resp.json()), resp.status_code
        except (OSError, requests.exceptions.RequestException) as e:
            logger.warning("Failed to get default quota for host=%s, device=%s: %s", slave_id, device, e)
            return jsonify(msg=str(e)), 502

    @app.route("/api/quotas/<string:slave_id>/default-quota", methods=["PUT"])
    @oauth.requires_admin
    def set_default_quota(slave_id: str) -> tuple[Any, int]:
        """Set default user quota for a device on a host. Query param: device=. Body: block_soft_limit, block_hard_limit, inode_soft_limit, inode_hard_limit."""
        slave = _slave_by_id(slave_id)
        if not slave:
            return jsonify(msg="slave not found"), 404
        device = request.args.get("device")
        if not device:
            return jsonify(msg="device query parameter required"), 400
        body = request.get_json(silent=True) or {}
        try:
            url = f"{slave['url']}/remote-api/quotas/defaults?device={urllib.parse.quote(device)}"
            resp = requests.put(url, json=body, auth=make_auth(slave), timeout=_REMOTE_API_TIMEOUT_SET_QUOTA)
            return jsonify(resp.json()), resp.status_code
        except (OSError, requests.exceptions.RequestException) as e:
            logger.warning("Failed to set default quota for host=%s, device=%s: %s", slave_id, device, e)
            return jsonify(msg=str(e)), 502

    @app.route("/api/hosts")
    @oauth.requires_login
    def get_hosts() -> tuple[Any, int] | Any:
        """List host ids from config (for host selector in mapping UIs)."""
        slaves = current_app.config.get("SLAVES", [])
        return jsonify([{"id": s["id"]} for s in slaves])

    @app.route("/api/hosts/ping")
    @oauth.requires_login
    def ping_hosts() -> tuple[Any, int] | Any:
        """Ping all slaves to check connectivity in parallel. Returns { host_id: { status: "ok"|"error", latency_ms?: number, error?: string } }."""
        start_time = time.time()
        slaves = current_app.config.get("SLAVES", [])
        logger.info("Pinging %d slave(s)", len(slaves))
        results: dict[str, Any] = {}
        
        def ping_slave(slave: dict[str, Any]) -> tuple[str, dict[str, Any], float]:
            """Ping a single slave. Returns (host_id, result_dict, elapsed_time)."""
            host_id = slave["id"]
            slave_start = time.time()
            try:
                resp = requests.get(
                    f"{slave['url']}/remote-api/ping",
                    auth=make_auth(slave),
                    timeout=_REMOTE_API_TIMEOUT_PING,
                )
                elapsed = time.time() - slave_start
                latency_ms = int(elapsed * 1000)
                if resp.status_code == 200:
                    logger.debug("Slave %s ping successful (latency: %dms)", host_id, latency_ms)
                    return (host_id, {"status": "ok", "latency_ms": latency_ms}, elapsed)
                else:
                    logger.warning("Slave %s ping returned error status %d (took %.2fs)", host_id, resp.status_code, elapsed)
                    return (host_id, {"status": "error", "error": f"HTTP {resp.status_code}"}, elapsed)
            except requests.exceptions.Timeout:
                elapsed = time.time() - slave_start
                logger.warning("Slave %s ping timeout (took %.2fs)", host_id, elapsed)
                return (host_id, {"status": "error", "error": "timeout"}, elapsed)
            except Exception as e:
                elapsed = time.time() - slave_start
                logger.warning("Slave %s ping failed: %s (took %.2fs)", host_id, str(e), elapsed)
                return (host_id, {"status": "error", "error": str(e)}, elapsed)
        
        # Ping all slaves in parallel
        slave_times: dict[str, float] = {}
        with ThreadPoolExecutor(max_workers=len(slaves)) as executor:
            future_to_slave = {executor.submit(ping_slave, slave): slave for slave in slaves}
            for future in as_completed(future_to_slave):
                host_id, result, elapsed = future.result()
                results[host_id] = result
                slave_times[host_id] = elapsed
        
        total_time = time.time() - start_time
        logger.info(
            "Pinged %d slave(s) in %.2fs (per-slave: %s)",
            len(slaves),
            total_time,
            ", ".join(f"{sid}={t*1000:.0f}ms" for sid, t in slave_times.items()),
        )
        return jsonify(results)

    @app.route("/api/hosts/<string:host_id>/users")
    @oauth.requires_login
    def get_host_users(host_id: str) -> tuple[Any, int] | Any:
        """List host user names on that host (lightweight endpoint, no quota computation)."""
        slave = _slave_by_id(host_id)
        if not slave:
            return jsonify(msg="host not found"), 404
        try:
            # Use lightweight /remote-api/users endpoint (just system users, no Docker df() calls)
            resp = requests.get(
                f"{slave['url']}/remote-api/users",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
        except (OSError, requests.exceptions.RequestException) as e:
            return jsonify(msg=str(e)), 502
        if resp.status_code // 100 != 2:
            return jsonify(msg="failed to fetch host users"), 502
        # Transform ["user1", "user2"] to [{"host_user_name": "user1"}, ...]
        names = resp.json()
        return jsonify([{"host_user_name": n} for n in names])

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

    @app.route("/api/admin/mappings/batch", methods=["POST"])
    @oauth.requires_admin
    def post_admin_mappings_batch() -> tuple[Any, int] | Any:
        """Add multiple mappings at once (admin only). Body: { mappings: [{ oauth_user_id, host_id, host_user_name }, ...] }"""
        body = request.get_json(silent=True) or {}
        mappings_input = body.get("mappings")
        if not isinstance(mappings_input, list) or len(mappings_input) == 0:
            return jsonify(msg="mappings array required"), 400
        
        # Validate all mappings first
        validated: list[dict[str, Any]] = []
        for i, m in enumerate(mappings_input):
            oauth_user_id = m.get("oauth_user_id")
            host_id = m.get("host_id")
            host_user_name = m.get("host_user_name")
            if oauth_user_id is None or not host_id or not host_user_name:
                return jsonify(msg=f"mapping[{i}]: oauth_user_id, host_id and host_user_name required"), 400
            if not _HOST_USER_NAME_RE.match(host_user_name):
                return jsonify(msg=f"mapping[{i}]: invalid host_user_name"), 400
            if not _slave_by_id(host_id):
                return jsonify(msg=f"mapping[{i}]: host '{host_id}' not found"), 404
            validated.append({
                "oauth_user_id": int(oauth_user_id),
                "host_id": host_id,
                "host_user_name": host_user_name,
            })
        
        db = SessionLocal()
        try:
            added: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for m in validated:
                existing = (
                    db.query(OAuthHostUserMapping)
                    .filter(
                        OAuthHostUserMapping.oauth_user_id == m["oauth_user_id"],
                        OAuthHostUserMapping.host_id == m["host_id"],
                        OAuthHostUserMapping.host_user_name == m["host_user_name"],
                    )
                    .first()
                )
                if existing:
                    skipped.append(m)
                else:
                    db.add(
                        OAuthHostUserMapping(
                            oauth_user_id=m["oauth_user_id"],
                            host_id=m["host_id"],
                            host_user_name=m["host_user_name"],
                        )
                    )
                    added.append(m)
            db.commit()
            return jsonify({"added": added, "skipped": skipped}), 201
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

    @app.route("/api/internal/slave-events", methods=["POST"])
    def post_slave_events() -> tuple[Any, int] | Any:
        """Accept events from slaves (quota exceeded, container removed). Auth: X-API-Key = SLAVE_EVENT_SECRET."""
        secret = current_app.config.get("SLAVE_EVENT_SECRET")
        if not secret:
            return jsonify(msg="slave events not configured"), 503
        provided = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
        if provided != secret:
            return jsonify(msg="unauthorized"), 401
        body = request.get_json(silent=True) or {}
        host_id = body.get("host_id")
        events = body.get("events")
        if not host_id or not isinstance(events, list):
            return jsonify(msg="host_id and events (array) required"), 400
        from app.notifications import process_slave_events
        process_slave_events(host_id, events)
        return jsonify(msg="ok"), 200

    @app.route("/api/admin/oauth-users")
    @oauth.requires_admin
    def get_admin_oauth_users() -> tuple[Any, int] | Any:
        """List OAuth users from OAuth server for admin dropdown."""
        try:
            users = oauth.get_users()
        except Exception as e:
            return jsonify(msg=str(e)), 502
        return jsonify([{"id": u.id, "name": u.name} for u in users])

    @app.route("/api/admin/notifications")
    @oauth.requires_admin
    def get_admin_notifications() -> tuple[Any, int] | Any:
        """List notification email log entries for admin notification center."""
        from app.models_db import NotificationEmailLog

        db = SessionLocal()
        try:
            # Basic pagination
            try:
                page = int(request.args.get("page", "1"))
            except ValueError:
                page = 1
            try:
                page_size = int(request.args.get("page_size", "50"))
            except ValueError:
                page_size = 50
            page = max(page, 1)
            page_size = max(min(page_size, 200), 1)
            offset = (page - 1) * page_size

            q = db.query(NotificationEmailLog)

            host_id = request.args.get("host_id")
            if host_id:
                q = q.filter(NotificationEmailLog.host_id == host_id)

            device_name = request.args.get("device_name")
            if device_name:
                q = q.filter(NotificationEmailLog.device_name == device_name)

            oauth_user_id = request.args.get("oauth_user_id")
            if oauth_user_id:
                try:
                    oauth_user_id_int = int(oauth_user_id)
                    q = q.filter(NotificationEmailLog.oauth_user_id == oauth_user_id_int)
                except ValueError:
                    pass

            email = request.args.get("email")
            if email:
                q = q.filter(NotificationEmailLog.email == email)

            event_type = request.args.get("event_type")
            if event_type:
                q = q.filter(NotificationEmailLog.event_type == event_type)

            send_status = request.args.get("send_status")
            if send_status:
                q = q.filter(NotificationEmailLog.send_status == send_status)

            batch_id = request.args.get("batch_id")
            if batch_id:
                q = q.filter(NotificationEmailLog.batch_id == batch_id)

            # Time range filters (ISO8601 strings)
            created_from = request.args.get("from")
            created_to = request.args.get("to")
            if created_from:
                try:
                    dt_from = datetime.fromisoformat(created_from)
                    q = q.filter(NotificationEmailLog.created_at >= dt_from)
                except ValueError:
                    pass
            if created_to:
                try:
                    dt_to = datetime.fromisoformat(created_to)
                    q = q.filter(NotificationEmailLog.created_at <= dt_to)
                except ValueError:
                    pass

            total = q.count()
            rows = (
                q.order_by(NotificationEmailLog.created_at.desc())
                .offset(offset)
                .limit(page_size)
                .all()
            )

            items: list[dict[str, Any]] = []
            for r in rows:
                items.append(
                    {
                        "id": r.id,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "oauth_user_id": r.oauth_user_id,
                        "email": r.email,
                        "host_id": r.host_id,
                        "host_user_name": r.host_user_name,
                        "device_name": r.device_name,
                        "quota_type": r.quota_type,
                        "event_type": r.event_type,
                        "subject": r.subject,
                        "send_status": r.send_status,
                        "error_message": r.error_message,
                        "batch_id": r.batch_id,
                    }
                )
            return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})
        finally:
            db.close()

    @app.route("/api/admin/notifications/<int:log_id>")
    @oauth.requires_admin
    def get_admin_notification_detail(log_id: int) -> tuple[Any, int] | Any:
        """Get full detail for a single notification log entry."""
        from app.models_db import NotificationEmailLog, NotificationEvent

        db = SessionLocal()
        try:
            row = db.query(NotificationEmailLog).filter(NotificationEmailLog.id == log_id).first()
            if not row:
                return jsonify(msg="notification not found"), 404

            events = (
                db.query(NotificationEvent)
                .filter(NotificationEvent.email_log_id == row.id)
                .order_by(NotificationEvent.created_at.asc())
                .all()
            )

            events_payload: list[dict[str, Any]] = []
            for ev in events:
                events_payload.append(
                    {
                        "id": ev.id,
                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                        "oauth_user_id": ev.oauth_user_id,
                        "email": ev.email,
                        "host_id": ev.host_id,
                        "host_user_name": ev.host_user_name,
                        "device_name": ev.device_name,
                        "quota_type": ev.quota_type,
                        "event_type": ev.event_type,
                        "payload": ev.payload,
                        "state_key": ev.state_key,
                    }
                )

            return jsonify(
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "oauth_user_id": row.oauth_user_id,
                    "email": row.email,
                    "host_id": row.host_id,
                    "host_user_name": row.host_user_name,
                    "device_name": row.device_name,
                    "quota_type": row.quota_type,
                    "event_type": row.event_type,
                    "subject": row.subject,
                    "body_preview": row.body_preview,
                    "body_html": row.body_html,
                    "send_status": row.send_status,
                    "error_message": row.error_message,
                    "dedupe_key": row.dedupe_key,
                    "last_state": row.last_state,
                    "batch_id": row.batch_id,
                    "events": events_payload,
                }
            )
        finally:
            db.close()

    @app.route("/api/quotas/<string:slave_id>/docker/containers")
    @oauth.requires_admin
    def get_docker_containers(slave_id: str) -> tuple[Any, int] | Any:
        """Proxy to slave's Docker container detail endpoint."""
        start_time = time.time()
        slave = _slave_by_id(slave_id)
        if not slave:
            logger.warning("Host %s not found for Docker containers fetch", slave_id)
            return jsonify(msg="host not found"), 404
        try:
            resp = requests.get(
                f"{slave['url']}/remote-api/docker/containers",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
            elapsed = time.time() - start_time
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d for Docker containers (took %.2fs)", slave_id, resp.status_code, elapsed)
                return jsonify(resp.json()), resp.status_code
            logger.debug("Fetched Docker containers from slave %s (took %.2fs)", slave_id, elapsed)
            return jsonify(resp.json())
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to fetch Docker containers from slave %s: %s (took %.2fs)", slave_id, str(e), elapsed)
            return jsonify(msg=str(e)), 502

    @app.route("/api/quotas/<string:slave_id>/docker/images")
    @oauth.requires_admin
    def get_docker_images(slave_id: str) -> tuple[Any, int] | Any:
        """Proxy to slave's Docker image detail endpoint."""
        start_time = time.time()
        slave = _slave_by_id(slave_id)
        if not slave:
            logger.warning("Host %s not found for Docker images fetch", slave_id)
            return jsonify(msg="host not found"), 404
        try:
            resp = requests.get(
                f"{slave['url']}/remote-api/docker/images",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
            elapsed = time.time() - start_time
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d for Docker images (took %.2fs)", slave_id, resp.status_code, elapsed)
                return jsonify(resp.json()), resp.status_code
            logger.debug("Fetched Docker images from slave %s (took %.2fs)", slave_id, elapsed)
            return jsonify(resp.json())
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to fetch Docker images from slave %s: %s (took %.2fs)", slave_id, str(e), elapsed)
            return jsonify(msg=str(e)), 502

    @app.route("/api/quotas/<string:slave_id>/docker/volumes")
    @oauth.requires_admin
    def get_docker_volumes(slave_id: str) -> tuple[Any, int] | Any:
        """Proxy to slave's Docker volume detail endpoint."""
        start_time = time.time()
        slave = _slave_by_id(slave_id)
        if not slave:
            logger.warning("Host %s not found for Docker volumes fetch", slave_id)
            return jsonify(msg="host not found"), 404
        try:
            resp = requests.get(
                f"{slave['url']}/remote-api/docker/volumes",
                auth=make_auth(slave),
                timeout=_REMOTE_API_TIMEOUT_QUOTA,
            )
            elapsed = time.time() - start_time
            if resp.status_code // 100 != 2:
                logger.warning("Slave %s returned error status %d for Docker volumes (took %.2fs)", slave_id, resp.status_code, elapsed)
                return jsonify(resp.json()), resp.status_code
            logger.debug("Fetched Docker volumes from slave %s (took %.2fs)", slave_id, elapsed)
            return jsonify(resp.json())
        except (OSError, requests.exceptions.RequestException) as e:
            elapsed = time.time() - start_time
            logger.warning("Failed to fetch Docker volumes from slave %s: %s (took %.2fs)", slave_id, str(e), elapsed)
            return jsonify(msg=str(e)), 502

    @app.route("/api/admin/host-users")
    @oauth.requires_admin
    def get_admin_host_users() -> tuple[Any, int] | Any:
        """For each slave, collect (host_id, host_user_name) using lightweight /remote-api/users endpoint; merge with mapped host users."""
        start_time = time.time()
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, str]] = []
        slaves = current_app.config.get("SLAVES", [])
        logger.info("Fetching host users from %d slave(s)", len(slaves))
        
        def fetch_slave_host_users(slave: dict[str, Any]) -> tuple[str, list[tuple[str, str]], float]:
            """Fetch host users from a single slave using lightweight endpoint. Returns (host_id, list of (host_id, host_user_name) tuples, elapsed_time)."""
            host_id = slave["id"]
            slave_start = time.time()
            host_users: list[tuple[str, str]] = []
            try:
                # Use lightweight /remote-api/users endpoint instead of /remote-api/quotas
                resp = requests.get(
                    f"{slave['url']}/remote-api/users",
                    auth=make_auth(slave),
                    timeout=_REMOTE_API_TIMEOUT_USER_RESOLVE,  # Should be fast, use shorter timeout
                )
                elapsed = time.time() - slave_start
                if resp.status_code // 100 != 2:
                    logger.warning("Slave %s returned error status %d when fetching host users (took %.2fs)", host_id, resp.status_code, elapsed)
                    return (host_id, host_users, elapsed)
                # Response is a simple list of user names
                user_names = resp.json()
                if isinstance(user_names, list):
                    host_users = [(host_id, name) for name in user_names]
                logger.debug("Slave %s returned %d host users (took %.2fs)", host_id, len(host_users), elapsed)
                return (host_id, host_users, elapsed)
            except (OSError, requests.exceptions.RequestException) as e:
                elapsed = time.time() - slave_start
                logger.warning("Slave %s request failed when fetching host users: %s (took %.2fs)", host_id, str(e), elapsed)
                return (host_id, host_users, elapsed)
        
        # Fetch from all slaves in parallel
        slave_times: dict[str, float] = {}
        with ThreadPoolExecutor(max_workers=len(slaves)) as executor:
            future_to_slave = {executor.submit(fetch_slave_host_users, slave): slave for slave in slaves}
            for future in as_completed(future_to_slave):
                host_id, host_users, elapsed = future.result()
                slave_times[host_id] = elapsed
                for hid, name in host_users:
                    if (hid, name) not in seen:
                        seen.add((hid, name))
                        result.append({"host_id": hid, "host_user_name": name})
        
        total_time = time.time() - start_time
        logger.info(
            "Fetched host users from %d slave(s) in %.2fs, found %d unique users (per-slave: %s)",
            len(slaves),
            total_time,
            len(result),
            ", ".join(f"{sid}={t:.2f}s" for sid, t in slave_times.items()),
        )
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
