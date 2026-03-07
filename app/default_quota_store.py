"""Persistence for per-device default user quota (slave; used by all disk types)."""

from typing import Any

from app.db import SessionLocal
from app.models_db import DeviceDefaultQuota
from app.utils import get_logger

logger = get_logger(__name__)


def get_device_default_quota(device_name: str) -> dict[str, Any] | None:
    """Return default quota for device, or None if not set."""
    db = SessionLocal()
    try:
        row = db.query(DeviceDefaultQuota).filter(DeviceDefaultQuota.device_name == device_name).first()
        if row is None:
            return None
        return {
            "device_name": row.device_name,
            "block_soft_limit": row.block_soft_limit,
            "block_hard_limit": row.block_hard_limit,
            "inode_soft_limit": row.inode_soft_limit,
            "inode_hard_limit": row.inode_hard_limit,
        }
    finally:
        db.close()


def set_device_default_quota(
    device_name: str,
    block_soft_limit: int = 0,
    block_hard_limit: int = 0,
    inode_soft_limit: int = 0,
    inode_hard_limit: int = 0,
) -> dict[str, Any]:
    """Set default quota for device. Returns the saved row as dict."""
    db = SessionLocal()
    try:
        row = db.query(DeviceDefaultQuota).filter(DeviceDefaultQuota.device_name == device_name).first()
        if row:
            row.block_soft_limit = block_soft_limit
            row.block_hard_limit = block_hard_limit
            row.inode_soft_limit = inode_soft_limit
            row.inode_hard_limit = inode_hard_limit
        else:
            db.add(
                DeviceDefaultQuota(
                    device_name=device_name,
                    block_soft_limit=block_soft_limit,
                    block_hard_limit=block_hard_limit,
                    inode_soft_limit=inode_soft_limit,
                    inode_hard_limit=inode_hard_limit,
                )
            )
        db.commit()
        out_row = db.query(DeviceDefaultQuota).filter(DeviceDefaultQuota.device_name == device_name).first()
        if out_row is None:
            raise RuntimeError("device_default_quota row missing after commit")
        logger.info(
            "Device default quota set device=%s block_soft=%s block_hard=%s inode_soft=%s inode_hard=%s",
            device_name,
            block_soft_limit,
            block_hard_limit,
            inode_soft_limit,
            inode_hard_limit,
        )
        return {
            "device_name": out_row.device_name,
            "block_soft_limit": out_row.block_soft_limit,
            "block_hard_limit": out_row.block_hard_limit,
            "inode_soft_limit": out_row.inode_soft_limit,
            "inode_hard_limit": out_row.inode_hard_limit,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_devices_with_nonempty_default() -> list[dict[str, Any]]:
    """Return list of devices that have at least one non-zero default limit."""
    db = SessionLocal()
    try:
        rows = (
            db.query(DeviceDefaultQuota)
            .filter(
                (DeviceDefaultQuota.block_soft_limit > 0)
                | (DeviceDefaultQuota.block_hard_limit > 0)
                | (DeviceDefaultQuota.inode_soft_limit > 0)
                | (DeviceDefaultQuota.inode_hard_limit > 0)
            )
            .all()
        )
        return [
            {
                "device_name": r.device_name,
                "block_soft_limit": r.block_soft_limit,
                "block_hard_limit": r.block_hard_limit,
                "inode_soft_limit": r.inode_soft_limit,
                "inode_hard_limit": r.inode_hard_limit,
            }
            for r in rows
        ]
    finally:
        db.close()
