"""Sync Docker attribution from audit logs and Docker events (container create, image pull)."""

import time
from datetime import datetime
from typing import Any

import pwd

from app.db import SessionLocal
from app.models_db import Setting
from app.docker_quota.attribution_store import (
    get_container_attributions,
    get_image_attributions,
    get_layer_attributions,
    set_container_attribution,
    set_image_attribution,
    attribute_image_layers,
    get_layers_for_image,
)
from app.docker_quota.quota import _reconcile_layer_attributions
from app.docker_quota.cache import invalidate_container_cache, invalidate_image_cache
from app.docker_quota.docker_client import (
    list_containers,
    list_images,
    collect_events_since,
    _parse_created_iso,
    get_system_df,
)
from app.docker_quota.audit_parser import parse_audit_logs, DEFAULT_AUDIT_KEYS, check_auditd_status
from app.utils import get_logger

logger = get_logger(__name__)

SETTING_LAST_EVENTS_TS = "docker_events_last_ts"
TIME_WINDOW_SECONDS = 120  # Match container/image event to audit event within ±60s
AUDIT_LOOKBACK = "60m"  # ausearch -ts recent -ts 60m (if supported)


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
    
    # Build list of (uid, timestamp) from audit for time matching
    # Try multiple UID sources: uid, auid (audit uid - who initiated), euid
    audit_by_ts: list[tuple[float, int]] = []
    parse_failures = 0
    uid_missing = 0
    ts_missing = 0
    
    for ev in audit_events:
        # Prefer auid (audit uid) over uid for attribution - it tracks who initiated the action
        uid = ev.get("auid") or ev.get("uid") or ev.get("euid")
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
            continue
        
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
            continue
        
        audit_by_ts.append((ts_float, uid))
    
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
            unique_uids = set(uid for _, uid in audit_by_ts)
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
        best_delta = float("inf")
        for at, uid in audit_by_ts:
            delta = abs(at - created_ts)
            if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                best_delta = delta
                best_uid = uid
        
        if best_uid is not None:
            try:
                name = pwd.getpwuid(best_uid).pw_name
            except KeyError:
                name = f"user_{best_uid}"
            size_bytes = container_sizes.get(cid, 0)
            set_container_attribution(cid, name, best_uid, c.get("image"), size_bytes)
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


