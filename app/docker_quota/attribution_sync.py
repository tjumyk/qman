"""Sync Docker attribution from audit logs and Docker events (container create, image pull)."""

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import pwd

from app.db import SessionLocal
from app.models_db import (
    DockerContainerAttributionOverride,
    DockerImageAttributionOverride,
    DockerLayerAttributionOverride,
    DockerUsageAuditEvent,
    DockerUsageDockerEvent,
    DockerVolumeAttributionOverride,
    Setting,
)
from app.docker_quota.attribution_store import (
    get_container_attributions,
    get_image_attributions,
    get_layer_attributions,
    get_volume_attributions,
    get_volume_attribution,
    set_container_attribution,
    set_image_attribution,
    set_volume_attribution,
    set_volume_last_mounted_at,
    update_volume_size,
    attribute_image_layers,
    get_layers_for_image,
    reconcile_volume_disk_usage,
    reconcile_volume_last_used,
)
from app.docker_quota.quota import _reconcile_layer_attributions, _reconcile_image_attributions, _reconcile_volume_attributions
from app.docker_quota.cache import invalidate_container_cache, invalidate_image_cache
from app.docker_quota.docker_client import (
    list_containers,
    list_images,
    collect_events_since,
    _parse_created_iso,
    get_system_df,
    get_container_volume_mounts,
)
from app.docker_quota.audit_parser import parse_audit_logs, DEFAULT_AUDIT_KEYS, check_auditd_status
from app.utils import get_logger

logger = get_logger(__name__)

SETTING_LAST_EVENTS_TS = "docker_events_last_ts"
TIME_WINDOW_SECONDS = 120  # Match container/image event to audit event within ±120s (symmetric)
# For long-running commands (load, pull, build), the Docker event marks *completion*.
# The audit event (command start) occurs *before* the Docker event.
# Use asymmetric window: look back further, small forward buffer for clock skew.
LONG_COMMAND_LOOKBACK_SECONDS = 600  # 10 minutes - for large image loads/pulls/builds
LONG_COMMAND_FORWARD_SECONDS = 10  # Small buffer for clock skew
AUDIT_LOOKBACK = "90m"  # ausearch -ts 90m - covers sync interval (10min) + buffer for restarts/delays
MAX_DOCKER_EVENTS = 2000  # Max Docker events to collect per sync (increased for 10-min sync interval)

# Mapping from Docker event action to required audit docker subcommand(s)
# Only match audit events with relevant docker subcommands
ACTION_TO_SUBCOMMANDS: dict[str, set[str]] = {
    "pull": {"pull"},
    "load": {"load"},
    "import": {"import"},
    "tag": {"build", "tag"},  # tag events can come from build (or buildx build) or explicit tag
    "commit": {"commit"},
    "create": {"run", "create"},  # container create events
}


def _resolve_image_id(image_ref: str) -> str | None:
    """Resolve an image reference (name:tag or partial ID) to its full image ID (sha256:...).
    
    Docker events use image name:tag (e.g. 'busybox:latest') while our internal storage
    uses full image IDs (sha256:...). This function bridges that gap.
    """
    if not image_ref:
        return None
    # Already a full ID
    if image_ref.startswith("sha256:"):
        return image_ref
    try:
        import docker
        client = docker.from_env()
        try:
            img = client.images.get(image_ref)
            return img.id  # Returns full sha256:... ID
        except docker.errors.ImageNotFound:
            logger.debug("Image not found for ref: %s", image_ref)
            return None
        finally:
            client.close()
    except Exception as e:
        logger.debug("Failed to resolve image ref %s: %s", image_ref, e)
        return None


def _get_setting(key: str) -> str | None:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
        return row.value if row else None
    finally:
        db.close()


