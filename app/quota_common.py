"""Shared helpers for quota backends (pyquota, ZFS)."""

# Same filtering as typical Linux "user" accounts: skip system uids/gids and nobody.
_MIN_UID = 1000
_MIN_GID = 1000
_NOBODY_UID = 65534
_NOBODY_GID = 65534


def should_include_uid(uid: int) -> bool:
    """Return True if this uid should be included in user quota listings (exclude system and nobody)."""
    return uid >= _MIN_UID and uid != _NOBODY_UID


def should_include_gid(gid: int) -> bool:
    """Return True if this gid should be included in group quota listings (exclude system and nobody)."""
    return gid >= _MIN_GID and gid != _NOBODY_GID
