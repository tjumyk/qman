"""Quota logic using pyquota and psutil."""

import grp
import pwd
from typing import Any

import psutil
import pyquota as pq

from app.models import quota_tuple_to_dict

_QUOTA_FORMAT_NAMES = {
    pq.QFMT_VFS_OLD: "vfsold",
    pq.QFMT_VFS_V0: "vfsv0",
    pq.QFMT_VFS_V1: "vfsv1",
}


def get_devices() -> dict[str, dict[str, Any]]:
    """Enumerate disk partitions and their usage. Returns dict keyed by device name."""
    devices: dict[str, dict[str, Any]] = {}
    for partition in psutil.disk_partitions():
        device = devices.get(partition.device)
        if device is None:
            device = {
                "name": partition.device,
                "mount_points": [],
                "fstype": partition.fstype,
                "opts": partition.opts.split(","),
            }
            devices[partition.device] = device
        device["mount_points"].append(partition.mountpoint)

    for device in devices.values():
        usage = psutil.disk_usage(device["mount_points"][0])
        device["usage"] = {
            "free": usage.free,
            "total": usage.total,
            "used": usage.used,
            "percent": usage.percent,
        }
    return devices


def collect_remote_quotas() -> list[dict[str, Any]]:
    """Build list of devices with user/group quotas (for remote-api/quotas)."""
    results: list[dict[str, Any]] = []
    devices = get_devices()

    for device in devices.values():
        device_name = device["name"]
        opts = device["opts"]
        user_quotas: list[dict[str, Any]] | None = None
        group_quotas: list[dict[str, Any]] | None = None

        if "usrquota" in opts:
            try:
                fmt = pq.get_user_quota_format(device_name)
                device["user_quota_format"] = _QUOTA_FORMAT_NAMES[fmt]
            except pq.APIError:
                pass

            try:
                bgrace, igrace, flags = pq.get_user_quota_info(device_name)
                device["user_quota_info"] = {
                    "block_grace": bgrace,
                    "inode_grace": igrace,
                    "flags": flags,
                }
            except pq.APIError:
                pass

            user_quotas = []
            for entry in pwd.getpwall():
                uid = entry.pw_uid
                if uid < 1000 or uid == 65534:
                    continue
                try:
                    quota = pq.get_user_quota(device_name, uid)
                    quota_dict = quota_tuple_to_dict(quota)
                    quota_dict["uid"] = uid
                    quota_dict["name"] = entry.pw_name
                    user_quotas.append(quota_dict)
                except pq.APIError:
                    pass

        if "grpquota" in opts:
            try:
                fmt = pq.get_group_quota_format(device_name)
                device["group_quota_format"] = _QUOTA_FORMAT_NAMES[fmt]
            except pq.APIError:
                pass

            try:
                bgrace, igrace, flags = pq.get_group_quota_info(device_name)
                device["group_quota_info"] = {
                    "block_grace": bgrace,
                    "inode_grace": igrace,
                    "flags": flags,
                }
            except pq.APIError:
                pass

            group_quotas = []
            for entry in grp.getgrall():
                gid = entry.gr_gid
                if gid < 1000 or gid == 65534:
                    continue
                try:
                    quota = pq.get_group_quota(device_name, gid)
                    quota_dict = quota_tuple_to_dict(quota)
                    quota_dict["gid"] = gid
                    quota_dict["name"] = entry.gr_name
                    group_quotas.append(quota_dict)
                except pq.APIError:
                    pass

        if user_quotas is not None or group_quotas is not None:
            if user_quotas is not None:
                device["user_quotas"] = user_quotas
            if group_quotas is not None:
                device["group_quotas"] = group_quotas
            results.append(device)

    return results
