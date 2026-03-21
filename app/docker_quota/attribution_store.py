"""Persistence for Docker container/image attribution and per-user quota limits (slave)."""

from typing import Any

from app.db import SessionLocal
from app.models_db import (
    DockerContainerAttribution,
    DockerContainerAttributionOverride,
    DockerImageAttribution,
    DockerImageAttributionOverride,
    DockerLayerAttribution,
    DockerLayerAttributionOverride,
    DockerUserQuotaLimit,
    DockerVolumeAttribution,
    DockerVolumeAttributionOverride,
    DockerVolumeDiskUsage,
    DockerVolumeLastUsed,
)
from app.utils import get_logger

logger = get_logger(__name__)


def get_container_attributions() -> list[dict[str, Any]]:
    """Return all container attributions: container_id -> host_user_name, uid, image_id, size_bytes."""
    db = SessionLocal()
    try:
        rows = db.query(DockerContainerAttribution).all()
        return [
            {
                "container_id": r.container_id,
                "host_user_name": r.host_user_name,
                "uid": r.uid,
                "image_id": r.image_id,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def set_container_attribution(
    container_id: str,
    host_user_name: str,
    uid: int | None,
    image_id: str | None = None,
    size_bytes: int = 0,
) -> None:
    """Upsert one container attribution."""
    db = SessionLocal()
    try:
        row = db.query(DockerContainerAttribution).filter(
            DockerContainerAttribution.container_id == container_id
        ).first()
        if row:
            row.host_user_name = host_user_name
            row.uid = uid
            if image_id is not None:
                row.image_id = image_id
            row.size_bytes = size_bytes
        else:
            db.add(
                DockerContainerAttribution(
                    container_id=container_id,
                    host_user_name=host_user_name,
                    uid=uid,
                    image_id=image_id,
                    size_bytes=size_bytes,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_image_attributions() -> list[dict[str, Any]]:
    """Return all image attributions: image_id -> puller_host_user_name, puller_uid, size_bytes."""
    db = SessionLocal()
    try:
        rows = db.query(DockerImageAttribution).all()
        return [
            {
                "image_id": r.image_id,
                "puller_host_user_name": r.puller_host_user_name,
                "puller_uid": r.puller_uid,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def set_image_attribution(
    image_id: str,
    puller_host_user_name: str,
    puller_uid: int | None,
    size_bytes: int = 0,
) -> None:
    """Upsert one image attribution (puller)."""
    db = SessionLocal()
    try:
        row = db.query(DockerImageAttribution).filter(DockerImageAttribution.image_id == image_id).first()
        if row:
            row.puller_host_user_name = puller_host_user_name
            row.puller_uid = puller_uid
            row.size_bytes = size_bytes
        else:
            db.add(
                DockerImageAttribution(
                    image_id=image_id,
                    puller_host_user_name=puller_host_user_name,
                    puller_uid=puller_uid,
                    size_bytes=size_bytes,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_container_attribution(container_id: str) -> None:
    """Remove container attribution (e.g. after container removed)."""
    db = SessionLocal()
    try:
        db.query(DockerContainerAttribution).filter(
            DockerContainerAttribution.container_id == container_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_layer_attribution(layer_id: str) -> None:
    """Remove layer attribution (e.g. after image/layer removed)."""
    db = SessionLocal()
    try:
        db.query(DockerLayerAttribution).filter(
            DockerLayerAttribution.layer_id == layer_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_image_attribution(image_id: str) -> None:
    """Remove image attribution (e.g. after image removed via docker rmi)."""
    db = SessionLocal()
    try:
        db.query(DockerImageAttribution).filter(
            DockerImageAttribution.image_id == image_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_user_quota_limit(uid: int) -> int:
    """Return block_hard_limit (1K blocks) for uid. 0 if not set."""
    db = SessionLocal()
    try:
        row = db.query(DockerUserQuotaLimit).filter(DockerUserQuotaLimit.uid == uid).first()
        return row.block_hard_limit if row else 0
    finally:
        db.close()


def set_user_quota_limit(uid: int, block_hard_limit: int) -> None:
    """Set Docker quota limit for uid (in 1K blocks)."""
    db = SessionLocal()
    try:
        row = db.query(DockerUserQuotaLimit).filter(DockerUserQuotaLimit.uid == uid).first()
        if row:
            row.block_hard_limit = block_hard_limit
        else:
            db.add(DockerUserQuotaLimit(uid=uid, block_hard_limit=block_hard_limit))
        db.commit()
        logger.info("Docker quota limit set uid=%s block_hard_limit=%s (1K blocks)", uid, block_hard_limit)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def batch_set_user_quota_limits(uid_limits: dict[int, int]) -> int:
    """Set Docker quota limits for multiple uids at once (in 1K blocks). Returns count of uids updated."""
    if not uid_limits:
        return 0
    db = SessionLocal()
    try:
        updated = 0
        for uid, block_hard_limit in uid_limits.items():
            row = db.query(DockerUserQuotaLimit).filter(DockerUserQuotaLimit.uid == uid).first()
            if row:
                row.block_hard_limit = block_hard_limit
            else:
                db.add(DockerUserQuotaLimit(uid=uid, block_hard_limit=block_hard_limit))
            updated += 1
        db.commit()
        logger.info("Docker quota limits batch set for %d uids", updated)
        return updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_all_user_quota_limits() -> dict[int, int]:
    """Return {uid: block_hard_limit} for all users with a Docker quota set."""
    db = SessionLocal()
    try:
        rows = db.query(DockerUserQuotaLimit).filter(DockerUserQuotaLimit.block_hard_limit > 0).all()
        return {r.uid: r.block_hard_limit for r in rows}
    finally:
        db.close()


def get_layer_attributions() -> list[dict[str, Any]]:
    """Return all layer attributions: layer_id -> first_puller_uid, size_bytes, etc."""
    db = SessionLocal()
    try:
        rows = db.query(DockerLayerAttribution).all()
        return [
            {
                "layer_id": r.layer_id,
                "first_puller_uid": r.first_puller_uid,
                "first_puller_host_user_name": r.first_puller_host_user_name,
                "size_bytes": r.size_bytes,
                "first_seen_at": r.first_seen_at,
                "creation_method": r.creation_method,
            }
            for r in rows
        ]
    finally:
        db.close()


def set_layer_attribution(
    layer_id: str,
    first_puller_host_user_name: str,
    first_puller_uid: int | None,
    size_bytes: int,
    creation_method: str | None = None,
) -> None:
    """Upsert one layer attribution. Only sets if layer_id doesn't exist (first creator wins)."""
    db = SessionLocal()
    try:
        row = db.query(DockerLayerAttribution).filter(DockerLayerAttribution.layer_id == layer_id).first()
        if row:
            # Layer already attributed, don't overwrite (first creator wins)
            return
        db.add(
            DockerLayerAttribution(
                layer_id=layer_id,
                first_puller_host_user_name=first_puller_host_user_name,
                first_puller_uid=first_puller_uid,
                size_bytes=size_bytes,
                creation_method=creation_method,
            )
        )
        db.commit()
        logger.debug("Attributed layer %s to uid=%s (method=%s)", layer_id[:12], first_puller_uid, creation_method)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_layers_for_image(image_id: str) -> list[str]:
    """Get layer IDs for an image (from Docker API). Returns list of layer IDs."""
    from app.docker_quota.docker_client import get_image_layers_with_sizes
    layers_with_sizes = get_image_layers_with_sizes(image_id)
    return [layer_id for layer_id, _size in layers_with_sizes]


def attribute_image_layers(
    image_id: str,
    creator_host_user_name: str,
    creator_uid: int | None,
    creation_method: str | None = None,
) -> int:
    """Extract layers from image and attribute NEW layers (not already attributed) to creator.
    Returns count of newly attributed layers.
    """
    from app.docker_quota.docker_client import get_image_layers_with_sizes
    layers_with_sizes = get_image_layers_with_sizes(image_id)
    existing_layers = {r["layer_id"] for r in get_layer_attributions()}
    new_count = 0
    for layer_id, size_bytes in layers_with_sizes:
        if layer_id not in existing_layers:
            set_layer_attribution(layer_id, creator_host_user_name, creator_uid, size_bytes, creation_method)
            new_count += 1
    return new_count


# --- Volume attribution ---


def get_volume_attributions() -> list[dict[str, Any]]:
    """Return all volume attributions: volume_name -> host_user_name, uid, size_bytes, etc."""
    db = SessionLocal()
    try:
        rows = db.query(DockerVolumeAttribution).all()
        return [
            {
                "volume_name": r.volume_name,
                "host_user_name": r.host_user_name,
                "uid": r.uid,
                "size_bytes": r.size_bytes,
                "attribution_source": r.attribution_source,
                "first_seen_at": r.first_seen_at,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_volume_attribution(volume_name: str) -> dict[str, Any] | None:
    """Return attribution for a specific volume, or None if not attributed."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeAttribution).filter(
            DockerVolumeAttribution.volume_name == volume_name
        ).first()
        if not row:
            return None
        return {
            "volume_name": row.volume_name,
            "host_user_name": row.host_user_name,
            "uid": row.uid,
            "size_bytes": row.size_bytes,
            "attribution_source": row.attribution_source,
            "first_seen_at": row.first_seen_at,
        }
    finally:
        db.close()


def set_volume_attribution(
    volume_name: str,
    host_user_name: str,
    uid: int | None,
    size_bytes: int = 0,
    attribution_source: str = "container",
) -> None:
    """Upsert volume attribution.
    
    Attribution sources:
    - 'label': from qman.user label on volume (takes priority, can change owner)
    - 'container': from first container that mounts the volume
    
    If source='label', always updates the attribution.
    If source='container' and attribution already exists, only updates size_bytes (preserves existing owner).
    """
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeAttribution).filter(
            DockerVolumeAttribution.volume_name == volume_name
        ).first()
        if row:
            # Label attribution takes priority and can change owner
            if attribution_source == "label":
                row.host_user_name = host_user_name
                row.uid = uid
                row.attribution_source = attribution_source
            # Container attribution preserves existing owner, only update size
            row.size_bytes = size_bytes
        else:
            db.add(
                DockerVolumeAttribution(
                    volume_name=volume_name,
                    host_user_name=host_user_name,
                    uid=uid,
                    size_bytes=size_bytes,
                    attribution_source=attribution_source,
                )
            )
        db.commit()
        logger.debug(
            "Volume attribution set: volume=%s, user=%s, uid=%s, size=%d, source=%s",
            volume_name, host_user_name, uid, size_bytes, attribution_source
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def update_volume_size(volume_name: str, size_bytes: int) -> bool:
    """Update only the size_bytes for an existing volume attribution.
    Returns True if updated, False if volume not found.
    """
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeAttribution).filter(
            DockerVolumeAttribution.volume_name == volume_name
        ).first()
        if not row:
            return False
        row.size_bytes = size_bytes
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_volume_attribution(volume_name: str) -> None:
    """Remove volume attribution (e.g. after volume removed via docker volume rm)."""
    db = SessionLocal()
    try:
        db.query(DockerVolumeAttribution).filter(
            DockerVolumeAttribution.volume_name == volume_name
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Volume disk usage (actual du scan results) ---


def get_volume_disk_usage_all() -> list[dict[str, Any]]:
    """Return all volume disk usage rows: volume_name -> actual_disk_bytes, scan_*, last_scan_*, pending_scan_started_at."""
    db = SessionLocal()
    try:
        rows = db.query(DockerVolumeDiskUsage).all()
        return [
            {
                "volume_name": r.volume_name,
                "actual_disk_bytes": r.actual_disk_bytes,
                "scan_started_at": r.scan_started_at,
                "scan_finished_at": r.scan_finished_at,
                "pending_scan_started_at": r.pending_scan_started_at,
                "last_scan_started_at": r.last_scan_started_at,
                "last_scan_finished_at": r.last_scan_finished_at,
                "last_scan_status": r.last_scan_status,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_volume_disk_usage(volume_name: str) -> dict[str, Any] | None:
    """Return disk usage row for one volume, or None."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeDiskUsage).filter(
            DockerVolumeDiskUsage.volume_name == volume_name
        ).first()
        if not row:
            return None
        return {
            "volume_name": row.volume_name,
            "actual_disk_bytes": row.actual_disk_bytes,
            "scan_started_at": row.scan_started_at,
            "scan_finished_at": row.scan_finished_at,
            "pending_scan_started_at": row.pending_scan_started_at,
            "last_scan_started_at": row.last_scan_started_at,
            "last_scan_finished_at": row.last_scan_finished_at,
            "last_scan_status": row.last_scan_status,
        }
    finally:
        db.close()


def set_volume_disk_usage_pending(volume_name: str, started_at: Any) -> None:
    """Set pending_scan_started_at and last_scan_started_at when starting a scan."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeDiskUsage).filter(
            DockerVolumeDiskUsage.volume_name == volume_name
        ).first()
        if row:
            row.pending_scan_started_at = started_at
            row.last_scan_started_at = started_at
        else:
            db.add(
                DockerVolumeDiskUsage(
                    volume_name=volume_name,
                    pending_scan_started_at=started_at,
                    last_scan_started_at=started_at,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_volume_disk_usage_success(
    volume_name: str,
    actual_disk_bytes: int,
    scan_started_at: Any,
    scan_finished_at: Any,
) -> None:
    """Set success tuple and last attempt on successful scan; clear pending."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeDiskUsage).filter(
            DockerVolumeDiskUsage.volume_name == volume_name
        ).first()
        if row:
            row.actual_disk_bytes = actual_disk_bytes
            row.scan_started_at = scan_started_at
            row.scan_finished_at = scan_finished_at
            row.pending_scan_started_at = None
            row.last_scan_started_at = scan_started_at
            row.last_scan_finished_at = scan_finished_at
            row.last_scan_status = "success"
        else:
            db.add(
                DockerVolumeDiskUsage(
                    volume_name=volume_name,
                    actual_disk_bytes=actual_disk_bytes,
                    scan_started_at=scan_started_at,
                    scan_finished_at=scan_finished_at,
                    last_scan_started_at=scan_started_at,
                    last_scan_finished_at=scan_finished_at,
                    last_scan_status="success",
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_volume_disk_usage_failure(
    volume_name: str,
    last_scan_finished_at: Any,
    last_scan_status: str,
) -> None:
    """Set last attempt on failed scan; clear pending. Do not modify success tuple."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeDiskUsage).filter(
            DockerVolumeDiskUsage.volume_name == volume_name
        ).first()
        if row:
            row.pending_scan_started_at = None
            row.last_scan_finished_at = last_scan_finished_at
            row.last_scan_status = last_scan_status
        else:
            db.add(
                DockerVolumeDiskUsage(
                    volume_name=volume_name,
                    last_scan_finished_at=last_scan_finished_at,
                    last_scan_status=last_scan_status,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_volume_disk_usage(volume_name: str) -> None:
    """Remove disk usage row (e.g. after volume removed)."""
    db = SessionLocal()
    try:
        db.query(DockerVolumeDiskUsage).filter(
            DockerVolumeDiskUsage.volume_name == volume_name
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reconcile_volume_disk_usage(volume_names_from_docker: set[str]) -> int:
    """Remove disk usage rows for volumes that no longer exist in Docker. Returns count removed."""
    db = SessionLocal()
    try:
        rows = db.query(DockerVolumeDiskUsage).all()
        removed = 0
        for r in rows:
            if r.volume_name not in volume_names_from_docker:
                db.query(DockerVolumeDiskUsage).filter(
                    DockerVolumeDiskUsage.volume_name == r.volume_name
                ).delete()
                removed += 1
        db.commit()
        return removed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Volume last mounted (for smart skip) ---


def get_volume_last_used_all() -> dict[str, Any]:
    """Return {volume_name: last_mounted_at} for all volumes with last_used record."""
    db = SessionLocal()
    try:
        rows = db.query(DockerVolumeLastUsed).all()
        return {r.volume_name: r.last_mounted_at for r in rows}
    finally:
        db.close()


def set_volume_last_mounted_at(volume_name: str, last_mounted_at: Any) -> None:
    """Set or update last_mounted_at for a volume (from container start event)."""
    db = SessionLocal()
    try:
        row = db.query(DockerVolumeLastUsed).filter(
            DockerVolumeLastUsed.volume_name == volume_name
        ).first()
        if row:
            row.last_mounted_at = last_mounted_at
        else:
            db.add(DockerVolumeLastUsed(volume_name=volume_name, last_mounted_at=last_mounted_at))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_volume_last_used(volume_name: str) -> None:
    """Remove last_used row (e.g. after volume removed)."""
    db = SessionLocal()
    try:
        db.query(DockerVolumeLastUsed).filter(
            DockerVolumeLastUsed.volume_name == volume_name
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reconcile_volume_last_used(volume_names_from_docker: set[str]) -> int:
    """Remove last_used rows for volumes that no longer exist in Docker. Returns count removed."""
    db = SessionLocal()
    try:
        rows = db.query(DockerVolumeLastUsed).all()
        removed = 0
        for r in rows:
            if r.volume_name not in volume_names_from_docker:
                db.query(DockerVolumeLastUsed).filter(
                    DockerVolumeLastUsed.volume_name == r.volume_name
                ).delete()
                removed += 1
        db.commit()
        return removed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- Manual attribution overrides (separate tables; higher priority) ---


def get_container_attribution_override(container_id: str) -> dict[str, Any] | None:
    """Return manual override for a container, or None if not set."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerContainerAttributionOverride)
            .filter(DockerContainerAttributionOverride.container_id == container_id)
            .first()
        )
        if not row:
            return None
        return {
            "container_id": row.container_id,
            "host_user_name": row.host_user_name,
            "uid": row.uid,
            "created_at": row.created_at,
            "resolved_by_oauth_user_id": row.resolved_by_oauth_user_id,
        }
    finally:
        db.close()


def set_container_attribution_override(
    container_id: str,
    host_user_name: str,
    uid: int | None,
    resolved_by_oauth_user_id: int | None,
    cascade: bool = False,
) -> None:
    """Upsert container manual attribution override.

    If cascade=True, also writes overrides for the container's image + its layers
    and for volumes mounted by this container.
    """
    db = SessionLocal()
    try:
        row = (
            db.query(DockerContainerAttributionOverride)
            .filter(DockerContainerAttributionOverride.container_id == container_id)
            .first()
        )
        if row:
            row.host_user_name = host_user_name
            row.uid = uid
            row.resolved_by_oauth_user_id = resolved_by_oauth_user_id
        else:
            db.add(
                DockerContainerAttributionOverride(
                    container_id=container_id,
                    host_user_name=host_user_name,
                    uid=uid,
                    resolved_by_oauth_user_id=resolved_by_oauth_user_id,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if not cascade:
        return

    # Resolve container -> (image_id, volume_names) from Docker.
    image_id = _resolve_image_id_from_docker_container(container_id)
    volume_names = _get_volume_names_for_container(container_id)

    if image_id:
        set_image_attribution_override(
            image_id=image_id,
            puller_host_user_name=host_user_name,
            puller_uid=uid,
            resolved_by_oauth_user_id=resolved_by_oauth_user_id,
            cascade=True,
        )

    for vol_name in volume_names:
        set_volume_attribution_override(
            volume_name=vol_name,
            host_user_name=host_user_name,
            uid=uid,
            resolved_by_oauth_user_id=resolved_by_oauth_user_id,
        )


def delete_container_attribution_override(
    container_id: str,
    cascade: bool = False,
) -> None:
    """Clear a container manual override (optionally cascade to image/layers/volumes)."""
    db = SessionLocal()
    try:
        db.query(DockerContainerAttributionOverride).filter(
            DockerContainerAttributionOverride.container_id == container_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if not cascade:
        return

    # Resolve container -> (image_id, volume_names) from Docker and clear related overrides.
    image_id = _resolve_image_id_from_docker_container(container_id)
    volume_names = _get_volume_names_for_container(container_id)

    if image_id:
        delete_image_attribution_override(image_id=image_id, cascade=True)
    for vol_name in volume_names:
        delete_volume_attribution_override(volume_name=vol_name)


def get_image_attribution_override(image_id: str) -> dict[str, Any] | None:
    """Return manual override for an image, or None if not set."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerImageAttributionOverride)
            .filter(DockerImageAttributionOverride.image_id == image_id)
            .first()
        )
        if not row:
            return None
        return {
            "image_id": row.image_id,
            "puller_host_user_name": row.puller_host_user_name,
            "puller_uid": row.puller_uid,
            "created_at": row.created_at,
            "resolved_by_oauth_user_id": row.resolved_by_oauth_user_id,
        }
    finally:
        db.close()


def set_image_attribution_override(
    image_id: str,
    puller_host_user_name: str,
    puller_uid: int | None,
    resolved_by_oauth_user_id: int | None,
    cascade: bool = False,
) -> None:
    """Upsert image manual attribution override (optionally cascade to all layers)."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerImageAttributionOverride)
            .filter(DockerImageAttributionOverride.image_id == image_id)
            .first()
        )
        if row:
            row.puller_host_user_name = puller_host_user_name
            row.puller_uid = puller_uid
            row.resolved_by_oauth_user_id = resolved_by_oauth_user_id
        else:
            db.add(
                DockerImageAttributionOverride(
                    image_id=image_id,
                    puller_host_user_name=puller_host_user_name,
                    puller_uid=puller_uid,
                    resolved_by_oauth_user_id=resolved_by_oauth_user_id,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if not cascade:
        return

    layer_ids = get_layers_for_image(image_id)
    for layer_id in layer_ids:
        set_layer_attribution_override(
            layer_id=layer_id,
            first_puller_host_user_name=puller_host_user_name,
            first_puller_uid=puller_uid,
            resolved_by_oauth_user_id=resolved_by_oauth_user_id,
        )


def delete_image_attribution_override(image_id: str, cascade: bool = False) -> None:
    """Clear an image manual override (optionally cascade to layer overrides)."""
    db = SessionLocal()
    try:
        db.query(DockerImageAttributionOverride).filter(
            DockerImageAttributionOverride.image_id == image_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if not cascade:
        return

    layer_ids = get_layers_for_image(image_id)
    for layer_id in layer_ids:
        delete_layer_attribution_override(layer_id=layer_id)


def get_layer_attribution_override(layer_id: str) -> dict[str, Any] | None:
    """Return manual override for a layer, or None if not set."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerLayerAttributionOverride)
            .filter(DockerLayerAttributionOverride.layer_id == layer_id)
            .first()
        )
        if not row:
            return None
        return {
            "layer_id": row.layer_id,
            "first_puller_host_user_name": row.first_puller_host_user_name,
            "first_puller_uid": row.first_puller_uid,
            "created_at": row.created_at,
            "resolved_by_oauth_user_id": row.resolved_by_oauth_user_id,
        }
    finally:
        db.close()


def set_layer_attribution_override(
    layer_id: str,
    first_puller_host_user_name: str,
    first_puller_uid: int | None,
    resolved_by_oauth_user_id: int | None,
) -> None:
    """Upsert a layer manual attribution override."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerLayerAttributionOverride)
            .filter(DockerLayerAttributionOverride.layer_id == layer_id)
            .first()
        )
        if row:
            row.first_puller_host_user_name = first_puller_host_user_name
            row.first_puller_uid = first_puller_uid
            row.resolved_by_oauth_user_id = resolved_by_oauth_user_id
        else:
            db.add(
                DockerLayerAttributionOverride(
                    layer_id=layer_id,
                    first_puller_host_user_name=first_puller_host_user_name,
                    first_puller_uid=first_puller_uid,
                    resolved_by_oauth_user_id=resolved_by_oauth_user_id,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_layer_attribution_override(layer_id: str) -> None:
    """Clear a layer manual override."""
    db = SessionLocal()
    try:
        db.query(DockerLayerAttributionOverride).filter(
            DockerLayerAttributionOverride.layer_id == layer_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_volume_attribution_override(volume_name: str) -> dict[str, Any] | None:
    """Return manual override for a volume, or None if not set."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerVolumeAttributionOverride)
            .filter(DockerVolumeAttributionOverride.volume_name == volume_name)
            .first()
        )
        if not row:
            return None
        return {
            "volume_name": row.volume_name,
            "host_user_name": row.host_user_name,
            "uid": row.uid,
            "created_at": row.created_at,
            "resolved_by_oauth_user_id": row.resolved_by_oauth_user_id,
        }
    finally:
        db.close()


def set_volume_attribution_override(
    volume_name: str,
    host_user_name: str,
    uid: int | None,
    resolved_by_oauth_user_id: int | None,
) -> None:
    """Upsert a volume manual attribution override."""
    db = SessionLocal()
    try:
        row = (
            db.query(DockerVolumeAttributionOverride)
            .filter(DockerVolumeAttributionOverride.volume_name == volume_name)
            .first()
        )
        if row:
            row.host_user_name = host_user_name
            row.uid = uid
            row.resolved_by_oauth_user_id = resolved_by_oauth_user_id
        else:
            db.add(
                DockerVolumeAttributionOverride(
                    volume_name=volume_name,
                    host_user_name=host_user_name,
                    uid=uid,
                    resolved_by_oauth_user_id=resolved_by_oauth_user_id,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_volume_attribution_override(volume_name: str) -> None:
    """Clear a volume manual override."""
    db = SessionLocal()
    try:
        db.query(DockerVolumeAttributionOverride).filter(
            DockerVolumeAttributionOverride.volume_name == volume_name
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _resolve_image_id_from_docker_container(container_id: str) -> str | None:
    """Resolve a container's image to full image ID (sha256:...)."""
    try:
        import docker

        client = docker.from_env()
        try:
            container = client.containers.get(container_id)
            attrs = container.attrs or {}
            config = attrs.get("Config") or {}
            image_ref = config.get("Image") or attrs.get("Image")
            if not image_ref:
                return None
            if isinstance(image_ref, str) and image_ref.startswith("sha256:"):
                return image_ref
            try:
                img = client.images.get(image_ref)
                return img.id
            except Exception:
                return None
        finally:
            client.close()
    except Exception:
        return None


def _get_volume_names_for_container(container_id: str) -> list[str]:
    """Return list of Docker volume names mounted by a given container."""
    try:
        import docker

        client = docker.from_env()
        try:
            container = client.containers.get(container_id)
            attrs = container.attrs or {}
            mounts = attrs.get("Mounts") or []
            out: list[str] = []
            for mount in mounts:
                if mount.get("Type") != "volume":
                    continue
                name = mount.get("Name")
                if name:
                    out.append(name)
            return out
        finally:
            client.close()
    except Exception:
        return []


def _json_dt(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def get_container_attribution_breakdown(container_id: str) -> dict[str, Any]:
    """Return auto vs manual override rows for API JSON (ISO datetimes)."""
    db = SessionLocal()
    try:
        auto: dict[str, Any] | None = None
        row = (
            db.query(DockerContainerAttribution)
            .filter(DockerContainerAttribution.container_id == container_id)
            .first()
        )
        if row:
            auto = {
                "container_id": row.container_id,
                "host_user_name": row.host_user_name,
                "uid": row.uid,
                "image_id": row.image_id,
                "size_bytes": row.size_bytes,
                "created_at": _json_dt(row.created_at),
            }
        override: dict[str, Any] | None = None
        orow = (
            db.query(DockerContainerAttributionOverride)
            .filter(DockerContainerAttributionOverride.container_id == container_id)
            .first()
        )
        if orow:
            override = {
                "container_id": orow.container_id,
                "host_user_name": orow.host_user_name,
                "uid": orow.uid,
                "created_at": _json_dt(orow.created_at),
                "resolved_by_oauth_user_id": orow.resolved_by_oauth_user_id,
            }
        return {"auto": auto, "override": override}
    finally:
        db.close()


def get_image_attribution_breakdown(image_id: str) -> dict[str, Any]:
    """Return auto vs manual override rows for an image (ISO datetimes)."""
    db = SessionLocal()
    try:
        auto: dict[str, Any] | None = None
        row = db.query(DockerImageAttribution).filter(DockerImageAttribution.image_id == image_id).first()
        if row:
            auto = {
                "image_id": row.image_id,
                "puller_host_user_name": row.puller_host_user_name,
                "puller_uid": row.puller_uid,
                "size_bytes": row.size_bytes,
                "created_at": _json_dt(row.created_at),
            }
        override: dict[str, Any] | None = None
        orow = (
            db.query(DockerImageAttributionOverride)
            .filter(DockerImageAttributionOverride.image_id == image_id)
            .first()
        )
        if orow:
            override = {
                "image_id": orow.image_id,
                "puller_host_user_name": orow.puller_host_user_name,
                "puller_uid": orow.puller_uid,
                "created_at": _json_dt(orow.created_at),
                "resolved_by_oauth_user_id": orow.resolved_by_oauth_user_id,
            }
        return {"auto": auto, "override": override}
    finally:
        db.close()


def get_volume_attribution_breakdown(volume_name: str) -> dict[str, Any]:
    """Return auto vs manual override rows for a volume (ISO datetimes)."""
    db = SessionLocal()
    try:
        auto: dict[str, Any] | None = None
        row = (
            db.query(DockerVolumeAttribution)
            .filter(DockerVolumeAttribution.volume_name == volume_name)
            .first()
        )
        if row:
            auto = {
                "volume_name": row.volume_name,
                "host_user_name": row.host_user_name,
                "uid": row.uid,
                "size_bytes": row.size_bytes,
                "attribution_source": row.attribution_source,
                "first_seen_at": _json_dt(row.first_seen_at),
            }
        override: dict[str, Any] | None = None
        orow = (
            db.query(DockerVolumeAttributionOverride)
            .filter(DockerVolumeAttributionOverride.volume_name == volume_name)
            .first()
        )
        if orow:
            override = {
                "volume_name": orow.volume_name,
                "host_user_name": orow.host_user_name,
                "uid": orow.uid,
                "created_at": _json_dt(orow.created_at),
                "resolved_by_oauth_user_id": orow.resolved_by_oauth_user_id,
            }
        return {"auto": auto, "override": override}
    finally:
        db.close()


# --- Effective attribution (manual overrides win) ---


def get_container_effective_attributions() -> list[dict[str, Any]]:
    """Return effective container ownership, using manual overrides when present."""
    db = SessionLocal()
    try:
        auto_rows = db.query(DockerContainerAttribution).all()
        override_rows = db.query(DockerContainerAttributionOverride).all()
        overrides = {r.container_id: r for r in override_rows}
        auto_ids = {r.container_id for r in auto_rows}

        out: list[dict[str, Any]] = []
        for r in auto_rows:
            o = overrides.get(r.container_id)
            if o:
                out.append(
                    {
                        "container_id": r.container_id,
                        "host_user_name": o.host_user_name,
                        "uid": o.uid,
                        "image_id": r.image_id,
                        "size_bytes": r.size_bytes,
                        "created_at": o.created_at,
                    }
                )
            else:
                out.append(
                    {
                        "container_id": r.container_id,
                        "host_user_name": r.host_user_name,
                        "uid": r.uid,
                        "image_id": r.image_id,
                        "size_bytes": r.size_bytes,
                        "created_at": r.created_at,
                    }
                )

        for o in override_rows:
            if o.container_id in auto_ids:
                continue
            out.append(
                {
                    "container_id": o.container_id,
                    "host_user_name": o.host_user_name,
                    "uid": o.uid,
                    "image_id": None,
                    "size_bytes": 0,
                    "created_at": o.created_at,
                }
            )

        return out
    finally:
        db.close()


def get_image_effective_attributions() -> list[dict[str, Any]]:
    """Return effective image ownership, using manual overrides when present."""
    db = SessionLocal()
    try:
        auto_rows = db.query(DockerImageAttribution).all()
        override_rows = db.query(DockerImageAttributionOverride).all()
        overrides = {r.image_id: r for r in override_rows}
        auto_ids = {r.image_id for r in auto_rows}

        out: list[dict[str, Any]] = []
        for r in auto_rows:
            o = overrides.get(r.image_id)
            if o:
                out.append(
                    {
                        "image_id": r.image_id,
                        "puller_host_user_name": o.puller_host_user_name,
                        "puller_uid": o.puller_uid,
                        "size_bytes": r.size_bytes,
                        "created_at": o.created_at,
                    }
                )
            else:
                out.append(
                    {
                        "image_id": r.image_id,
                        "puller_host_user_name": r.puller_host_user_name,
                        "puller_uid": r.puller_uid,
                        "size_bytes": r.size_bytes,
                        "created_at": r.created_at,
                    }
                )

        for o in override_rows:
            if o.image_id in auto_ids:
                continue
            out.append(
                {
                    "image_id": o.image_id,
                    "puller_host_user_name": o.puller_host_user_name,
                    "puller_uid": o.puller_uid,
                    "size_bytes": 0,
                    "created_at": o.created_at,
                }
            )
        return out
    finally:
        db.close()


def get_layer_effective_attributions() -> list[dict[str, Any]]:
    """Return effective layer ownership, using manual overrides when present."""
    db = SessionLocal()
    try:
        auto_rows = db.query(DockerLayerAttribution).all()
        override_rows = db.query(DockerLayerAttributionOverride).all()
        overrides = {r.layer_id: r for r in override_rows}

        auto_map = {r.layer_id: r for r in auto_rows}
        out: list[dict[str, Any]] = []
        seen_layer_ids: set[str] = set()

        for layer_id, a in auto_map.items():
            o = overrides.get(layer_id)
            if o:
                out.append(
                    {
                        "layer_id": layer_id,
                        "first_puller_uid": o.first_puller_uid,
                        "first_puller_host_user_name": o.first_puller_host_user_name,
                        "size_bytes": a.size_bytes,
                        "first_seen_at": o.created_at,
                        "creation_method": a.creation_method,
                    }
                )
            else:
                out.append(
                    {
                        "layer_id": layer_id,
                        "first_puller_uid": a.first_puller_uid,
                        "first_puller_host_user_name": a.first_puller_host_user_name,
                        "size_bytes": a.size_bytes,
                        "first_seen_at": a.first_seen_at,
                        "creation_method": a.creation_method,
                    }
                )
            seen_layer_ids.add(layer_id)

        # Override-only layers (no auto record): ownership known, size_bytes unknown.
        for layer_id, o in overrides.items():
            if layer_id in seen_layer_ids:
                continue
            out.append(
                {
                    "layer_id": layer_id,
                    "first_puller_uid": o.first_puller_uid,
                    "first_puller_host_user_name": o.first_puller_host_user_name,
                    "size_bytes": 0,
                    "first_seen_at": o.created_at,
                    "creation_method": None,
                }
            )
        return out
    finally:
        db.close()


def get_volume_effective_attributions() -> list[dict[str, Any]]:
    """Return effective volume ownership, using manual overrides when present."""
    db = SessionLocal()
    try:
        auto_rows = db.query(DockerVolumeAttribution).all()
        override_rows = db.query(DockerVolumeAttributionOverride).all()
        overrides = {r.volume_name: r for r in override_rows}
        auto_ids = {r.volume_name for r in auto_rows}

        out: list[dict[str, Any]] = []
        for r in auto_rows:
            o = overrides.get(r.volume_name)
            if o:
                out.append(
                    {
                        "volume_name": r.volume_name,
                        "host_user_name": o.host_user_name,
                        "uid": o.uid,
                        "size_bytes": r.size_bytes,
                        "attribution_source": "manual_override",
                        "first_seen_at": o.created_at,
                    }
                )
            else:
                out.append(
                    {
                        "volume_name": r.volume_name,
                        "host_user_name": r.host_user_name,
                        "uid": r.uid,
                        "size_bytes": r.size_bytes,
                        "attribution_source": r.attribution_source,
                        "first_seen_at": r.first_seen_at,
                    }
                )

        for o in override_rows:
            if o.volume_name in auto_ids:
                continue
            out.append(
                {
                    "volume_name": o.volume_name,
                    "host_user_name": o.host_user_name,
                    "uid": o.uid,
                    "size_bytes": 0,
                    "attribution_source": "manual_override",
                    "first_seen_at": o.created_at,
                }
            )

        return out
    finally:
        db.close()