def _set_setting(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _json_dumps_stable(payload: Any) -> str:
    """Deterministic JSON encoding for stable fingerprints."""
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _payload_hash_short(payload_str: str, length: int = 10) -> str:
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()[:length]


def _fingerprint(prefix: str, *parts: str) -> str:
    base = "|".join([prefix, *parts])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _audit_event_fingerprint(
    event_ts_float: float | None,
    audit_key: str | None,
    docker_subcommand: str | None,
    payload_str: str,
) -> str:
    ts_part = str(event_ts_float) if event_ts_float is not None else "none"
    return _fingerprint(
        "audit",
        ts_part,
        audit_key or "",
        docker_subcommand or "",
        _payload_hash_short(payload_str),
    )


def _docker_event_fingerprint(
    event_ts_float: float | None,
    docker_event_type: str | None,
    docker_action: str | None,
    actor_id: str | None,
    volume_name: str | None,
    payload_str: str,
) -> str:
    ts_part = str(event_ts_float) if event_ts_float is not None else "none"
    return _fingerprint(
        "docker",
        ts_part,
        docker_event_type or "",
        docker_action or "",
        actor_id or "",
        volume_name or "",
        _payload_hash_short(payload_str),
    )


def _docker_usage_event_entity_fields(
    typ: str,
    actor_id: str | None,
    ev: dict[str, Any],
) -> tuple[str | None, str | None, str | None, str | None]:
    """Derive (container_id, image_id, image_ref, volume_name) from a decoded Docker events entry.

    Used when persisting ``DockerUsageDockerEvent`` so admin entity views match rows by FK,
    not only ``docker_actor_id`` (previously only ``container``+``create`` set ``container_id``).
    """
    typ_l = (typ or "").lower()
    aid = (actor_id or "").strip() or None

    if typ_l == "container" and aid:
        return (aid, None, None, None)

    if typ_l == "image" and aid:
        from_ref = ev.get("from")
        ref: str | None = None
        if isinstance(from_ref, str) and from_ref.strip():
            ref = from_ref.strip()
        return (None, aid, ref, None)

    if typ_l == "volume" and aid:
        return (None, None, None, aid)

    return (None, None, None, None)


def _audit_events_by_time_window(
    audit_events: list[dict[str, Any]],
) -> dict[int, int]:
    """Build approximate (time_bucket_sec -> uid) from audit events. time_bucket_sec = floor(timestamp/60)."""
    bucket_to_uid: dict[int, int] = {}
    for ev in audit_events:
        uid = ev.get("uid")
        if uid is None:
            continue
        ts_str = ev.get("timestamp") or ev.get("msg") or ""
        try:
            # ausearch -i often has "time" in msg or we need to parse timestamp
            if ts_str.isdigit():
                t = int(ts_str)
            else:
                continue
        except ValueError:
            continue
        bucket = t // TIME_WINDOW_SECONDS
        bucket_to_uid[bucket] = uid
    return bucket_to_uid


def _parse_audit_timestamp(ev: dict[str, Any]) -> float | None:
    """Try to get Unix timestamp from audit event (time= or from msg)."""
    ts = ev.get("timestamp") or ev.get("time")
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    # ausearch -i may output "time" as date string
    try:
        if ts.isdigit():
            return float(ts)
        return None
    except Exception:
        return None


class AuditMatchResult:
    """Result of audit event matching for attribution."""
    __slots__ = ("uid", "delta", "audit_ts", "subcommand", "proctitle", "audit_fingerprint")
    
    def __init__(self, uid: int | None = None, delta: float = float("inf"), 
                 audit_ts: float | None = None, subcommand: str | None = None,
                 proctitle: str | None = None, audit_fingerprint: str | None = None):
        self.uid = uid
        self.delta = delta
        self.audit_ts = audit_ts
        self.subcommand = subcommand
        self.proctitle = proctitle
        self.audit_fingerprint = audit_fingerprint
    
    @property
    def found(self) -> bool:
        return self.uid is not None
    
    def audit_time_str(self) -> str:
        """Return formatted audit timestamp string."""
        if self.audit_ts is None:
            return "N/A"
        return datetime.fromtimestamp(self.audit_ts).strftime("%Y-%m-%d %H:%M:%S")
    
    def command_str(self) -> str:
        """Return the audit command for logging (proctitle or subcommand fallback)."""
        if self.proctitle:
            # Truncate long commands for readability in logs
            if len(self.proctitle) > 60:
                return self.proctitle[:57] + "..."
            return self.proctitle
        return self.subcommand or "unknown"


def _find_best_audit_match(
    ev_ts: float,
    audit_by_ts: list[tuple[float, int, str | None, str | None, str]],
    required_subcommands: set[str] | None = None,
    use_asymmetric_window: bool = False,
) -> AuditMatchResult:
    """Find the best matching audit event for a Docker event timestamp.
    
    Args:
        ev_ts: Docker event timestamp (Unix timestamp)
        audit_by_ts: List of (timestamp, uid, docker_subcommand, proctitle) tuples, sorted by timestamp
        required_subcommands: If set, only consider audit events with matching docker_subcommand.
                              If None, matches any audit event (legacy behavior for container create).
        use_asymmetric_window: If True, use asymmetric time window for long-running commands
                               (look back further since audit event = command start, Docker event = completion).
                               If False, use symmetric window (for quick commands).
    
    Returns:
        AuditMatchResult with uid, delta, audit_ts, subcommand, proctitle (uid is None if no match found).
    """
    result = AuditMatchResult()
    
    if use_asymmetric_window:
        # For load/pull/build: audit event (command start) is BEFORE Docker event (completion)
        # Look back up to LONG_COMMAND_LOOKBACK_SECONDS, small forward buffer for clock skew
        lookback = LONG_COMMAND_LOOKBACK_SECONDS
        forward = LONG_COMMAND_FORWARD_SECONDS
    else:
        # Symmetric window for quick commands
        lookback = TIME_WINDOW_SECONDS
        forward = TIME_WINDOW_SECONDS
    
    for at, uid, subcommand, proctitle, audit_fingerprint in audit_by_ts:
        # Check time window: audit_ts should be in [ev_ts - lookback, ev_ts + forward]
        if at < ev_ts - lookback:
            continue
        if at > ev_ts + forward:
            # Since audit_by_ts is sorted, no more matches possible
            break
        
        # Check subcommand filter
        if required_subcommands is not None:
            if subcommand is None or subcommand not in required_subcommands:
                continue
        
        # For asymmetric window, prefer audit events that are BEFORE the Docker event
        # (command start should precede command completion)
        if use_asymmetric_window and at > ev_ts:
            # Audit event after Docker event - less likely to be the cause
            # Still consider it but with a penalty
            delta = (at - ev_ts) * 10  # 10x penalty for forward matches
        else:
            delta = abs(at - ev_ts)
        
        if delta < result.delta:
            result.uid = uid
            result.delta = delta
            result.audit_ts = at
            result.subcommand = subcommand
            result.proctitle = proctitle
            result.audit_fingerprint = audit_fingerprint
    
    return result


def sync_containers_from_audit() -> int:
    """Find containers without attribution; match Created time to audit events (docker-socket, docker-client); set attribution. Returns count set."""
    attributions = {a["container_id"]: a for a in get_container_attributions()}
    # use_cache=False: background sync must see current Docker state for correct attribution
    containers = list_containers(all_containers=True, use_cache=False)
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    audit_events = parse_audit_logs(keys=DEFAULT_AUDIT_KEYS, since=AUDIT_LOOKBACK)
    
    # Count containers by status for logging
    already_attributed = sum(1 for c in containers if c["id"] in attributions)
    has_qman_label = sum(1 for c in containers if c["id"] not in attributions and (c.get("labels") or {}).get("qman.user"))
    needs_audit = len(containers) - already_attributed - has_qman_label
    
    logger.info(
        "sync_containers_from_audit: containers=%d (already_attributed=%d, needs_label_sync=%d, needs_audit=%d), audit_events=%d",
        len(containers), already_attributed, has_qman_label, needs_audit, len(audit_events)
    )
    
    if not audit_events:
        logger.info("No audit events for container correlation (auditd may not be configured or no Docker activity in time window)")
    
    db_events = SessionLocal()
    audit_event_by_fp: dict[str, DockerUsageAuditEvent] = {}
    pending_audit_events: list[DockerUsageAuditEvent] = []
    seen_audit_fps: set[str] = set()
    
    # Build list of (uid, timestamp) from audit for time matching
    # Try multiple UID sources: uid, auid (audit uid - who initiated), euid
    audit_by_ts: list[tuple[float, int, str]] = []
    parse_failures = 0
    uid_missing = 0
    ts_missing = 0
    
    for ev in audit_events:
        # Prefer auid (audit uid) over uid for attribution - it tracks who initiated the action
        uid = ev.get("auid") or ev.get("uid") or ev.get("euid")
        host_user_name: str | None = None
        if uid is None:
            # Try to resolve uid from name if -i flag gave us names
            uid_name = ev.get("auid_name") or ev.get("uid_name")
            if uid_name:
                try:
                    uid = pwd.getpwnam(uid_name).pw_uid
                except KeyError:
                    pass
        if uid is None:
            uid_missing += 1
        else:
            try:
                host_user_name = pwd.getpwuid(uid).pw_name
            except KeyError:
                host_user_name = f"user_{uid}"
        
        # Get timestamp - try multiple sources
        ts_float: float | None = None
        
        # First try Unix timestamp (most reliable)
        if ev.get("timestamp_unix"):
            ts_float = ev["timestamp_unix"]
        elif ev.get("timestamp"):
            ts_str = ev["timestamp"]
            try:
                # Format: "02/16/2026 12:34:56"
                if " " in str(ts_str):
                    dt = datetime.strptime(ts_str.strip(), "%m/%d/%Y %H:%M:%S")
                    ts_float = dt.timestamp()
            except Exception as e:
                logger.debug("Failed to parse audit timestamp '%s': %s", ts_str, e)
                parse_failures += 1
        
        if ts_float is None:
            ts_missing += 1

        # Only use audit events that could have created a container (run/create)
        # so we don't attribute to someone who only ran e.g. "docker ps" or "docker container ls"
        subcommand = (ev.get("docker_subcommand") or "").lower()

        payload_str = _json_dumps_stable(ev)
        fp = _audit_event_fingerprint(ts_float, ev.get("key"), subcommand, payload_str)
        if fp not in seen_audit_fps:
            seen_audit_fps.add(fp)
            pending_audit_events.append(
                DockerUsageAuditEvent(
                    event_ts=datetime.fromtimestamp(ts_float) if ts_float is not None else None,
                    uid=uid,
                    host_user_name=host_user_name,
                    audit_key=ev.get("key"),
                    docker_subcommand=subcommand or None,
                    payload=payload_str,
                    fingerprint=fp,
                )
            )

        if (
            uid is not None
            and ts_float is not None
            and subcommand in (ACTION_TO_SUBCOMMANDS.get("create") or set())
        ):
            audit_by_ts.append((ts_float, uid, fp))
    
    # Persist all parsed audit events for this sync window (dedupe via fingerprint).
    if pending_audit_events:
        fps = [e.fingerprint for e in pending_audit_events]
        existing = (
            db_events.query(DockerUsageAuditEvent)
            .filter(DockerUsageAuditEvent.fingerprint.in_(fps))
            .all()
        )
        audit_event_by_fp = {r.fingerprint: r for r in existing}
        for row in pending_audit_events:
            if row.fingerprint not in audit_event_by_fp:
                db_events.add(row)
                audit_event_by_fp[row.fingerprint] = row
        db_events.commit()

    audit_by_ts.sort(key=lambda x: x[0])
    
    if audit_events:
        logger.info(
            "Audit events processed: total=%d, usable=%d (uid_missing=%d, ts_missing=%d, parse_failures=%d)",
            len(audit_events), len(audit_by_ts), uid_missing, ts_missing, parse_failures
        )
        if audit_by_ts:
            # Log time range of usable events
            oldest = datetime.fromtimestamp(audit_by_ts[0][0]).strftime("%Y-%m-%d %H:%M:%S")
            newest = datetime.fromtimestamp(audit_by_ts[-1][0]).strftime("%Y-%m-%d %H:%M:%S")
            unique_uids = set(uid for _, uid, _ in audit_by_ts)
            logger.info("Audit time range: %s to %s, unique_uids=%s", oldest, newest, list(unique_uids))
    set_count = 0
    containers_checked = 0
    containers_no_created_ts = 0
    containers_no_audit_match = 0
    
    for c in containers:
        cid = c["id"]
        if cid in attributions:
            # Update size if container already attributed
            size_bytes = container_sizes.get(cid, 0)
            if size_bytes > 0:
                set_container_attribution(
                    cid,
                    attributions[cid]["host_user_name"],
                    attributions[cid].get("uid"),
                    attributions[cid].get("image_id"),
                    size_bytes,
                )
            continue
        labels = c.get("labels") or {}
        qman_user = labels.get("qman.user")
        if qman_user:
            # Container has explicit label - attribute it directly (no audit needed)
            try:
                uid = pwd.getpwuid(int(qman_user)).pw_uid if qman_user.isdigit() else pwd.getpwnam(qman_user).pw_uid
                name = pwd.getpwuid(uid).pw_name
            except (KeyError, ValueError):
                uid = None
                name = qman_user
            size_bytes = container_sizes.get(cid, 0)
            set_container_attribution(cid, name, uid, c.get("image"), size_bytes)
            set_count += 1
            logger.info("Attributed container %s to %s from qman.user label", cid[:12], name)
            continue
        
        containers_checked += 1
        created_str = c.get("created")
        created_ts = _parse_created_iso(created_str)
        if created_ts <= 0:
            containers_no_created_ts += 1
            logger.debug("Container %s has invalid/missing created timestamp: %s", cid[:12], created_str)
            continue
        
        # Find audit event within TIME_WINDOW_SECONDS
        best_uid: int | None = None
        best_fp: str | None = None
        best_delta = float("inf")
        for at, uid, fp in audit_by_ts:
            delta = abs(at - created_ts)
            if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                best_delta = delta
                best_uid = uid
                best_fp = fp
        
        if best_uid is not None:
            try:
                name = pwd.getpwuid(best_uid).pw_name
            except KeyError:
                name = f"user_{best_uid}"
            size_bytes = container_sizes.get(cid, 0)
            set_container_attribution(cid, name, best_uid, c.get("image"), size_bytes)
            if best_fp and best_fp in audit_event_by_fp:
                audit_row = audit_event_by_fp[best_fp]
                audit_row.used_for_auto_attribution = True
                audit_row.container_id = cid
                audit_row.uid = best_uid
                audit_row.host_user_name = name
            set_count += 1
            logger.info(
                "Attributed container %s to uid=%s from audit (delta=%.1fs, created=%s)",
                cid[:12], best_uid, best_delta,
                datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d %H:%M:%S")
            )
        else:
            containers_no_audit_match += 1
            if containers_no_audit_match <= 5:  # Log first few unmatched for debugging
                logger.debug(
                    "Container %s (created %s) has no audit match within %ds window",
                    cid[:12],
                    datetime.fromtimestamp(created_ts).strftime("%Y-%m-%d %H:%M:%S"),
                    TIME_WINDOW_SECONDS
                )
    
    db_events.commit()
    db_events.close()

    # Reconcile stale manual container overrides (containers no longer exist).
    try:
        override_db = SessionLocal()
        try:
            container_ids_in_docker = {c["id"] for c in containers}
            removed = 0
            rows = override_db.query(DockerContainerAttributionOverride).all()
            for r in rows:
                if r.container_id not in container_ids_in_docker:
                    override_db.delete(r)
                    removed += 1
            if removed:
                override_db.commit()
                logger.info(
                    "Reconciled Docker container attribution overrides: removed %d stale rows",
                    removed,
                )
        finally:
            override_db.close()
    except Exception as e:
        logger.warning("Failed to reconcile container overrides: %s", e)

    logger.info(
        "sync_containers_from_audit result: attributed=%d, checked_for_audit=%d (no_created_ts=%d, no_audit_match=%d)",
        set_count, containers_checked, containers_no_created_ts, containers_no_audit_match
    )
    
    if set_count == 0 and needs_audit > 0:
        logger.info(
            "Troubleshooting: %d containers need audit attribution but no matches found. "
            "Possible causes: (1) auditd not configured - check /etc/audit/rules.d/, "
            "(2) audit events outside %ds time window, "
            "(3) containers created before auditd was enabled",
            needs_audit, TIME_WINDOW_SECONDS
        )
    return set_count


def sync_from_docker_events(
    *,
    full_history: bool = False,
    docker_max_seconds: float | None = None,
    docker_max_events: int | None = None,
    audit_timeout: float | None = None,
) -> int:
    """Collect Docker events since last run (or full history); correlate with audit; update attribution.

    When ``full_history`` is True (one-shot backfill): Docker events from epoch to now (bounded by
    ``docker_max_seconds`` / ``docker_max_events``) and audit via ``ausearch`` with no ``-ts`` limit
    (bounded by ``audit_timeout``). Heavy — intended for manual CLI / maintenance.
    """
    now_ts = time.time()
    if full_history:
        until_ts = int(now_ts)
        d_sec = docker_max_seconds if docker_max_seconds is not None else 7200.0
        d_evt = docker_max_events if docker_max_events is not None else 200_000
        events = collect_events_since(
            0, until_ts=until_ts, max_seconds=d_sec, max_events=d_evt
        )
        a_timeout = audit_timeout if audit_timeout is not None else 600.0
        audit_events = parse_audit_logs(
            keys=DEFAULT_AUDIT_KEYS, since=None, timeout=a_timeout
        )
        since_ts = 0.0
    else:
        last_s = _get_setting(SETTING_LAST_EVENTS_TS)
        since_ts = now_ts - (24 * 3600)
        if last_s:
            try:
                since_ts = float(last_s)
            except ValueError:
                pass
        events = collect_events_since(
            int(since_ts), max_seconds=90.0, max_events=MAX_DOCKER_EVENTS
        )
        a_timeout = audit_timeout if audit_timeout is not None else 60.0
        audit_events = parse_audit_logs(
            keys=DEFAULT_AUDIT_KEYS, since=AUDIT_LOOKBACK, timeout=a_timeout
        )

    # Log event counts by type for diagnosis
    container_events = sum(1 for e in events if (e.get("type") or "").lower() == "container")
    image_events = sum(1 for e in events if (e.get("type") or "").lower() == "image")
    if full_history:
        until_str = datetime.fromtimestamp(
            int(now_ts), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(
            "sync_from_docker_events (full_history): docker_events=%d (container=%d, image=%d) "
            "until %s, audit_events=%d",
            len(events),
            container_events,
            image_events,
            until_str,
            len(audit_events),
        )
    else:
        since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        logger.info(
            "sync_from_docker_events: docker_events=%d (container=%d, image=%d) since %s, audit_events=%d",
            len(events),
            container_events,
            image_events,
            since_dt,
            len(audit_events),
        )
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    image_sizes = df.get("images") or {}

    db_events = SessionLocal()
    audit_event_by_fp: dict[str, DockerUsageAuditEvent] = {}
    pending_audit_events: list[DockerUsageAuditEvent] = []
    seen_audit_fps: set[str] = set()

    # Build audit_by_ts with (timestamp, uid, docker_subcommand) for command-filtered matching
    audit_by_ts: list[tuple[float, int, str | None, str | None, str]] = []
    for ev in audit_events:
        # Get UID from auid (preferred) or uid; fall back to name resolution
        uid = ev.get("auid") or ev.get("uid") or ev.get("euid")
        if uid is None:
            # ausearch -i converts UIDs to names, try to resolve them
            uid_name = ev.get("auid_name") or ev.get("uid_name")
            if uid_name:
                try:
                    uid = pwd.getpwnam(uid_name).pw_uid
                except KeyError:
                    pass
        host_user_name: str | None = None
        if uid is not None:
            try:
                host_user_name = pwd.getpwuid(uid).pw_name
            except KeyError:
                host_user_name = f"user_{uid}"

        ts_str = ev.get("timestamp")
        ts_float: float | None = None
        if ts_str:
            try:
                s = str(ts_str).strip()
                if s.replace(".", "", 1).isdigit():
                    ts_float = float(s)
                elif " " in s:
                    dt = datetime.strptime(s, "%m/%d/%Y %H:%M:%S")
                    ts_float = dt.timestamp()
            except Exception:
                ts_float = None

        # Get docker subcommand and proctitle for filtering and logging
        docker_subcommand_raw = ev.get("docker_subcommand")
        docker_subcommand = docker_subcommand_raw.lower() if docker_subcommand_raw else None
        proctitle = ev.get("proctitle")

        payload_str = _json_dumps_stable(ev)
        fp = _audit_event_fingerprint(ts_float, ev.get("key"), docker_subcommand, payload_str)
        if fp not in seen_audit_fps:
            seen_audit_fps.add(fp)
            pending_audit_events.append(
                DockerUsageAuditEvent(
                    event_ts=datetime.fromtimestamp(ts_float) if ts_float is not None else None,
                    uid=uid,
                    host_user_name=host_user_name,
                    audit_key=ev.get("key"),
                    docker_subcommand=docker_subcommand,
                    payload=payload_str,
                    fingerprint=fp,
                )
            )

        # Candidate for matching requires timestamp, uid, and docker subcommand.
        if uid is not None and ts_float is not None and docker_subcommand is not None:
            audit_by_ts.append((ts_float, uid, docker_subcommand, proctitle, fp))
    audit_by_ts.sort(key=lambda x: x[0])

    # Persist all parsed audit events for this sync window (dedupe via fingerprint).
    if pending_audit_events:
        fps = [e.fingerprint for e in pending_audit_events]
        existing = (
            db_events.query(DockerUsageAuditEvent)
            .filter(DockerUsageAuditEvent.fingerprint.in_(fps))
            .all()
        )
        audit_event_by_fp = {r.fingerprint: r for r in existing}
        for row in pending_audit_events:
            if row.fingerprint not in audit_event_by_fp:
                db_events.add(row)
                audit_event_by_fp[row.fingerprint] = row
        db_events.commit()
    
    # Log subcommand distribution for debugging
    subcommand_counts: dict[str, int] = {}
    for _, _, subcmd, _, _ in audit_by_ts:
        key = subcmd or "(none)"
        subcommand_counts[key] = subcommand_counts.get(key, 0) + 1
    if subcommand_counts:
        logger.debug("Audit subcommand distribution: %s", subcommand_counts)

    # Persist Docker events for admin review (dedupe via fingerprint).
    docker_event_by_fp: dict[str, DockerUsageDockerEvent] = {}
    pending_docker_events: list[DockerUsageDockerEvent] = []
    seen_docker_fps: set[str] = set()
    docker_event_fps_by_index: list[str] = []

    for ev in events:
        typ = (ev.get("type") or "").lower()
        action = (ev.get("action") or "").lower()
        actor_id = ev.get("id")

        time_nano = ev.get("time_nano")
        try:
            ev_ts_float = int(time_nano) / 1e9 if time_nano else None
        except (TypeError, ValueError):
            ev_ts_float = None
        if ev_ts_float is not None and ev_ts_float <= 0:
            ev_ts_float = None

        payload_str = _json_dumps_stable(ev)
        fp = _docker_event_fingerprint(
            ev_ts_float,
            typ,
            action,
            actor_id,
            None,
            payload_str,
        )
        docker_event_fps_by_index.append(fp)

        if fp in seen_docker_fps:
            continue
        seen_docker_fps.add(fp)

        cid, img_id, img_ref, vol_name = _docker_usage_event_entity_fields(typ, actor_id, ev)
        pending_docker_events.append(
            DockerUsageDockerEvent(
                event_ts=datetime.fromtimestamp(ev_ts_float) if ev_ts_float is not None else None,
                container_id=cid,
                image_id=img_id,
                image_ref=img_ref,
                volume_name=vol_name,
                uid=None,
                host_user_name=None,
                docker_event_type=typ,
                docker_action=action,
                docker_actor_id=actor_id,
                payload=payload_str,
                fingerprint=fp,
            )
        )

    if pending_docker_events:
        fps = [e.fingerprint for e in pending_docker_events]
        existing = (
            db_events.query(DockerUsageDockerEvent)
            .filter(DockerUsageDockerEvent.fingerprint.in_(fps))
            .all()
        )
        docker_event_by_fp = {r.fingerprint: r for r in existing}
        for row in pending_docker_events:
            if row.fingerprint not in docker_event_by_fp:
                db_events.add(row)
                docker_event_by_fp[row.fingerprint] = row
        db_events.commit()
    attributions = {a["container_id"]: a for a in get_container_attributions()}
    image_attributions = {a["image_id"]: a for a in get_image_attributions()}
    set_count = 0
    cache_invalidated = False
    for ev_idx, ev in enumerate(events):
        typ = (ev.get("type") or "").lower()
        action = (ev.get("action") or "").lower()
        eid = ev.get("id")
        docker_fp = docker_event_fps_by_index[ev_idx]
        if not eid:
            continue
        
        # Invalidate cache when container/image events occur (event-driven cache invalidation)
        if not cache_invalidated:
            if typ == "container" and action in ("create", "destroy", "die", "kill", "start", "stop"):
                invalidate_container_cache()
                cache_invalidated = True
            elif typ == "image" and action in ("pull", "push", "tag", "untag", "delete", "remove"):
                invalidate_image_cache()
                cache_invalidated = True
        
        time_nano = ev.get("time_nano")
        try:
            ev_ts = int(time_nano) / 1e9 if time_nano else 0
        except (TypeError, ValueError):
            ev_ts = 0
        # Container create
        if typ == "container" and action == "create":
            if eid in attributions:
                # Update size if container already attributed
                size_bytes = container_sizes.get(eid, 0)
                if size_bytes > 0:
                    set_container_attribution(
                        eid,
                        attributions[eid]["host_user_name"],
                        attributions[eid].get("uid"),
                        attributions[eid].get("image_id"),
                        size_bytes,
                    )
                continue
            # Filter to only "docker run" or "docker create" commands
            required_subcommands = ACTION_TO_SUBCOMMANDS.get("create")
            match = _find_best_audit_match(
                ev_ts, audit_by_ts,
                required_subcommands=required_subcommands,
                use_asymmetric_window=False,  # Container create is quick
            )
            if match.found:
                try:
                    name = pwd.getpwuid(match.uid).pw_name
                except KeyError:
                    name = f"user_{match.uid}"
                size_bytes = container_sizes.get(eid, 0)
                set_container_attribution(eid, name, match.uid, None, size_bytes)
                docker_row = docker_event_by_fp.get(docker_fp)
                if docker_row:
                    docker_row.used_for_auto_attribution = True
                    docker_row.container_id = eid
                    docker_row.uid = match.uid
                    docker_row.host_user_name = name
                if match.audit_fingerprint:
                    audit_row = audit_event_by_fp.get(match.audit_fingerprint)
                    if audit_row:
                        audit_row.used_for_auto_attribution = True
                        audit_row.container_id = eid
                        audit_row.uid = match.uid
                        audit_row.host_user_name = name
                set_count += 1
                attributions[eid] = {}
                ev_time_str = datetime.fromtimestamp(ev_ts).strftime("%Y-%m-%d %H:%M:%S")
                logger.info(
                    "Attributed container %s to %s (uid=%s): docker_event=%s, audit_cmd=%s at %s, delta=%.1fs",
                    eid[:12], name, match.uid, ev_time_str, match.command_str(), match.audit_time_str(), match.delta
                )
        # Container start: update last_mounted_at for each volume (for actual-disk scan smart skip)
        elif typ == "container" and action == "start":
            try:
                import docker
                client = docker.from_env()
                try:
                    container = client.containers.get(eid)
                    mounts = container.attrs.get("Mounts") or []
                    ev_dt = datetime.fromtimestamp(ev_ts, tz=timezone.utc)
                    volume_names: list[str] = []
                    for mount in mounts:
                        if mount.get("Type") == "volume":
                            vol_name = mount.get("Name")
                            if vol_name:
                                volume_names.append(vol_name)
                                set_volume_last_mounted_at(vol_name, ev_dt)
                    # Record persisted docker events for each mounted volume so the
                    # admin review queue can list volume-associated events.
                    if volume_names:
                        payload_str = _json_dumps_stable(ev)
                        ev_ts_float = ev_ts if ev_ts and ev_ts > 0 else None
                        volume_fps = [
                            _docker_event_fingerprint(ev_ts_float, typ, action, eid, vn, payload_str)
                            for vn in volume_names
                        ]
                        existing = (
                            db_events.query(DockerUsageDockerEvent)
                            .filter(DockerUsageDockerEvent.fingerprint.in_(volume_fps))
                            .all()
                        )
                        existing_fps = {r.fingerprint for r in existing}
                        for vn in volume_names:
                            fp = _docker_event_fingerprint(ev_ts_float, typ, action, eid, vn, payload_str)
                            if fp in existing_fps:
                                continue
                            db_events.add(
                                DockerUsageDockerEvent(
                                    event_ts=datetime.fromtimestamp(ev_ts_float) if ev_ts_float is not None else None,
                                    container_id=eid,
                                    image_id=None,
                                    image_ref=None,
                                    volume_name=vn,
                                    uid=None,
                                    host_user_name=None,
                                    docker_event_type=typ,
                                    docker_action=action,
                                    docker_actor_id=eid,
                                    payload=payload_str,
                                    fingerprint=fp,
                                )
                            )
                finally:
                    client.close()
            except Exception as e:
                logger.debug("Could not update volume last_mounted_at for container %s: %s", eid[:12], e)
        # Container commit (creates new image)
        elif typ == "container" and action == "commit":
            # eid is container_id, but commit creates a new image
            # We'll handle this by checking for new images after commit
            # For now, we can try to get the committed image ID from the event
            committed_image_id = ev.get("id")  # May be the new image ID
            if committed_image_id and committed_image_id not in image_attributions:
                # Try to attribute to container owner or find via audit
                container_att = attributions.get(eid)
                if container_att:
                    creator_uid = container_att.get("uid")
                    creator_name = container_att.get("host_user_name")
                    if creator_uid is not None and creator_name:
                        size_bytes = image_sizes.get(committed_image_id, 0)
                        set_image_attribution(committed_image_id, creator_name, creator_uid, size_bytes)
                        attribute_image_layers(committed_image_id, creator_name, creator_uid, "commit")
                        image_attributions[committed_image_id] = {}
                        docker_row = docker_event_by_fp.get(docker_fp)
                        if docker_row:
                            docker_row.used_for_auto_attribution = True
                            docker_row.image_id = committed_image_id
                            docker_row.uid = creator_uid
                            docker_row.host_user_name = creator_name
                        logger.info("Attributed committed image %s to uid=%s (from container %s)", committed_image_id[:12], creator_uid, eid[:12])
                else:
                    # Try audit correlation - filter to "docker commit" commands
                    required_subcommands = ACTION_TO_SUBCOMMANDS.get("commit")
                    match = _find_best_audit_match(
                        ev_ts, audit_by_ts,
                        required_subcommands=required_subcommands,
                        use_asymmetric_window=False,  # Commit is relatively quick
                    )
                    if match.found:
                        try:
                            name = pwd.getpwuid(match.uid).pw_name
                        except KeyError:
                            name = f"user_{match.uid}"
                        size_bytes = image_sizes.get(committed_image_id, 0)
                        set_image_attribution(committed_image_id, name, match.uid, size_bytes)
                        attribute_image_layers(committed_image_id, name, match.uid, "commit")
                        image_attributions[committed_image_id] = {}
                        docker_row = docker_event_by_fp.get(docker_fp)
                        if docker_row:
                            docker_row.used_for_auto_attribution = True
                            docker_row.image_id = committed_image_id
                            docker_row.uid = match.uid
                            docker_row.host_user_name = name
                        if match.audit_fingerprint:
                            audit_row = audit_event_by_fp.get(match.audit_fingerprint)
                            if audit_row:
                                audit_row.used_for_auto_attribution = True
                                audit_row.image_id = committed_image_id
                                audit_row.uid = match.uid
                                audit_row.host_user_name = name
                        ev_time_str = datetime.fromtimestamp(ev_ts).strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(
                            "Attributed committed image %s to %s (uid=%s): docker_event=%s, audit_cmd=%s at %s, delta=%.1fs",
                            committed_image_id[:12], name, match.uid, ev_time_str, match.command_str(), match.audit_time_str(), match.delta
                        )
        # Image events: pull, tag (for new images from build), import, load
        elif typ == "image":
            # Resolve image name/tag to full ID (Docker events use name:tag, we store sha256:...)
            resolved_id = _resolve_image_id(eid) if eid else None
            if resolved_id:
                eid = resolved_id
            
            if action == "pull":
                if eid in image_attributions:
                    # Update size if image already attributed
                    size_bytes = image_sizes.get(eid, 0)
                    if size_bytes > 0:
                        set_image_attribution(
                            eid,
                            image_attributions[eid]["puller_host_user_name"],
                            image_attributions[eid].get("puller_uid"),
                            size_bytes,
                        )
                    continue
                # Filter to only "docker pull" commands; use asymmetric window (pull can take minutes)
                required_subcommands = ACTION_TO_SUBCOMMANDS.get("pull")
                match = _find_best_audit_match(
                    ev_ts, audit_by_ts,
                    required_subcommands=required_subcommands,
                    use_asymmetric_window=True,  # Pull can take a long time
                )
                if match.found:
                    try:
                        name = pwd.getpwuid(match.uid).pw_name
                    except KeyError:
                        name = f"user_{match.uid}"
                    size_bytes = image_sizes.get(eid, 0)
                    set_image_attribution(eid, name, match.uid, size_bytes)
                    attribute_image_layers(eid, name, match.uid, "pull")
                    image_attributions[eid] = {}
                    docker_row = docker_event_by_fp.get(docker_fp)
                    if docker_row:
                        docker_row.used_for_auto_attribution = True
                        docker_row.image_id = eid
                        docker_row.uid = match.uid
                        docker_row.host_user_name = name
                    if match.audit_fingerprint:
                        audit_row = audit_event_by_fp.get(match.audit_fingerprint)
                        if audit_row:
                            audit_row.used_for_auto_attribution = True
                            audit_row.image_id = eid
                            audit_row.uid = match.uid
                            audit_row.host_user_name = name
                    ev_time_str = datetime.fromtimestamp(ev_ts).strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(
                        "Attributed image %s to %s (uid=%s) via pull: docker_event=%s, audit_cmd=%s at %s, delta=%.1fs",
                        eid[:12], name, match.uid, ev_time_str, match.command_str(), match.audit_time_str(), match.delta
                    )
            elif action == "tag":
                # Tag event: check if image is new (not in attributions)
                if eid not in image_attributions:
                    # New image (likely from build) - try to attribute via audit
                    # Filter to "docker build" or "docker tag" commands; use asymmetric window for builds
                    required_subcommands = ACTION_TO_SUBCOMMANDS.get("tag")
                    match = _find_best_audit_match(
                        ev_ts, audit_by_ts,
                        required_subcommands=required_subcommands,
                        use_asymmetric_window=True,  # Build can take a long time
                    )
                    if match.found:
                        try:
                            name = pwd.getpwuid(match.uid).pw_name
                        except KeyError:
                            name = f"user_{match.uid}"
                        size_bytes = image_sizes.get(eid, 0)
                        set_image_attribution(eid, name, match.uid, size_bytes)
                        attribute_image_layers(eid, name, match.uid, "build")
                        image_attributions[eid] = {}
                        docker_row = docker_event_by_fp.get(docker_fp)
                        if docker_row:
                            docker_row.used_for_auto_attribution = True
                            docker_row.image_id = eid
                            docker_row.uid = match.uid
                            docker_row.host_user_name = name
                        if match.audit_fingerprint:
                            audit_row = audit_event_by_fp.get(match.audit_fingerprint)
                            if audit_row:
                                audit_row.used_for_auto_attribution = True
                                audit_row.image_id = eid
                                audit_row.uid = match.uid
                                audit_row.host_user_name = name
                        ev_time_str = datetime.fromtimestamp(ev_ts).strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(
                            "Attributed image %s to %s (uid=%s) via build/tag: docker_event=%s, audit_cmd=%s at %s, delta=%.1fs",
                            eid[:12], name, match.uid, ev_time_str, match.command_str(), match.audit_time_str(), match.delta
                        )
            elif action in ("import", "load"):
                if eid not in image_attributions:
                    # Filter to "docker import" or "docker load" commands; use asymmetric window
                    required_subcommands = ACTION_TO_SUBCOMMANDS.get(action)
                    match = _find_best_audit_match(
                        ev_ts, audit_by_ts,
                        required_subcommands=required_subcommands,
                        use_asymmetric_window=True,  # Load/import can take a long time
                    )
                    if match.found:
                        try:
                            name = pwd.getpwuid(match.uid).pw_name
                        except KeyError:
                            name = f"user_{match.uid}"
                        size_bytes = image_sizes.get(eid, 0)
                        set_image_attribution(eid, name, match.uid, size_bytes)
                        attribute_image_layers(eid, name, match.uid, action)
                        image_attributions[eid] = {}
                        docker_row = docker_event_by_fp.get(docker_fp)
                        if docker_row:
                            docker_row.used_for_auto_attribution = True
                            docker_row.image_id = eid
                            docker_row.uid = match.uid
                            docker_row.host_user_name = name
                        if match.audit_fingerprint:
                            audit_row = audit_event_by_fp.get(match.audit_fingerprint)
                            if audit_row:
                                audit_row.used_for_auto_attribution = True
                                audit_row.image_id = eid
                                audit_row.uid = match.uid
                                audit_row.host_user_name = name
                        ev_time_str = datetime.fromtimestamp(ev_ts).strftime("%Y-%m-%d %H:%M:%S")
                        logger.info(
                            "Attributed image %s to %s (uid=%s) via %s: docker_event=%s, audit_cmd=%s at %s, delta=%.1fs",
                            eid[:12], name, match.uid, action, ev_time_str, match.command_str(), match.audit_time_str(), match.delta
                        )
    db_events.commit()
    db_events.close()
    _set_setting(SETTING_LAST_EVENTS_TS, str(now_ts))
    return set_count


def sync_existing_images() -> int:
    """Sync layers for all existing images in DockerImageAttribution that don't have layers attributed yet."""
    import time
    start_time = time.time()
    image_attributions = get_image_attributions()
    layer_attributions = {r["layer_id"] for r in get_layer_attributions()}
    # Fetch image list once; use for sizes and for reconciliation (no get_system_df call needed here)
    all_images = list_images(use_cache=False)
    image_sizes = {img["id"]: (img.get("size") or 0) for img in all_images}
    
    logger.info(
        "sync_existing_images: image_attributions=%d, layer_attributions=%d, docker_images=%d",
        len(image_attributions), len(layer_attributions), len(all_images)
    )
    count = 0
    for img_att in image_attributions:
        image_id = img_att["image_id"]
        # Check if any layers are missing
        layers = get_layers_for_image(image_id)
        has_new_layers = any(layer_id not in layer_attributions for layer_id in layers)
        if has_new_layers:
            # Update size and attribute layers
            size_bytes = image_sizes.get(image_id, 0)
            if size_bytes > 0:
                set_image_attribution(
                    image_id,
                    img_att["puller_host_user_name"],
                    img_att.get("puller_uid"),
                    size_bytes,
                )
            new_layers_count = attribute_image_layers(
                image_id,
                img_att["puller_host_user_name"],
                img_att.get("puller_uid"),
                None,  # creation_method unknown for existing images
            )
            if new_layers_count > 0:
                count += 1
                logger.info("Attributed %s new layers for existing image %s", new_layers_count, image_id[:12])
    
    # Reconcile attributions: remove entries for images/layers that no longer exist
    # Use the same all_images we already fetched above
    reconcile_start = time.time()
    image_ids_in_docker = {img["id"] for img in all_images}
    
    # Reconcile image attributions first
    removed_images = _reconcile_image_attributions(image_ids_in_docker)
    if removed_images > 0:
        logger.info("Reconciled image attributions: removed %d images that no longer exist", removed_images)
    
    # Then reconcile layer attributions
    all_layers_in_docker: set[str] = set()
    for img in all_images:
        img_id = img["id"]
        try:
            layers = get_layers_for_image(img_id)
            all_layers_in_docker.update(layers)
        except Exception as e:
            logger.warning("Failed to get layers for image %s: %s", img_id[:12], e)
    
    removed_layers = _reconcile_layer_attributions(all_layers_in_docker)
    reconcile_time = time.time() - reconcile_start
    if removed_layers > 0:
        logger.info("Reconciled layer attributions: removed %d layers that no longer exist (took %.2fs)", 
                   removed_layers, reconcile_time)

    # Reconcile stale manual image/layer overrides.
    try:
        override_db = SessionLocal()
        try:
            removed_image_overrides = 0
            for row in override_db.query(DockerImageAttributionOverride).all():
                if row.image_id not in image_ids_in_docker:
                    override_db.delete(row)
                    removed_image_overrides += 1

            removed_layer_overrides = 0
            for row in override_db.query(DockerLayerAttributionOverride).all():
                if row.layer_id not in all_layers_in_docker:
                    override_db.delete(row)
                    removed_layer_overrides += 1

            if removed_image_overrides > 0 or removed_layer_overrides > 0:
                override_db.commit()
                logger.info(
                    "Reconciled Docker manual overrides (images/layers): removed %d images, %d layers",
                    removed_image_overrides,
                    removed_layer_overrides,
                )
        finally:
            override_db.close()
    except Exception as e:
        logger.warning("Failed to reconcile image/layer overrides: %s", e)

    total_time = time.time() - start_time
    logger.debug("sync_existing_images: total=%.2fs (attributed=%d images, removed=%d images, removed=%d layers)", 
                total_time, count, removed_images, removed_layers)
    return count


def sync_volume_attributions() -> dict[str, int]:
    """Sync volume attributions from Docker volumes.
    
    Attribution priority:
    1. qman.user label on volume -> explicit owner (source='label')
    2. Existing attribution in DB -> preserved (only update size)
    3. First container (by creation time) that mounts it -> use container's attributed owner
    4. Unattributed -> volume not stored (counted in unattributed_bytes)
    
    Returns dict with counts: new_from_label, new_from_container, updated_size, unattributed.
    """
    start_time = time.time()
    
    # Get volume data from Docker
    df = get_system_df(include_volumes=True)
    volumes = df.get("volumes") or {}
    if not volumes:
        logger.info("sync_volume_attributions: no volumes found")
        return {"new_from_label": 0, "new_from_container": 0, "updated_size": 0, "unattributed": 0}
    
    # Get container attributions (for resolving volume -> container -> user)
    container_attributions = {att["container_id"]: att for att in get_container_attributions()}
    
    # Get existing volume attributions
    existing_vol_attributions = {att["volume_name"]: att for att in get_volume_attributions()}
    
    # Get volume -> container mappings (sorted by container creation time)
    volume_to_containers = get_container_volume_mounts()
    
    counts = {"new_from_label": 0, "new_from_container": 0, "updated_size": 0, "unattributed": 0}
    
    for vol_name, vol_info in volumes.items():
        size_bytes = vol_info.get("size", 0)
        labels = vol_info.get("labels") or {}
        
        # Priority 1: qman.user label on volume
        qman_user = labels.get("qman.user")
        if qman_user:
            uid = None
            try:
                uid = pwd.getpwnam(qman_user).pw_uid
            except KeyError:
                logger.debug("Volume %s has qman.user=%s but user not found in passwd", vol_name, qman_user)
            set_volume_attribution(vol_name, qman_user, uid, size_bytes, attribution_source="label")
            if vol_name not in existing_vol_attributions:
                counts["new_from_label"] += 1
                logger.info("Attributed volume %s to %s (uid=%s) via label", vol_name, qman_user, uid)
            else:
                counts["updated_size"] += 1
            continue
        
        # Priority 2: Existing attribution in DB (preserve owner, update size)
        if vol_name in existing_vol_attributions:
            update_volume_size(vol_name, size_bytes)
            counts["updated_size"] += 1
            continue
        
        # Priority 3: First container (by creation time) that mounts this volume
        containers_for_vol = volume_to_containers.get(vol_name, [])
        attributed = False
        for container_info in containers_for_vol:
            cid = container_info["container_id"]
            container_att = container_attributions.get(cid)
            if container_att:
                host_user_name = container_att["host_user_name"]
                uid = container_att.get("uid")
                set_volume_attribution(vol_name, host_user_name, uid, size_bytes, attribution_source="container")
                counts["new_from_container"] += 1
                logger.info(
                    "Attributed volume %s to %s (uid=%s) via first container %s",
                    vol_name, host_user_name, uid, cid[:12]
                )
                attributed = True
                break
        
        if not attributed:
            # Priority 4: Unattributed (no label, no attributed container)
            counts["unattributed"] += 1
            logger.debug("Volume %s is unattributed (no label, no attributed container)", vol_name)
    
    # Reconcile: remove attributions and disk usage / last_used for volumes that no longer exist
    reconcile_start = time.time()
    volume_names_in_docker = set(volumes.keys())
    removed_volumes = _reconcile_volume_attributions(volume_names_in_docker)
    removed_disk_usage = reconcile_volume_disk_usage(volume_names_in_docker)
    removed_last_used = reconcile_volume_last_used(volume_names_in_docker)
    reconcile_time = time.time() - reconcile_start
    if removed_volumes > 0 or removed_disk_usage > 0 or removed_last_used > 0:
        logger.info(
            "Reconciled volume data: removed %d attributions, %d disk_usage, %d last_used (took %.2fs)",
            removed_volumes, removed_disk_usage, removed_last_used, reconcile_time
        )

    # Reconcile stale manual volume overrides (volumes no longer exist in Docker).
    try:
        override_db = SessionLocal()
        try:
            removed_volume_overrides = 0
            for row in override_db.query(DockerVolumeAttributionOverride).all():
                if row.volume_name not in volume_names_in_docker:
                    override_db.delete(row)
                    removed_volume_overrides += 1

            if removed_volume_overrides > 0:
                override_db.commit()
                logger.info(
                    "Reconciled Docker manual volume overrides: removed %d stale rows",
                    removed_volume_overrides,
                )
        finally:
            override_db.close()
    except Exception as e:
        logger.warning("Failed to reconcile volume overrides: %s", e)

    counts["removed"] = removed_volumes
    
    elapsed = time.time() - start_time
    logger.info(
        "sync_volume_attributions: total=%.2fs (volumes=%d, new_from_label=%d, new_from_container=%d, "
        "updated_size=%d, unattributed=%d, removed=%d)",
        elapsed, len(volumes), counts["new_from_label"], counts["new_from_container"], 
        counts["updated_size"], counts["unattributed"], counts["removed"]
    )
    return counts


def run_sync_docker_attribution() -> dict[str, int]:
    """Run all Docker attribution syncs: audit-based, events-based, images, and volumes. Returns counts."""
    logger.info("Starting Docker attribution sync")
    
    # Check auditd status on first run or periodically for diagnostics
    try:
        audit_status = check_auditd_status()
        if not audit_status.get("docker_rules_found"):
            logger.warning(
                "No Docker audit rules found - audit-based attribution will not work. "
                "See deploy/auditd-docker-quota.rules for setup instructions."
            )
    except Exception as e:
        logger.debug("Auditd status check failed: %s", e)
    
    a = sync_containers_from_audit()
    b = sync_from_docker_events()
    c = sync_existing_images()
    d = sync_volume_attributions()
    logger.info(
        "Docker attribution sync complete: from_audit=%d, from_events=%d, existing_images=%d, "
        "volumes(new_label=%d, new_container=%d, updated=%d, unattributed=%d)",
        a, b, c, d["new_from_label"], d["new_from_container"], d["updated_size"], d["unattributed"]
    )
    return {
        "from_audit": a, 
        "from_events": b, 
        "existing_images": c,
        "volumes_new_label": d["new_from_label"],
        "volumes_new_container": d["new_from_container"],
        "volumes_updated": d["updated_size"],
        "volumes_unattributed": d["unattributed"],
    }
