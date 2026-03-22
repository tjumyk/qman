"""Parse auditd logs for Docker socket/binary access to attribute container create / image pull to uid."""

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from app.utils import get_logger

logger = get_logger(__name__)

# Default keys: separate socket access vs client execution for easier correlation
DEFAULT_AUDIT_KEYS = ("docker-socket", "docker-client")

# Docker subcommand categories for filtering audit events
# These map Docker event actions to the docker CLI subcommands that cause them
DOCKER_SUBCOMMAND_CATEGORIES: dict[str, set[str]] = {
    "image_create": {"pull", "build", "load", "import", "commit"},
    "container_create": {"run", "create"},
    "container_exec": {"exec"},
    "other": {
        "ps", "images", "image", "inspect", "logs", "stats", "top", "port", "diff", "cp", "export", "save", "tag", "push", "login", "logout", "search", "version", "info", "system", "network", "volume", "compose",
        "container", "ls", "events", "rm", "start", "stop", "restart", "attach", "buildx", "builder", "context",
    },
}

# Reverse mapping: subcommand -> category
SUBCOMMAND_TO_CATEGORY: dict[str, str] = {}
for category, subcommands in DOCKER_SUBCOMMAND_CATEGORIES.items():
    for subcmd in subcommands:
        SUBCOMMAND_TO_CATEGORY[subcmd] = category


def extract_docker_subcommand(proctitle: str | None) -> str | None:
    """Extract the docker subcommand (verb) from a proctitle string for attribution matching.
    
    Handles both legacy form and object form so that attribution works for:
    - "docker run ..." and "docker container run ..." -> "run"
    - "docker pull ..." and "docker image pull ..." -> "pull"
    - "docker build ...", "docker buildx build ...", "docker builder build ..." -> "build"
    
    Examples:
        "docker load -i pg15.tar.gz" -> "load"
        "docker container run -it redis" -> "run"
        "docker image pull nginx:latest" -> "pull"
        "docker buildx build ..." / "docker builder build ..." -> "build"
        "docker start 2027" -> "start" (2027 is container ID prefix; we require first token to start with [a-z] so it is never mistaken for subcommand)
        "docker __complete attach" -> None (internal, not [a-z] lead)

    The first token after "docker" must start with a letter ([a-z]). So container ID prefixes
    like "2027" or "33f7fa7dcbfb" are never parsed as the subcommand.
    Returns the subcommand/verb (e.g., "load", "run", "pull") or None if not parseable.
    """
    if not proctitle:
        return None

    # Normalize: proctitle may have null bytes replaced with spaces
    proctitle = proctitle.replace("\x00", " ").strip()

    # Must start with "docker " (not docker-compose)
    if not re.match(r"^docker\s+", proctitle, re.IGNORECASE):
        return None

    rest = proctitle[6:].lstrip()  # after "docker"
    if not rest:
        return None

    # First token: subcommand or object (container/image/buildx)
    first_match = re.match(r"^([a-z][a-z0-9-]*)\s*", rest, re.IGNORECASE)
    if not first_match:
        return None
    first = first_match.group(1).lower()
    rest = rest[first_match.end() :].lstrip()

    # Object form: first token is object type, second is verb (Docker CLI reference).
    # We only include objects whose verb can overlap with attribution-relevant verbs
    # (run, create, build, pull, ...) so that we extract the real verb. Adding e.g.
    # "volume" would make "docker volume create" yield "create" and could falsely
    # match container-create attribution; so we only add: container, image, buildx, builder.
    if first in ("container", "image", "buildx", "builder") and rest:
        verb_match = re.match(r"^([a-z][a-z0-9-]*)\s*", rest, re.IGNORECASE)
        if verb_match:
            return verb_match.group(1).lower()
    return first