def sync_from_docker_events() -> int:
    """Collect Docker events since last run; correlate container create and image events (pull/build/commit/import/load/tag) with audit; update attribution. Returns count of container attributions set."""
    now_ts = time.time()
    last_s = _get_setting(SETTING_LAST_EVENTS_TS)
    since_ts = now_ts - (24 * 3600)
    if last_s:
        try:
            since_ts = float(last_s)
        except ValueError:
            pass
    events = collect_events_since(since_ts, max_seconds=90.0, max_events=500)
    audit_events = parse_audit_logs(keys=DEFAULT_AUDIT_KEYS, since=AUDIT_LOOKBACK)
    
    # Log event counts by type for diagnosis
    container_events = sum(1 for e in events if (e.get("type") or "").lower() == "container")
    image_events = sum(1 for e in events if (e.get("type") or "").lower() == "image")
    since_dt = datetime.fromtimestamp(since_ts).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        "sync_from_docker_events: docker_events=%d (container=%d, image=%d) since %s, audit_events=%d",
        len(events), container_events, image_events, since_dt, len(audit_events)
    )
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    image_sizes = df.get("images") or {}
    audit_by_ts: list[tuple[float, int]] = []
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
                    continue
        if uid is None:
            continue
        ts_str = ev.get("timestamp")
        if not ts_str:
            continue
        try:
            s = str(ts_str).strip()
            if s.replace(".", "", 1).isdigit():
                audit_by_ts.append((float(s), uid))
            elif " " in s:
                dt = datetime.strptime(s, "%m/%d/%Y %H:%M:%S")
                audit_by_ts.append((dt.timestamp(), uid))
        except Exception:
            continue
    audit_by_ts.sort(key=lambda x: x[0])
    attributions = {a["container_id"]: a for a in get_container_attributions()}
    image_attributions = {a["image_id"]: a for a in get_image_attributions()}
    set_count = 0
    cache_invalidated = False
    for ev in events:
        typ = (ev.get("type") or "").lower()
        action = (ev.get("action") or "").lower()
        eid = ev.get("id")
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
            best_uid = None
            best_delta = float("inf")
            for at, uid in audit_by_ts:
                delta = abs(at - ev_ts)
                if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                    best_delta = delta
                    best_uid = uid
            if best_uid is not None:
                try:
                    name = pwd.getpwuid(best_uid).pw_name
                except KeyError:
                    name = f"user_{best_uid}"
                size_bytes = container_sizes.get(eid, 0)
                set_container_attribution(eid, name, best_uid, None, size_bytes)
                set_count += 1
                attributions[eid] = {}
                logger.info("Attributed container %s to uid=%s from Docker event", eid[:12], best_uid)
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
                        logger.info("Attributed committed image %s to uid=%s (from container %s)", committed_image_id[:12], creator_uid, eid[:12])
                else:
                    # Try audit correlation
                    best_uid = None
                    best_delta = float("inf")
                    for at, uid in audit_by_ts:
                        delta = abs(at - ev_ts)
                        if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                            best_delta = delta
                            best_uid = uid
                    if best_uid is not None:
                        try:
                            name = pwd.getpwuid(best_uid).pw_name
                        except KeyError:
                            name = f"user_{best_uid}"
                        size_bytes = image_sizes.get(committed_image_id, 0)
                        set_image_attribution(committed_image_id, name, best_uid, size_bytes)
                        attribute_image_layers(committed_image_id, name, best_uid, "commit")
                        image_attributions[committed_image_id] = {}
                        logger.info("Attributed committed image %s to uid=%s from audit", committed_image_id[:12], best_uid)
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
                best_uid = None
                best_delta = float("inf")
                for at, uid in audit_by_ts:
                    delta = abs(at - ev_ts)
                    if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                        best_delta = delta
                        best_uid = uid
                if best_uid is not None:
                    try:
                        name = pwd.getpwuid(best_uid).pw_name
                    except KeyError:
                        name = f"user_{best_uid}"
                    size_bytes = image_sizes.get(eid, 0)
                    set_image_attribution(eid, name, best_uid, size_bytes)
                    attribute_image_layers(eid, name, best_uid, "pull")
                    image_attributions[eid] = {}
                    logger.info("Attributed image %s to uid=%s (puller) from Docker event", eid[:12], best_uid)
            elif action == "tag":
                # Tag event: check if image is new (not in attributions)
                if eid not in image_attributions:
                    # New image (likely from build) - try to attribute via audit
                    best_uid = None
                    best_delta = float("inf")
                    for at, uid in audit_by_ts:
                        delta = abs(at - ev_ts)
                        if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                            best_delta = delta
                            best_uid = uid
                    if best_uid is not None:
                        try:
                            name = pwd.getpwuid(best_uid).pw_name
                        except KeyError:
                            name = f"user_{best_uid}"
                        size_bytes = image_sizes.get(eid, 0)
                        set_image_attribution(eid, name, best_uid, size_bytes)
                        attribute_image_layers(eid, name, best_uid, "build")
                        image_attributions[eid] = {}
                        logger.info("Attributed image %s to uid=%s (builder, from tag event)", eid[:12], best_uid)
            elif action in ("import", "load"):
                if eid not in image_attributions:
                    best_uid = None
                    best_delta = float("inf")
                    for at, uid in audit_by_ts:
                        delta = abs(at - ev_ts)
                        if delta <= TIME_WINDOW_SECONDS and delta < best_delta:
                            best_delta = delta
                            best_uid = uid
                    if best_uid is not None:
                        try:
                            name = pwd.getpwuid(best_uid).pw_name
                        except KeyError:
                            name = f"user_{best_uid}"
                        size_bytes = image_sizes.get(eid, 0)
                        set_image_attribution(eid, name, best_uid, size_bytes)
                        attribute_image_layers(eid, name, best_uid, action)
                        image_attributions[eid] = {}
                        logger.info("Attributed image %s to uid=%s (%s) from Docker event", eid[:12], best_uid, action)
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
    
    # Reconcile layer attributions: remove layers that no longer exist in any image
    # Use the same all_images we already fetched above
    reconcile_start = time.time()
    all_layers_in_docker: set[str] = set()
    for img in all_images:
        img_id = img["id"]
        try:
            layers = get_layers_for_image(img_id)
            all_layers_in_docker.update(layers)
        except Exception as e:
            logger.warning("Failed to get layers for image %s: %s", img_id[:12], e)
    
    # Remove layer attributions for layers that no longer exist
    removed_count = _reconcile_layer_attributions(all_layers_in_docker)
    reconcile_time = time.time() - reconcile_start
    if removed_count > 0:
        logger.info("Reconciled layer attributions: removed %d layers that no longer exist (took %.2fs)", 
                   removed_count, reconcile_time)
    total_time = time.time() - start_time
    logger.debug("sync_existing_images: total=%.2fs (attributed=%d images, removed=%d layers)", 
                total_time, count, removed_count)
    return count


def run_sync_docker_attribution() -> dict[str, int]:
    """Run both audit-based and Docker-events-based sync, plus sync existing images. Returns counts."""
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
    logger.info("Docker attribution sync complete: from_audit=%d, from_events=%d, existing_images=%d", a, b, c)
    return {"from_audit": a, "from_events": b, "existing_images": c}
