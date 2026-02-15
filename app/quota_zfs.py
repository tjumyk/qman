"""ZFS quota logic via zfs CLI. Used alongside pyquota when USE_ZFS is true (mixed backends)."""

import subprocess
from typing import Any

import pwd

_ZFS_CMD = "zfs"


class ZFSQuotaError(Exception):
    """Raised when a zfs command fails."""

    pass


def _zfs_list_datasets() -> list[str]:
    """Discover mounted ZFS filesystem datasets (name,mountpoint,used,avail). Returns list of dataset names."""
    result = subprocess.run(
        [
            _ZFS_CMD,
            "list",
            "-t", "filesystem",
            "-H", "-p",
            "-o", "name,mountpoint,used,avail",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    lines = result.stdout.strip().splitlines()
    datasets: list[str] = []
    for line in lines:
        parts = line.split("\t", 3)
        if len(parts) < 4:
            continue
        name, mountpoint, used_s, avail_s = parts
        if not mountpoint or mountpoint == "-":
            continue
        try:
            used = int(used_s)
            avail = int(avail_s)
        except ValueError:
            continue
        if used < 0 or avail < 0:
            continue
        datasets.append(name)
    return datasets


def get_devices(zfs_datasets: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Return dict keyed by dataset name. Same shape as quota.get_devices() for ZFS datasets."""
    if zfs_datasets is None:
        zfs_datasets = _zfs_list_datasets()
    devices: dict[str, dict[str, Any]] = {}
    for name in zfs_datasets:
        result = subprocess.run(
            [
                _ZFS_CMD,
                "list",
                "-H", "-p",
                "-o", "name,mountpoint,used,avail",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            continue
        parts = result.stdout.strip().split("\t", 3)
        if len(parts) < 4:
            continue
        _, mountpoint, used_s, avail_s = parts
        mountpoint = mountpoint if mountpoint and mountpoint != "-" else ""
        try:
            used = int(used_s)
            avail = int(avail_s)
        except ValueError:
            continue
        total = used + avail
        percent = (used / total * 100.0) if total else 0.0
        devices[name] = {
            "name": name,
            "mount_points": [mountpoint] if mountpoint else [],
            "fstype": "zfs",
            "opts": ["zfs"],
            "usage": {
                "used": used,
                "total": total,
                "free": avail,
                "percent": round(percent, 1),
            },
        }
    return devices


def _parse_userspace_output(stdout: str) -> list[tuple[int, int, int]]:
    """Parse 'zfs userspace -H -n -p -o type,name,used,quota'. Returns [(uid, used_bytes, quota_bytes), ...]."""
    rows: list[tuple[int, int, int]] = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        # type, name (numeric uid), used, quota
        try:
            uid = int(parts[1])
            used = int(parts[2])
            quota_s = parts[3].strip()
            quota = 0 if quota_s in ("-", "") else int(quota_s)
        except (ValueError, IndexError):
            continue
        rows.append((uid, used, quota))
    return rows


def _user_quota_dict(uid: int, used_bytes: int, quota_bytes: int) -> dict[str, Any]:
    """Build UserQuota-shaped dict. Limits in 1K blocks, block_current in bytes; inode/time = 0."""
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = f"user_{uid}"
    block_hard = quota_bytes // 1024 if quota_bytes else 0
    return {
        "uid": uid,
        "name": name,
        "block_hard_limit": block_hard,
        "block_soft_limit": block_hard,  # ZFS has single limit
        "block_current": used_bytes,
        "inode_hard_limit": 0,
        "inode_soft_limit": 0,
        "inode_current": 0,
        "block_time_limit": 0,
        "inode_time_limit": 0,
    }


def collect_remote_quotas(zfs_datasets: list[str] | None = None) -> list[dict[str, Any]]:
    """Build list of ZFS datasets with user quotas (same shape as quota.collect_remote_quotas)."""
    devices = get_devices(zfs_datasets)
    results: list[dict[str, Any]] = []
    for name, device in devices.items():
        result = subprocess.run(
            [
                _ZFS_CMD,
                "userspace",
                "-H", "-n", "-p",
                "-o", "type,name,used,quota",
                "-t", "posixuser",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            continue
        rows = _parse_userspace_output(result.stdout)
        if not rows:
            continue
        user_quotas = [_user_quota_dict(uid, used, quota) for uid, used, quota in rows]
        device_copy: dict[str, Any] = {
            "name": device["name"],
            "mount_points": list(device["mount_points"]),
            "fstype": device["fstype"],
            "opts": list(device["opts"]),
            "usage": dict(device["usage"]),
            "user_quota_format": "zfs",
            "user_quotas": user_quotas,
        }
        results.append(device_copy)
    results.sort(key=lambda r: r["name"])
    return results


def collect_remote_quotas_for_uid(uid: int, zfs_datasets: list[str] | None = None) -> list[dict[str, Any]]:
    """Build list of ZFS datasets where this user has usage or quota (same shape as quota.collect_remote_quotas_for_uid)."""
    devices = get_devices(zfs_datasets)
    results: list[dict[str, Any]] = []
    try:
        user_name = pwd.getpwuid(uid).pw_name
    except KeyError:
        user_name = f"user_{uid}"
    for name, device in devices.items():
        result = subprocess.run(
            [
                _ZFS_CMD,
                "userspace",
                "-H", "-n", "-p",
                "-o", "type,name,used,quota",
                "-t", "posixuser",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            continue
        rows = _parse_userspace_output(result.stdout)
        for row_uid, used, quota in rows:
            if row_uid != uid:
                continue
            quota_dict = _user_quota_dict(uid, used, quota)
            device_copy: dict[str, Any] = {
                "name": device["name"],
                "mount_points": list(device["mount_points"]),
                "fstype": device["fstype"],
                "opts": list(device["opts"]),
                "usage": dict(device["usage"]),
                "user_quota_format": "zfs",
                "user_quotas": [quota_dict],
            }
            results.append(device_copy)
            break
    results.sort(key=lambda r: r["name"])
    return results


def set_user_quota(
    dataset: str,
    uid: int,
    block_hard_limit: int,
    block_soft_limit: int,
    inode_hard_limit: int | None,
    inode_soft_limit: int | None,
) -> dict[str, Any]:
    """Set userquota@uid on dataset (bytes = block_hard_limit * 1024). Returns updated quota dict."""
    del block_soft_limit, inode_hard_limit, inode_soft_limit  # ZFS has single space limit
    quota_bytes = block_hard_limit * 1024
    result = subprocess.run(
        [
            _ZFS_CMD,
            "set",
            f"userquota@{uid}={quota_bytes}",
            dataset,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ZFSQuotaError(result.stderr or result.stdout or "zfs set userquota failed")
    # Read back used/quota (one row per property)
    get_result = subprocess.run(
        [
            _ZFS_CMD,
            "get",
            "-H", "-p",
            "-o", "value",
            f"userused@{uid},userquota@{uid}",
            dataset,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    used_bytes = 0
    quota_bytes_read = quota_bytes
    if get_result.returncode == 0 and get_result.stdout.strip():
        lines = get_result.stdout.strip().splitlines()
        if len(lines) >= 1:
            try:
                used_bytes = int(lines[0].strip())
            except ValueError:
                pass
        if len(lines) >= 2:
            qs = lines[1].strip()
            if qs not in ("-", ""):
                try:
                    quota_bytes_read = int(qs)
                except ValueError:
                    pass
    return _user_quota_dict(uid, used_bytes, quota_bytes_read)
