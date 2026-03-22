"""Shared helpers for quota backends (pyquota, ZFS)."""

from __future__ import annotations

import pwd
from typing import Any

# Same filtering as typical Linux "user" accounts: skip system uids/gids and nobody.
_MIN_UID = 1000
_MIN_GID = 1000
_NOBODY_UID = 65534
_NOBODY_GID = 65534
_MAX_UID = 9999
_MAX_GID = 9999


def should_include_uid(uid: int) -> bool:
    """Return True if this uid should be included in user quota listings (exclude system and nobody)."""
    return uid >= _MIN_UID and uid != _NOBODY_UID and uid <= _MAX_UID


def should_include_gid(gid: int) -> bool:
    """Return True if this gid should be included in group quota listings (exclude system and nobody)."""
    return gid >= _MIN_GID and gid != _NOBODY_GID and gid <= _MAX_GID


def build_name_to_uid_from_container_attributions(
    attributions: list[dict[str, Any]],
) -> dict[str, int]:
    """Map host user name -> Linux uid from container attribution rows, with passwd fallback."""
    name_to_uid: dict[str, int] = {}
    for att in attributions:
        name = att["host_user_name"]
        if name not in name_to_uid and att.get("uid") is not None:
            name_to_uid[name] = att["uid"]
    for att in attributions:
        name = att["host_user_name"]
        if name in name_to_uid:
            continue
        try:
            name_to_uid[name] = pwd.getpwnam(name).pw_uid
        except KeyError:
            pass
    return name_to_uid


def resolve_uid_for_docker_attribution(
    uid: int | None,
    host_user_name: str | None,
    name_to_uid: dict[str, int],
) -> int | None:
    """Resolve Linux uid for Docker quota aggregation when the DB row may omit uid."""
    if uid is not None:
        return uid
    if not host_user_name:
        return None
    if host_user_name in name_to_uid:
        return name_to_uid[host_user_name]
    try:
        return pwd.getpwnam(host_user_name).pw_uid
    except KeyError:
        return None
