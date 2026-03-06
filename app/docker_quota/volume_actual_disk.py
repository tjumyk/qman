"""Collect actual on-disk usage of Docker volumes via du -sB1 (low I/O priority, disk-wise parallelism)."""

import os
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app.docker_quota.attribution_store import (
    get_volume_disk_usage_all,
    get_volume_last_used_all,
    set_volume_disk_usage_failure,
    set_volume_disk_usage_pending,
    set_volume_disk_usage_success,
)
from app.docker_quota.docker_client import get_system_df
from app.utils import get_logger

logger = get_logger(__name__)

_DEFAULT_TIMEOUT_PER_VOLUME = 3600  # 1 hour
_MAX_CONCURRENT_PER_DISK = 1


def _get_volumes_with_mountpoints() -> dict[str, str]:
    """Return {volume_name: mountpoint} for all Docker volumes. Mountpoint from volume attrs."""
    try:
        import docker
        client = docker.from_env()
        try:
            volumes = client.volumes.list()
            result: dict[str, str] = {}
            for vol in volumes:
                mountpoint = (vol.attrs or {}).get("Mountpoint")
                if mountpoint and isinstance(mountpoint, str) and vol.name:
                    result[vol.name] = mountpoint
            return result
        finally:
            client.close()
    except Exception as e:
        logger.warning("Failed to list Docker volumes: %s", e)
        return {}


def _device_for_path(path: str) -> int | None:
    """Return device id (st_dev) for path, or None if not available."""
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def _run_du_bytes(path: str, timeout_seconds: int) -> tuple[int | None, str | None]:
    """Run du -sB1 on path with optional ionice/nice. Returns (bytes, None) on success, (None, status) on failure.
    status is one of 'timeout', 'permission_denied', 'parse_failure'.
    """
    # Use block size 1 to get actual disk usage in bytes (allocated blocks), not apparent size.
    base_cmd = ["du", "-sB1", path]
    if sys.platform == "linux":
        full_cmd = ["ionice", "-c3", "nice", "-n19"] + base_cmd
    else:
        full_cmd = base_cmd
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            timeout=timeout_seconds,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except PermissionError:
        return None, "permission_denied"
    except OSError as e:
        logger.debug("du failed for %s: %s", path, e)
        return None, "permission_denied"
    if result.returncode != 0:
        return None, "permission_denied"
    line = (result.stdout or "").strip().split("\n")[-1]
    parts = line.split()
    if not parts:
        return None, "parse_failure"
    try:
        return int(parts[0]), None
    except ValueError:
        return None, "parse_failure"


def _load_config() -> dict[str, Any]:
    """Load config from CONFIG_PATH (JSON). Returns dict with timeout and max_concurrent_per_disk."""
    config_path = os.environ.get("CONFIG_PATH", "config.json")
    out = {
        "timeout_per_volume": _DEFAULT_TIMEOUT_PER_VOLUME,
        "max_concurrent_per_disk": _MAX_CONCURRENT_PER_DISK,
    }
    if config_path and os.path.isfile(config_path):
        try:
            import json
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("DOCKER_VOLUME_ACTUAL_DISK_TIMEOUT_PER_VOLUME_SECONDS") is not None:
                out["timeout_per_volume"] = int(data["DOCKER_VOLUME_ACTUAL_DISK_TIMEOUT_PER_VOLUME_SECONDS"])
            if data.get("DOCKER_VOLUME_ACTUAL_DISK_MAX_CONCURRENT_PER_DISK") is not None:
                out["max_concurrent_per_disk"] = int(data["DOCKER_VOLUME_ACTUAL_DISK_MAX_CONCURRENT_PER_DISK"])
        except Exception as e:
            logger.debug("Could not load config from %s: %s", config_path, e)
    return out