def get_subcommand_category(subcommand: str | None) -> str | None:
    """Get the category for a docker subcommand.
    
    Returns: "image_create", "container_create", "container_exec", "other", or None
    """
    if not subcommand:
        return None
    return SUBCOMMAND_TO_CATEGORY.get(subcommand.lower())

# ausearch -ts accepts keywords (recent, today, ...) or date + time. "recent" = 10 min only.
# Relative strings like "60m" are not supported; we convert them to absolute start date/time.
AUSEARCH_TS_KEYWORDS = frozenset(
    {"now", "recent", "this-hour", "boot", "today", "yesterday", "this-week", "week-ago", "this-month", "this-year", "checkpoint"}
)


def _since_to_start_ts(since: str) -> tuple[str, str] | None:
    """Convert relative 'since' (e.g. '60m', '1h') to (start_date, start_time) for ausearch -ts.
    Returns (MM/DD/YYYY, HH:MM:SS) in local time, or None if since is a keyword or invalid.
    """
    since = since.strip().lower()
    if since in AUSEARCH_TS_KEYWORDS:
        return None
    match = re.match(r"^(\d+)\s*(m|min|h|hr|d)?$", since)
    if not match:
        return None
    num = int(match.group(1))
    unit = (match.group(2) or "m").lower()
    if unit in ("m", "min"):
        delta = timedelta(minutes=num)
    elif unit in ("h", "hr"):
        delta = timedelta(hours=num)
    elif unit == "d":
        delta = timedelta(days=num)
    else:
        delta = timedelta(minutes=num)
    start = datetime.now(timezone.utc).astimezone() - delta
    return (start.strftime("%m/%d/%Y"), start.strftime("%H:%M:%S"))


