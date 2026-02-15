"""Pydantic models for config and API request/response."""

from typing import Any

from pydantic import BaseModel, Field


# --- Config ---


class SlaveConfig(BaseModel):
    """Single slave in master config."""

    id: str
    url: str
    api_key: str


class AppConfig(BaseModel):
    """Flask app config (master or slave)."""

    SECRET_KEY: str
    SESSION_COOKIE_NAME: str = "qman_session"
    SLAVES: list[SlaveConfig] = Field(default_factory=list)
    API_KEY: str | None = None
    PORT: int | None = None
    MOCK_QUOTA: bool = False  # If true, slave uses in-memory mock instead of pyquota
    MOCK_HOST_ID: str | None = None  # When MOCK_QUOTA: which host's mock data to use (e.g. host1, host2)


# --- API: Error ---


class BasicError(BaseModel):
    """Error response body."""

    msg: str
    detail: str | None = None


# --- API: Quota (remote-api and aggregation) ---


class DiskUsage(BaseModel):
    """Disk usage for a device."""

    free: int
    total: int
    used: int
    percent: float


class QuotaInfo(BaseModel):
    """Quota grace/time info."""

    block_grace: int
    inode_grace: int
    flags: int


class QuotaBase(BaseModel):
    """Quota limits and current usage."""

    block_hard_limit: int
    block_soft_limit: int
    block_current: int
    inode_hard_limit: int
    inode_soft_limit: int
    inode_current: int
    block_time_limit: int
    inode_time_limit: int


class UserQuota(QuotaBase):
    """User quota with uid and name."""

    uid: int
    name: str


class GroupQuota(QuotaBase):
    """Group quota with gid and name."""

    gid: int
    name: str


class SetUserQuotaRequest(BaseModel):
    """PUT body for setting user quota."""

    block_hard_limit: int | None = None
    block_soft_limit: int | None = None
    inode_hard_limit: int | None = None
    inode_soft_limit: int | None = None


# Device quota: optional user/group quotas and info (built from pyquota/psutil)
# We use a flexible model so we can build it incrementally in quota.py
class DeviceQuotaResponse(BaseModel):
    """Single device with optional user/group quotas."""

    model_config = {"extra": "allow"}

    name: str
    mount_points: list[str]
    fstype: str
    opts: list[str]
    usage: DiskUsage
    user_quota_format: str | None = None
    user_quota_info: QuotaInfo | None = None
    user_quotas: list[UserQuota] | None = None
    group_quota_format: str | None = None
    group_quota_info: QuotaInfo | None = None
    group_quotas: list[GroupQuota] | None = None


def quota_tuple_to_dict(quota: tuple[Any, ...]) -> dict[str, Any]:
    """Convert pyquota 8-tuple to dict for JSON."""
    bhard, bsoft, bcurrent, ihard, isoft, icurrent, btime, itime = quota
    return {
        "block_hard_limit": bhard,
        "block_soft_limit": bsoft,
        "block_current": bcurrent,
        "inode_hard_limit": ihard,
        "inode_soft_limit": isoft,
        "inode_current": icurrent,
        "block_time_limit": btime,
        "inode_time_limit": itime,
    }
