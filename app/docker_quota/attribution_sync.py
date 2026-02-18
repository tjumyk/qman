"""Sync Docker attribution from audit logs and Docker events (container create, image pull)."""

import time
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
from app.docker_quota.docker_client import (
    list_containers,
    list_images,
    collect_events_since,
    _parse_created_iso,
    get_system_df,
)
from app.docker_quota.audit_parser import parse_audit_logs, DEFAULT_AUDIT_KEYS
from app.utils import get_logger

logger = get_logger(__name__)

SETTING_LAST_EVENTS_TS = "docker_events_last_ts"
TIME_WINDOW_SECONDS = 120  # Match container/image event to audit event within ±60s
AUDIT_LOOKBACK = "60m"  # ausearch -ts recent -ts 60m (if supported)


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
    from datetime import datetime
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
        from datetime import datetime
        if ts.isdigit():
            return float(ts)
        return None
    except Exception:
        return None


def sync_containers_from_audit() -> int:
    """Find containers without attribution; match Created time to audit events (docker-socket, docker-client); set attribution. Returns count set."""
    attributions = {a["container_id"]: a for a in get_container_attributions()}
    containers = list_containers(all_containers=True)
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    audit_events = parse_audit_logs(keys=DEFAULT_AUDIT_KEYS, since=AUDIT_LOOKBACK)
    if not audit_events:
        logger.debug("No audit events for container correlation")
    # Build list of (uid, timestamp) from audit for time matching
    audit_by_ts: list[tuple[float, int]] = []
    for ev in audit_events:
        uid = ev.get("uid")
        if uid is None:
            continue
        # ausearch output often has 'time' field with format like "02/16/2026 12:34:56"
        ts_str = ev.get("timestamp")
        if not ts_str:
            continue
        try:
            from datetime import datetime
            if " " in str(ts_str):
                dt = datetime.strptime(ts_str.strip(), "%m/%d/%Y %H:%M:%S")
            else:
                continue
            audit_by_ts.append((dt.timestamp(), uid))
        except Exception:
            continue
    audit_by_ts.sort(key=lambda x: x[0])
    set_count = 0
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
        if labels.get("qman.user"):
            continue
        created_str = c.get("created")
        created_ts = _parse_created_iso(created_str)
        if created_ts <= 0:
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
            logger.info("Attributed container %s to uid=%s from audit (time window)", cid[:12], best_uid)
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
    events = collect_events_since(since_ts, max_seconds=5.0, max_events=500)
    audit_events = parse_audit_logs(keys=DEFAULT_AUDIT_KEYS, since=AUDIT_LOOKBACK)
    df = get_system_df()
    container_sizes = df.get("containers") or {}
    image_sizes = df.get("images") or {}
    audit_by_ts: list[tuple[float, int]] = []
    for ev in audit_events:
        uid = ev.get("uid")
        if uid is None:
            continue
        ts_str = ev.get("timestamp")
        if not ts_str:
            continue
        try:
            from datetime import datetime
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
    for ev in events:
        typ = (ev.get("type") or "").lower()
        action = (ev.get("action") or "").lower()
        eid = ev.get("id")
        if not eid:
            continue
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
    image_attributions = get_image_attributions()
    layer_attributions = {r["layer_id"] for r in get_layer_attributions()}
    df = get_system_df()
    image_sizes = df.get("images") or {}
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
    return count


def run_sync_docker_attribution() -> dict[str, int]:
    """Run both audit-based and Docker-events-based sync, plus sync existing images. Returns counts."""
    a = sync_containers_from_audit()
    b = sync_from_docker_events()
    c = sync_existing_images()
    return {"from_audit": a, "from_events": b, "existing_images": c}