def collect_volume_actual_disk() -> dict[str, int]:
    """Scan all Docker volumes for actual disk usage (du -sb). Apply smart skip; disk-wise parallelism.
    Returns counts: scanned, success, timeout, permission_denied, parse_failure, skipped.
    """
    start_time = time.time()
    config = _load_config()
    timeout_per_volume = config["timeout_per_volume"]
    max_concurrent_per_disk = config["max_concurrent_per_disk"]

    name_to_mountpoint = _get_volumes_with_mountpoints()
    if not name_to_mountpoint:
        logger.info("collect_volume_actual_disk: no volumes with mountpoints")
        return {"scanned": 0, "success": 0, "timeout": 0, "permission_denied": 0, "parse_failure": 0, "skipped": 0}

    df = get_system_df(include_volumes=True)
    volume_data = df.get("volumes") or {}
    ref_count_by_name = {name: (vol.get("ref_count", 0) or 0) for name, vol in volume_data.items()}

    disk_usage_all = get_volume_disk_usage_all()
    disk_usage_by_name = {u["volume_name"]: u for u in disk_usage_all}
    last_used_all = get_volume_last_used_all()

    def should_skip(vol_name: str) -> bool:
        """Skip iff: has scan AND RefCount==0 AND last_mounted_at set AND last_mounted_at <= scan_finished_at."""
        disk_usage = disk_usage_by_name.get(vol_name)
        if not disk_usage or disk_usage.get("actual_disk_bytes") is None or disk_usage.get("scan_finished_at") is None:
            return False
        if ref_count_by_name.get(vol_name, 0) != 0:
            return False
        last_mounted = last_used_all.get(vol_name)
        if last_mounted is None:
            return False
        scan_finished = disk_usage.get("scan_finished_at")
        if scan_finished is None:
            return False
        # Compare timestamps (last_mounted_at <= scan_finished_at)
        if hasattr(last_mounted, "timestamp"):
            lm_ts = last_mounted.timestamp()
        else:
            lm_ts = last_mounted
        if hasattr(scan_finished, "timestamp"):
            sf_ts = scan_finished.timestamp()
        else:
            sf_ts = scan_finished
        return lm_ts <= sf_ts

    to_scan: list[tuple[str, str]] = []
    skipped = 0
    for vol_name, mountpoint in name_to_mountpoint.items():
        if should_skip(vol_name):
            skipped += 1
            continue
        to_scan.append((vol_name, mountpoint))

    # Group by device for disk-wise parallelism
    device_to_volumes: dict[int | str, list[tuple[str, str]]] = defaultdict(list)
    for vol_name, mountpoint in to_scan:
        dev = _device_for_path(mountpoint)
        key: int | str = dev if dev is not None else f"unknown_{vol_name}"
        device_to_volumes[key].append((vol_name, mountpoint))

    counts = {"scanned": 0, "success": 0, "timeout": 0, "permission_denied": 0, "parse_failure": 0, "skipped": skipped}

    def scan_volume(vol_name: str, mountpoint: str) -> tuple[str, str | None]:
        """Run du for one volume; return (vol_name, failure_status or None)."""
        now_start = datetime.now(timezone.utc)
        set_volume_disk_usage_pending(vol_name, now_start)
        bytes_val, failure_status = _run_du_bytes(mountpoint, timeout_per_volume)
        now_finish = datetime.now(timezone.utc)
        if failure_status:
            set_volume_disk_usage_failure(vol_name, now_finish, failure_status)
            return vol_name, failure_status
        set_volume_disk_usage_success(vol_name, bytes_val or 0, now_start, now_finish)
        return vol_name, None

    def run_device_volumes(vol_list: list[tuple[str, str]]) -> list[tuple[str, str | None]]:
        """Run scan for each volume on one device; up to max_concurrent_per_disk concurrent scans per device."""
        if max_concurrent_per_disk <= 1 or len(vol_list) <= 1:
            return [scan_volume(vol_name, mountpoint) for vol_name, mountpoint in vol_list]
        results: list[tuple[str, str | None]] = []
        workers = min(max_concurrent_per_disk, len(vol_list))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(scan_volume, vol_name, mountpoint): vol_name
                for vol_name, mountpoint in vol_list
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    vol_name = futures[future]
                    logger.warning("Volume %s scan failed: %s", vol_name, e)
                    results.append((vol_name, "parse_failure"))
        return results

    # Disk-wise parallelism: one task per device, each task runs up to max_concurrent_per_disk scans on that device
    max_workers = min(len(device_to_volumes), 32)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_device_volumes, vol_list): dev_key
            for dev_key, vol_list in device_to_volumes.items()
        }
        for future in as_completed(futures):
            try:
                results = future.result()
                for _vol_name, failure_status in results:
                    counts["scanned"] += 1
                    if failure_status:
                        counts[failure_status] = counts.get(failure_status, 0) + 1
                    else:
                        counts["success"] += 1
            except Exception as e:
                logger.warning("Device scan task failed: %s", e)

    elapsed = time.time() - start_time
    logger.info(
        "collect_volume_actual_disk: total=%.2fs scanned=%d success=%d timeout=%d permission_denied=%d parse_failure=%d skipped=%d",
        elapsed, counts["scanned"], counts["success"], counts["timeout"],
        counts["permission_denied"], counts["parse_failure"], counts["skipped"]
    )
    return counts