def parse_audit_logs(
    keys: tuple[str, ...] | None = None,
    audit_path: str | None = None,
    since: str | None = None,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    """Parse audit logs for given keys (e.g. docker-socket, docker-client). Returns list of {uid, pid, timestamp, msg, type, key}.

    Uses 'ausearch -k key1 -k key2 ...' when available; otherwise returns empty list.
    If since is set: use -ts with that value. For relative times (e.g. '60m', '1h') we convert to
    absolute start date/time because ausearch does not accept '60m'; only keywords like 'recent' (10 min).
    If since is None, no -ts is passed (full log search; can be slow — use a larger timeout).
    """
    keys = keys or DEFAULT_AUDIT_KEYS
    # Note: -i (interpret) converts numeric UIDs to names which can cause parsing issues.
    # However, it also makes timestamps human-readable. We handle both formats in parsing.
    cmd = ["ausearch", "-i"]
    for k in keys:
        cmd.extend(["-k", k])
    if since:
        start_ts = _since_to_start_ts(since)
        if start_ts is not None:
            start_date, start_time = start_ts
            cmd.extend(["-ts", start_date, start_time])
            logger.debug("ausearch time range: since=%s -> %s %s", since, start_date, start_time)
        else:
            cmd.extend(["-ts", since])
    if audit_path:
        cmd.extend(["--input", audit_path])
    env = dict(os.environ)
    env["LC_TIME"] = "en_US.UTF-8"
    cmd_str = " ".join(cmd)
    logger.info("Running audit query: %s", cmd_str)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        # ausearch exit codes: 0=matches found, 1=no matches (not an error), 2+=error
        if result.returncode == 1:
            # No matches is normal when there are no Docker audit events in the time window
            output = (result.stderr or result.stdout or "").strip()
            if "no matches" in output.lower():
                logger.debug("ausearch: no audit events found (cmd: %s)", cmd_str)
            else:
                logger.info("ausearch returned no matches: %s (cmd: %s)", output, cmd_str)
            return []
        if result.returncode != 0:
            # Actual error (exit code 2+)
            logger.warning(
                "ausearch failed (exit=%d): %s (cmd: %s)",
                result.returncode,
                result.stderr or result.stdout,
                cmd_str,
            )
            return []
        events = _parse_ausearch_output(result.stdout, keys)
        logger.debug("ausearch found %d events (cmd: %s)", len(events), cmd_str)
        return events
    except FileNotFoundError:
        logger.info("ausearch not available (not installed); audit attribution disabled")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ausearch timed out after %.0fs (cmd: %s)", timeout, cmd_str)
        return []
    except Exception as e:
        logger.warning("audit parse failed: %s (cmd: %s)", e, cmd_str)
        return []


def _parse_ausearch_output(stdout: str, keys: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Parse ausearch -i output into list of events with uid, pid, msg, type, timestamp, docker_subcommand.
    
    Example ausearch -i output format:
    ----
    type=PROCTITLE msg=audit(...) : proctitle=docker load -i pg15.tar.gz
    type=SYSCALL msg=audit(02/16/2026 12:34:56.789:1234) : arch=x86_64 ... uid=1001 ...
    type=PATH ... name="/var/run/docker.sock" ...
    ----
    
    Note: The timestamp is in the msg field as audit(MM/DD/YYYY HH:MM:SS.mmm:serial).
    The -i (interpret) flag converts numeric UIDs to names, but we need numeric UIDs.
    
    The docker_subcommand field is extracted from the proctitle line (e.g., "load", "exec", "pull").
    """
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    raw_lines_count = len(stdout.splitlines()) if stdout else 0
    
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("----"):
            if current:
                # Extract docker subcommand from proctitle before appending
                proctitle = current.get("proctitle")
                if proctitle:
                    subcommand = extract_docker_subcommand(proctitle)
                    if subcommand:
                        current["docker_subcommand"] = subcommand
                        current["docker_subcommand_category"] = get_subcommand_category(subcommand)
                events.append(current)
            current = {}
            continue
        
        # Extract timestamp from msg=audit(MM/DD/YYYY HH:MM:SS.mmm:serial) format
        if "msg=audit(" in line:
            match = re.search(r"msg=audit\(([^)]+)\)", line)
            if match:
                audit_ts = match.group(1)
                # Format: "02/16/2026 12:34:56.789:1234" - extract date/time before the serial
                ts_match = re.match(r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})", audit_ts)
                if ts_match:
                    current["timestamp"] = ts_match.group(1)
                else:
                    # Try Unix timestamp format: "1234567890.123:serial"
                    unix_match = re.match(r"(\d+\.\d+):", audit_ts)
                    if unix_match:
                        current["timestamp_unix"] = float(unix_match.group(1))
        
        # Extract proctitle for docker subcommand detection
        if "type=PROCTITLE" in line:
            proctitle_match = re.search(r"proctitle=(.+?)(?:\s+$|\s+\w+=|$)", line)
            if proctitle_match:
                current["proctitle"] = proctitle_match.group(1).strip()
        
        if "=" in line:
            # Parse key=value pairs; handle multiple on same line
            # Use regex to find all key=value or key="value" pairs
            pairs = re.findall(r'(\w+)=("[^"]*"|\S+)', line)
            for k, v in pairs:
                v = v.strip('"')
                if k == "uid":
                    try:
                        current["uid"] = int(v)
                    except ValueError:
                        # -i flag may show username instead of numeric uid
                        current["uid_name"] = v
                elif k == "auid":
                    # auid (audit uid) is often more reliable than uid for tracking who initiated
                    try:
                        current["auid"] = int(v)
                    except ValueError:
                        current["auid_name"] = v
                elif k == "euid":
                    try:
                        current["euid"] = int(v)
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
                    current["key"] = v.strip('"')
                elif k == "exe":
                    current["exe"] = v
                elif k == "comm":
                    current["comm"] = v
    
    if current:
        # Extract docker subcommand from proctitle for final event
        proctitle = current.get("proctitle")
        if proctitle:
            subcommand = extract_docker_subcommand(proctitle)
            if subcommand:
                current["docker_subcommand"] = subcommand
                current["docker_subcommand_category"] = get_subcommand_category(subcommand)
        events.append(current)
    
    # Log summary of parsed events for debugging
    if events:
        uids_found = [e.get("uid") or e.get("auid") for e in events if e.get("uid") is not None or e.get("auid") is not None]
        ts_found = sum(1 for e in events if e.get("timestamp") or e.get("timestamp_unix"))
        keys_found = set(e.get("key") for e in events if e.get("key"))
        subcommands_found = [e.get("docker_subcommand") for e in events if e.get("docker_subcommand")]
        logger.info(
            "Parsed ausearch output: raw_lines=%d, events=%d, with_uid=%d, with_timestamp=%d, keys=%s, docker_subcommands=%s",
            raw_lines_count, len(events), len(uids_found), ts_found, list(keys_found), list(set(subcommands_found))
        )
        # Log first few events for debugging
        for i, ev in enumerate(events[:3]):
            logger.debug("Sample audit event %d: %s", i, ev)
    else:
        logger.info("Parsed ausearch output: raw_lines=%d, events=0", raw_lines_count)
    
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


def check_auditd_status() -> dict[str, Any]:
    """Check auditd status and rules for Docker quota attribution. Returns diagnostic info."""
    result: dict[str, Any] = {
        "ausearch_available": False,
        "auditctl_available": False,
        "auditd_running": False,
        "docker_rules_found": [],
        "errors": [],
    }
    
    # Check if ausearch is available
    try:
        proc = subprocess.run(["ausearch", "--version"], capture_output=True, text=True, timeout=5)
        result["ausearch_available"] = proc.returncode == 0
        if proc.returncode == 0:
            result["ausearch_version"] = proc.stdout.strip()
    except FileNotFoundError:
        result["errors"].append("ausearch not installed (install audit or auditd package)")
    except Exception as e:
        result["errors"].append(f"ausearch check failed: {e}")
    
    # Check if auditctl is available and get rules
    try:
        proc = subprocess.run(["auditctl", "-l"], capture_output=True, text=True, timeout=5)
        result["auditctl_available"] = proc.returncode == 0
        if proc.returncode == 0:
            rules = proc.stdout.strip().split("\n")
            result["total_rules"] = len(rules)
            # Find Docker-related rules
            for rule in rules:
                if "docker" in rule.lower() or "docker-socket" in rule or "docker-client" in rule:
                    result["docker_rules_found"].append(rule)
        else:
            result["errors"].append(f"auditctl -l failed: {proc.stderr}")
    except FileNotFoundError:
        result["errors"].append("auditctl not installed")
    except subprocess.TimeoutExpired:
        result["errors"].append("auditctl timed out")
    except Exception as e:
        result["errors"].append(f"auditctl check failed: {e}")
    
    # Check if auditd service is running
    try:
        proc = subprocess.run(["systemctl", "is-active", "auditd"], capture_output=True, text=True, timeout=5)
        result["auditd_running"] = proc.stdout.strip() == "active"
        result["auditd_status"] = proc.stdout.strip()
    except FileNotFoundError:
        # Try alternative check
        try:
            proc = subprocess.run(["pgrep", "-x", "auditd"], capture_output=True, text=True, timeout=5)
            result["auditd_running"] = proc.returncode == 0
        except Exception:
            pass
    except Exception as e:
        result["errors"].append(f"auditd status check failed: {e}")
    
    # Log summary
    if result["docker_rules_found"]:
        logger.info("Auditd status: running=%s, docker_rules=%d: %s",
                   result["auditd_running"], len(result["docker_rules_found"]), result["docker_rules_found"])
    else:
        logger.warning(
            "Auditd status: running=%s, NO docker rules found! "
            "Install rules from deploy/auditd-docker-quota.rules to /etc/audit/rules.d/ and restart auditd",
            result["auditd_running"]
        )
    
    if result["errors"]:
        logger.warning("Auditd check errors: %s", result["errors"])
    
    return result
