"""Persistence for Docker container/image attribution and per-user quota limits (slave)."""

from typing import Any

from app.db import SessionLocal
from app.models_db import (
    DockerContainerAttribution,
    DockerImageAttribution,
    DockerLayerAttribution,
    DockerUserQuotaLimit,
    DockerVolumeAttribution,
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
