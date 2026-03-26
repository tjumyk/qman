"""Parse auditd logs for Docker socket/binary access to attribute container create / image pull to uid."""

import os
import re
import shlex
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


def normalize_audit_proctitle(raw: str | None) -> str | None:
    """Turn kernel/ausearch proctitle into plain text when it is hex-encoded argv (null-separated).

    Raw audit often logs ``proctitle=646F636B6572...`` (hex of ``docker\\0restart\\0...``).
    Interpreted ``ausearch -i`` output may already use readable ``docker ...`` text; that path is unchanged.
    """
    if not raw:
        return None
    s = raw.strip()
    if len(s) < 12 or len(s) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", s):
        return s.replace("\x00", " ").strip()
    try:
        b = bytes.fromhex(s)
    except ValueError:
        return s.replace("\x00", " ").strip()
    text = b.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    text = re.sub(r"\s+", " ", text)
    if re.match(r"^docker\s+", text, re.IGNORECASE):
        return text
    return s


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


def _decode_audit_quoted_arg(raw: str) -> str:
    """Decode EXECVE ``aN="..."`` value (minimal C escapes used by auditd)."""
    if "\\" not in raw:
        return raw
    try:
        return raw.encode("utf-8", errors="surrogateescape").decode("unicode_escape")
    except UnicodeDecodeError:
        return raw


def parse_execve_audit_line(line: str) -> tuple[int | None, list[str]]:
    """Parse ``type=EXECVE`` line: return ``(argc, argv)`` with argv in order a0..a(argc-1).

    Handles quoted ``aN="..."`` (with backslash escapes) and unquoted ``aN=token`` fragments.
    """
    if "type=EXECVE" not in line:
        return None, []
    argc_m = re.search(r"\bargc=(\d+)\b", line)
    argc: int | None = int(argc_m.group(1)) if argc_m else None
    by_idx: dict[int, str] = {}
    for m in re.finditer(r'a(\d+)="((?:\\.|[^"\\])*)"', line):
        by_idx[int(m.group(1))] = _decode_audit_quoted_arg(m.group(2))
    for m in re.finditer(r"\ba(\d+)=([^\s]+)", line):
        i = int(m.group(1))
        if i in by_idx:
            continue
        tok = m.group(2).strip('"')
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            tok = _decode_audit_quoted_arg(tok[1:-1])
        by_idx[i] = tok
    if not by_idx:
        return argc, []
    max_i = max(by_idx.keys())
    argv = [by_idx.get(i, "") for i in range(max_i + 1)]
    if argc is not None and argc <= len(argv):
        argv = argv[:argc]
    return argc, argv


def _is_docker_invocation(argv: list[str]) -> bool:
    if not argv:
        return False
    return os.path.basename(argv[0]).lower() == "docker"


def _merge_execve_into_event(current: dict[str, Any]) -> None:
    """Prefer full ``docker`` argv from EXECVE when proctitle is missing, non-docker, or truncated."""
    argv = current.get("execve_argv")
    if not isinstance(argv, list) or not argv:
        return
    if not _is_docker_invocation(argv):
        return
    try:
        cmdline = shlex.join(str(a) for a in argv)
    except (TypeError, ValueError):
        cmdline = " ".join(str(a) for a in argv)
    current["execve_cmdline"] = cmdline
    pt = (current.get("proctitle") or "").strip()
    prefer_execve = (
        not pt
        or not re.match(r"^docker\s+", pt, re.IGNORECASE)
        or len(cmdline) > len(pt) + 8
    )
    if prefer_execve:
        current["proctitle"] = cmdline
        current["proctitle_source"] = "execve"


def _finalize_audit_event(current: dict[str, Any]) -> None:
    """Derive ``docker_subcommand`` / category from best available cmdline (after EXECVE merge)."""
    _merge_execve_into_event(current)
    proctitle = current.get("proctitle")
    if not proctitle:
        return
    subcommand = extract_docker_subcommand(proctitle)
    if subcommand:
        current["docker_subcommand"] = subcommand
        current["docker_subcommand_category"] = get_subcommand_category(subcommand)


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

    Uses ``ausearch -k key1 -k key2 ...`` (without ``-i``) when available; otherwise returns empty list.
    Raw output keeps numeric UIDs and epoch-style ``msg=audit(epoch:seq)`` times, which are stable for parsing
    and attribution. Interpreted ``ausearch -i`` pastes are still accepted by ``_parse_ausearch_output``.

    If since is set: use -ts with that value. For relative times (e.g. '60m', '1h') we convert to
    absolute start date/time because ausearch does not accept '60m'; only keywords like 'recent' (10 min).
    If since is None, no -ts is passed (full log search; can be slow — use a larger timeout).
    """
    keys = keys or DEFAULT_AUDIT_KEYS
    cmd = ["ausearch"]
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
    """Parse ausearch text into list of events with uid, pid, cwd, execve argv, proctitle, docker_subcommand.

    Primary shape is **raw** ``ausearch`` output: hex ``proctitle``, ``msg=audit(epoch.mmm:seq)``,
    numeric ``uid``/``auid``. Also handles **interpreted** ``ausearch -i`` pastes (plaintext proctitle,
    ``MM/DD/YYYY`` times, username uids via ``uid_name``). When present, ``type=EXECVE`` rebuilds the full
    command line when kernel ``PROCTITLE`` is truncated.

    Example raw-ish line types:
    ----
    type=PROCTITLE msg=audit(1774339582.741:1028819): proctitle=646F636B6572...
    type=SYSCALL msg=audit(1774339582.741:1028819): ... uid=1044 ...
    ----

    ``docker_subcommand`` is derived from the best available cmdline (EXECVE merge beats short proctitle).
    """
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    raw_lines_count = len(stdout.splitlines()) if stdout else 0
    
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("----"):
            if current:
                _finalize_audit_event(current)
                events.append(current)
            current = {}
            continue

        if line.startswith("time->"):
            # ``time->Tue Mar 24 13:34:44 2026`` (human-readable stamp from ausearch)
            current["audit_time_text"] = line[len("time->") :].strip()
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
                raw_pt = proctitle_match.group(1).strip()
                current["proctitle"] = normalize_audit_proctitle(raw_pt) or raw_pt

        if "type=CWD" in line:
            cwd_m = re.search(r'\bcwd="((?:\\.|[^"\\])*)"', line)
            if cwd_m:
                current["cwd"] = _decode_audit_quoted_arg(cwd_m.group(1))
            else:
                cwd_plain = re.search(r'\bcwd=([^\s]+)\s*$', line)
                if cwd_plain:
                    current["cwd"] = cwd_plain.group(1).strip().strip('"')

        if "type=EXECVE" in line:
            argc, argv = parse_execve_audit_line(line)
            if argc is not None:
                current["execve_argc"] = argc
            if argv:
                current["execve_argv"] = argv
        
        if "=" in line:
            # Parse key=value pairs; handle multiple on same line
            # Use regex to find all key=value or key="value" pairs
            pairs = re.findall(r'(\w+)=("[^"]*"|\S+)', line)
            for k, v in pairs:
                if k == "argc" or (len(k) >= 2 and k[0] == "a" and k[1:].isdigit()):
                    continue
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
        _finalize_audit_event(current)
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


def parse_ausearch_stdout(
    stdout: str, keys: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Parse ausearch stdout (raw or ``-i``), e.g. pasted manual output or captured in tests."""
    return _parse_ausearch_output(stdout, keys)


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
