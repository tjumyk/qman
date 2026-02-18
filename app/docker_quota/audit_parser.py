"""Parse auditd logs for Docker socket/binary access to attribute container create / image pull to uid."""

import subprocess
from typing import Any

from app.utils import get_logger

logger = get_logger(__name__)

# Default keys: separate socket access vs client execution for easier correlation
DEFAULT_AUDIT_KEYS = ("docker-socket", "docker-client")


def parse_audit_logs(
    keys: tuple[str, ...] | None = None,
    audit_path: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Parse audit logs for given keys (e.g. docker-socket, docker-client). Returns list of {uid, pid, timestamp, msg, type, key}.

    Uses 'ausearch -k key1 -k key2 ...' when available; otherwise returns empty list.
    If since is set (e.g. '10m'), passes -ts recent to limit output.
    """
    keys = keys or DEFAULT_AUDIT_KEYS
    cmd = ["ausearch", "-i"]
    for k in keys:
        cmd.extend(["-k", k])
    if since:
        cmd.extend(["-ts", "recent", "-ts", since])
    if audit_path:
        cmd.extend(["--input", audit_path])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning("ausearch failed: %s", result.stderr or result.stdout)
            return []
        return _parse_ausearch_output(result.stdout, keys)
    except FileNotFoundError:
        logger.debug("ausearch not available; audit attribution disabled")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ausearch timed out")
        return []
    except Exception as e:
        logger.warning("audit parse failed: %s", e)
        return []


def _parse_ausearch_output(stdout: str, keys: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Parse ausearch -i output into list of events with uid, pid, msg, type, timestamp."""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("----"):
            if current:
                events.append(current)
            current = {}
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "uid":
                try:
                    current["uid"] = int(v)
                except ValueError:
                    pass
            elif k == "pid":
                try:
                    current["pid"] = int(v)
                except ValueError:
                    pass
            elif k == "msg":
                current["msg"] = v
            elif k == "type":
                current["type"] = v
            elif k == "key":
                current["key"] = v
            elif k == "time":
                current["timestamp"] = v
    if current:
        events.append(current)
    return events


def get_uid_for_container_create(container_id: str, audit_events: list[dict[str, Any]]) -> int | None:
    """From pre-parsed audit events, try to find uid that created the given container_id. Returns uid or None."""
    for ev in reversed(audit_events):
        if ev.get("uid") is not None and container_id in (ev.get("msg") or ""):
            return ev["uid"]
    return None


def parse_audit_logs_single_key(key: str, audit_path: str | None = None, since: str | None = None) -> list[dict[str, Any]]:
    """Convenience: parse a single audit key."""
    return parse_audit_logs(keys=(key,), audit_path=audit_path, since=since)
