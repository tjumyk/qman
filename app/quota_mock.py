"""Mock quota backend: in-memory host with filesystems and quotas, no pyquota."""

from __future__ import annotations

from typing import Any

# In-memory mock host state. Initialized by init_mock_host().
_mock_state: dict[str, Any] = {
    "devices": {},
    "users": {},
    "groups": {},
}

# Quota 8-tuple: (bhard, bsoft, bcurrent, ihard, isoft, icurrent, btime, itime)
# Block limits (bhard, bsoft) are in 1K blocks; bcurrent is in bytes (pyquota convention).
_DEFAULT_QUOTA = (0, 0, 0, 0, 0, 0, 0, 0)


def _quota_dict_to_tuple(d: dict[str, Any]) -> tuple[int, int, int, int, int, int, int, int]:
    """Convert our stored quota dict to pyquota-style 8-tuple."""
    return (
        d.get("block_hard_limit", 0),
        d.get("block_soft_limit", 0),
        d.get("block_current", 0),
        d.get("inode_hard_limit", 0),
        d.get("inode_soft_limit", 0),
        d.get("inode_current", 0),
        d.get("block_time_limit", 0),
        d.get("inode_time_limit", 0),
    )


def init_mock_host() -> None:
    """Initialize the mocked host with multiple filesystems, users, and quota settings."""
    users = {
        1000: "alice",
        1001: "bob",
        1002: "charlie",
        1003: "diana",
        1004: "eve",
    }
    groups = {
        1000: "users",
        1001: "developers",
        1002: "admins",
    }

    devices = {
        "/dev/sda1": {
            "name": "/dev/sda1",
            "mount_points": ["/home"],
            "fstype": "ext4",
            "opts": ["rw", "usrquota", "grpquota"],
            # total 100 GiB, used 50 GiB; ~5% root reserve → user-addressable free 45 GiB
            "usage": {"free": 45 * 1024**3, "total": 100 * 1024**3, "used": 50 * 1024**3, "percent": 50.0},
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 7 * 86400, "inode_grace": 7 * 86400, "flags": 0},
            "group_quota_format": "vfsv1",
            "group_quota_info": {"block_grace": 7 * 86400, "inode_grace": 7 * 86400, "flags": 0},
            "user_quotas": {
                1000: {
                    "block_hard_limit": 1_000_000,
                    "block_soft_limit": 900_000,
                    "block_current": 300_000 * 1024,  # bytes (~293 MiB)
                    "inode_hard_limit": 100_000,
                    "inode_soft_limit": 80_000,
                    "inode_current": 25_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 2_000_000,
                    "block_soft_limit": 1_800_000,
                    "block_current": 1_200_000 * 1024,  # bytes (~1.14 GiB)
                    "inode_hard_limit": 200_000,
                    "inode_soft_limit": 150_000,
                    "inode_current": 90_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1002: {
                    "block_hard_limit": 500_000,
                    "block_soft_limit": 400_000,
                    "block_current": 450_000_000,  # bytes, over soft (400_000 * 1024)
                    "inode_hard_limit": 50_000,
                    "inode_soft_limit": 40_000,
                    "inode_current": 35_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1003: {
                    "block_hard_limit": 0,
                    "block_soft_limit": 0,
                    "block_current": 10_000,  # bytes
                    "inode_hard_limit": 0,
                    "inode_soft_limit": 0,
                    "inode_current": 1_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1004: {
                    "block_hard_limit": 5_000_000,
                    "block_soft_limit": 4_000_000,
                    "block_current": 2_000_000 * 1024,  # bytes (~1.9 GiB)
                    "inode_hard_limit": 500_000,
                    "inode_soft_limit": 400_000,
                    "inode_current": 100_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {
                1000: {
                    "block_hard_limit": 10_000_000,
                    "block_soft_limit": 8_000_000,
                    "block_current": 3_000_000 * 1024,  # bytes
                    "inode_hard_limit": 1_000_000,
                    "inode_soft_limit": 800_000,
                    "inode_current": 200_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 20_000_000,
                    "block_soft_limit": 18_000_000,
                    "block_current": 5_000_000 * 1024,  # bytes
                    "inode_hard_limit": 2_000_000,
                    "inode_soft_limit": 1_500_000,
                    "inode_current": 400_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1002: {
                    "block_hard_limit": 50_000_000,
                    "block_soft_limit": 40_000_000,
                    "block_current": 10_000_000 * 1024,  # bytes
                    "inode_hard_limit": 5_000_000,
                    "inode_soft_limit": 4_000_000,
                    "inode_current": 1_000_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
        },
        "/dev/sdb1": {
            "name": "/dev/sdb1",
            "mount_points": ["/data", "/mnt/data"],
            "fstype": "ext4",
            "opts": ["rw", "usrquota"],
            # total 500 GiB, used 300 GiB; ~5% root reserve → user-addressable free 175 GiB
            "usage": {"free": 175 * 1024**3, "total": 500 * 1024**3, "used": 300 * 1024**3, "percent": 60.0},
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 14 * 86400, "inode_grace": 14 * 86400, "flags": 0},
            "group_quota_format": None,
            "group_quota_info": None,
            "user_quotas": {
                1000: {
                    "block_hard_limit": 10_000_000,
                    "block_soft_limit": 8_000_000,
                    "block_current": 2_000_000 * 1024,  # bytes
                    "inode_hard_limit": 1_000_000,
                    "inode_soft_limit": 800_000,
                    "inode_current": 50_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 20_000_000,
                    "block_soft_limit": 15_000_000,
                    "block_current": 12_000_000 * 1024,  # bytes
                    "inode_hard_limit": 2_000_000,
                    "inode_soft_limit": 1_500_000,
                    "inode_current": 1_200_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {},
        },
        "/dev/nvme0n1p1": {
            "name": "/dev/nvme0n1p1",
            "mount_points": ["/scratch"],
            "fstype": "xfs",
            "opts": ["rw", "usrquota", "grpquota"],
            # total 1 TiB, used 200 GiB; XFS-style reserve → user-addressable free 750 GiB
            "usage": {"free": 750 * 1024**3, "total": 1000 * 1024**3, "used": 200 * 1024**3, "percent": 20.0},
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 3 * 86400, "inode_grace": 3 * 86400, "flags": 0},
            "group_quota_format": "vfsv1",
            "group_quota_info": {"block_grace": 3 * 86400, "inode_grace": 3 * 86400, "flags": 0},
            "user_quotas": {
                1000: {
                    "block_hard_limit": 100_000_000,
                    "block_soft_limit": 80_000_000,
                    "block_current": 10_000_000 * 1024,  # bytes
                    "inode_hard_limit": 10_000_000,
                    "inode_soft_limit": 8_000_000,
                    "inode_current": 500_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1002: {
                    "block_hard_limit": 50_000_000,
                    "block_soft_limit": 40_000_000,
                    "block_current": 5_000_000 * 1024,  # bytes
                    "inode_hard_limit": 5_000_000,
                    "inode_soft_limit": 4_000_000,
                    "inode_current": 200_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {
                1000: {
                    "block_hard_limit": 500_000_000,
                    "block_soft_limit": 400_000_000,
                    "block_current": 100_000_000 * 1024,  # bytes
                    "inode_hard_limit": 50_000_000,
                    "inode_soft_limit": 40_000_000,
                    "inode_current": 2_000_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
        },
        "/dev/sdc1": {
            "name": "/dev/sdc1",
            "mount_points": ["/oversold"],
            "fstype": "ext4",
            "opts": ["rw", "usrquota"],
            # total 10 GiB, used 3 GiB; ~5% root reserve → user-addressable free 6.5 GiB
            "usage": {"free": int(6.5 * 1024**3), "total": 10 * 1024**3, "used": 3 * 1024**3, "percent": 30.0},
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 7 * 86400, "inode_grace": 7 * 86400, "flags": 0},
            "group_quota_format": None,
            "group_quota_info": None,
            "user_quotas": {
                1000: {
                    "block_hard_limit": 7_000_000,
                    "block_soft_limit": 6_000_000,
                    "block_current": 1_500_000 * 1024,
                    "inode_hard_limit": 100_000,
                    "inode_soft_limit": 80_000,
                    "inode_current": 20_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 7_000_000,
                    "block_soft_limit": 6_000_000,
                    "block_current": 1_000_000 * 1024,
                    "inode_hard_limit": 100_000,
                    "inode_soft_limit": 80_000,
                    "inode_current": 15_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {},
        },
        "/dev/sdd1": {
            "name": "/dev/sdd1",
            "mount_points": ["/full"],
            "fstype": "ext4",
            "opts": ["rw", "usrquota"],
            # disk full: no physical or user-addressable free
            "usage": {"free": 0, "total": 50 * 1024**3, "used": 50 * 1024**3, "percent": 100.0},
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 7 * 86400, "inode_grace": 7 * 86400, "flags": 0},
            "group_quota_format": None,
            "group_quota_info": None,
            "user_quotas": {
                1000: {
                    "block_hard_limit": 20_000_000,
                    "block_soft_limit": 18_000_000,
                    "block_current": 25_000_000 * 1024,
                    "inode_hard_limit": 500_000,
                    "inode_soft_limit": 400_000,
                    "inode_current": 300_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 25_000_000,
                    "block_soft_limit": 22_000_000,
                    "block_current": 24_000_000 * 1024,
                    "inode_hard_limit": 600_000,
                    "inode_soft_limit": 500_000,
                    "inode_current": 280_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {},
        },
        "/dev/vda1": {
            "name": "/dev/vda1",
            "mount_points": ["/"],
            "fstype": "ext4",
            "opts": ["rw"],
            # total 20 GiB, used 15 GiB; no quota but root reserve → user-addressable free 4 GiB
            "usage": {"free": 4 * 1024**3, "total": 20 * 1024**3, "used": 15 * 1024**3, "percent": 75.0},
            "user_quota_format": None,
            "user_quota_info": None,
            "group_quota_format": None,
            "group_quota_info": None,
            "user_quotas": {},
            "group_quotas": {},
        },
        "/dev/sde1": {
            "name": "/dev/sde1",
            "mount_points": ["/packed"],
            "fstype": "ext4",
            "opts": ["rw", "usrquota"],
            # 5% root reserved, ~10% other, users have used all remaining space (85% tracked, 0% user free)
            # total 100 GiB; used 95%; physical free 5% = root reserved; userFree = 0
            # otherUsage = 10% of total, trackedUsage = 85% of total
            "usage": {
                "free": 0,
                "total": 100 * 1024**3,
                "used": 95 * 1024**3,
                "percent": 95.0,
            },
            "user_quota_format": "vfsv1",
            "user_quota_info": {"block_grace": 7 * 86400, "inode_grace": 7 * 86400, "flags": 0},
            "group_quota_format": None,
            "group_quota_info": None,
            "user_quotas": {
                # trackedUsage = 85 GiB total; split across users (limits in 1K blocks)
                1000: {
                    "block_hard_limit": 30_000_000,
                    "block_soft_limit": 25_000_000,
                    "block_current": 40 * 1024**3,  # 40 GiB
                    "inode_hard_limit": 1_000_000,
                    "inode_soft_limit": 800_000,
                    "inode_current": 500_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1001: {
                    "block_hard_limit": 30_000_000,
                    "block_soft_limit": 25_000_000,
                    "block_current": 35 * 1024**3,  # 35 GiB
                    "inode_hard_limit": 1_000_000,
                    "inode_soft_limit": 800_000,
                    "inode_current": 400_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
                1002: {
                    "block_hard_limit": 15_000_000,
                    "block_soft_limit": 12_000_000,
                    "block_current": 10 * 1024**3,  # 10 GiB (40+35+10 = 85 GiB = trackedUsage)
                    "inode_hard_limit": 500_000,
                    "inode_soft_limit": 400_000,
                    "inode_current": 100_000,
                    "block_time_limit": 0,
                    "inode_time_limit": 0,
                },
            },
            "group_quotas": {},
        },
    }

    _mock_state["devices"] = devices
    _mock_state["users"] = users
    _mock_state["groups"] = groups


def get_devices_mock() -> dict[str, dict[str, Any]]:
    """Return devices from mock state (same shape as quota.get_devices())."""
    return {d["name"]: dict(d) for d in _mock_state["devices"].values()}


def collect_remote_quotas_mock() -> list[dict[str, Any]]:
    """Build list of devices with user/group quotas from mock state (same shape as collect_remote_quotas)."""
    results: list[dict[str, Any]] = []
    users = _mock_state["users"]
    groups = _mock_state["groups"]

    for dev in _mock_state["devices"].values():
        device: dict[str, Any] = {
            "name": dev["name"],
            "mount_points": list(dev["mount_points"]),
            "fstype": dev["fstype"],
            "opts": list(dev["opts"]),
            "usage": dict(dev["usage"]),
        }
        if dev.get("user_quota_format") is not None:
            device["user_quota_format"] = dev["user_quota_format"]
        if dev.get("user_quota_info") is not None:
            device["user_quota_info"] = dict(dev["user_quota_info"])
        if dev.get("group_quota_format") is not None:
            device["group_quota_format"] = dev["group_quota_format"]
        if dev.get("group_quota_info") is not None:
            device["group_quota_info"] = dict(dev["group_quota_info"])

        user_quotas = dev.get("user_quotas") or {}
        if user_quotas:
            device["user_quotas"] = [
                {**q, "uid": uid, "name": users.get(uid, f"user{uid}")}
                for uid, q in user_quotas.items()
            ]
        group_quotas = dev.get("group_quotas") or {}
        if group_quotas:
            device["group_quotas"] = [
                {**q, "gid": gid, "name": groups.get(gid, f"group{gid}")}
                for gid, q in group_quotas.items()
            ]

        if device.get("user_quotas") or device.get("group_quotas"):
            results.append(device)

    return results


def collect_remote_quotas_for_uid_mock(uid: int) -> list[dict[str, Any]]:
    """Build list of devices where the given user has a quota (same shape as collect_remote_quotas_for_uid)."""
    results: list[dict[str, Any]] = []
    users = _mock_state["users"]

    for dev in _mock_state["devices"].values():
        user_quotas = dev.get("user_quotas") or {}
        if uid not in user_quotas:
            continue
        device: dict[str, Any] = {
            "name": dev["name"],
            "mount_points": list(dev["mount_points"]),
            "fstype": dev["fstype"],
            "opts": list(dev["opts"]),
            "usage": dict(dev["usage"]),
        }
        if dev.get("user_quota_format") is not None:
            device["user_quota_format"] = dev["user_quota_format"]
        if dev.get("user_quota_info") is not None:
            device["user_quota_info"] = dict(dev["user_quota_info"])
        q = dict(user_quotas[uid])
        q["uid"] = uid
        q["name"] = users.get(uid, f"user{uid}")
        device["user_quotas"] = [q]
        results.append(device)

    return results


def set_user_quota_mock(
    device_name: str,
    uid: int,
    block_hard_limit: int | None,
    block_soft_limit: int | None,
    inode_hard_limit: int | None,
    inode_soft_limit: int | None,
) -> None:
    """Update mock user quota for device/uid. None means leave unchanged."""
    devices = _mock_state["devices"]
    if device_name not in devices:
        raise ValueError(f"device not found: {device_name}")
    dev = devices[device_name]
    user_quotas = dev.get("user_quotas") or {}
    if uid not in user_quotas:
        user_quotas[uid] = dict(zip(
            [
                "block_hard_limit", "block_soft_limit", "block_current",
                "inode_hard_limit", "inode_soft_limit", "inode_current",
                "block_time_limit", "inode_time_limit",
            ],
            _DEFAULT_QUOTA,
        ))
    q = user_quotas[uid]
    if block_hard_limit is not None:
        q["block_hard_limit"] = block_hard_limit
    if block_soft_limit is not None:
        q["block_soft_limit"] = block_soft_limit
    if inode_hard_limit is not None:
        q["inode_hard_limit"] = inode_hard_limit
    if inode_soft_limit is not None:
        q["inode_soft_limit"] = inode_soft_limit
    dev["user_quotas"] = user_quotas


def get_user_quota_mock(device_name: str, uid: int) -> dict[str, Any]:
    """Return user quota dict for device/uid (includes uid and name). Mimics pq.get_user_quota + quota_tuple_to_dict."""
    devices = _mock_state["devices"]
    users = _mock_state["users"]
    if device_name not in devices:
        raise ValueError(f"device not found: {device_name}")
    dev = devices[device_name]
    user_quotas = dev.get("user_quotas") or {}
    if uid not in user_quotas:
        raise ValueError(f"quota not found for uid {uid} on {device_name}")
    q = dict(user_quotas[uid])
    q["uid"] = uid
    q["name"] = users.get(uid, f"user{uid}")
    return q
