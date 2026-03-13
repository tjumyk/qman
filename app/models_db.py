"""SQLAlchemy ORM models (minimal schema for project rules)."""

from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Setting(Base):
    """Key-value settings (minimal table so DB stack is in place)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OAuthHostUserMapping(Base):
    """Mapping: OAuth user id <-> (host_id, host_user_name). Many-to-many."""

    __tablename__ = "oauth_host_user_mapping"

    oauth_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    host_user_name: Mapped[str] = mapped_column(String(255), primary_key=True)


class OAuthUserCache(Base):
    """Cache of OAuth user id -> name for admin UI (no OAuth server call)."""

    __tablename__ = "oauth_user_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


# --- Docker quota (slave-only tables) ---


class DockerContainerAttribution(Base):
    """Attribution of a container to a user (creator). Persisted on slave."""

    __tablename__ = "docker_container_attribution"

    container_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    host_user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DockerImageAttribution(Base):
    """Attribution of an image to a user (puller). Optional."""

    __tablename__ = "docker_image_attribution"

    image_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    puller_host_user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    puller_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DockerUserQuotaLimit(Base):
    """Per-user Docker quota limit (1K blocks). Stored on slave."""

    __tablename__ = "docker_user_quota_limit"

    uid: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_hard_limit: Mapped[int] = mapped_column(Integer, default=0)  # in 1K blocks
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DockerLayerAttribution(Base):
    """Attribution of a Docker layer to a user (first creator). Persisted on slave."""

    __tablename__ = "docker_layer_attribution"

    layer_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. sha256:abc123...
    first_puller_uid: Mapped[int | None] = mapped_column(Integer, nullable=True)  # uid of first creator
    first_puller_host_user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)  # incremental size from history
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    creation_method: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 'pull', 'build', 'commit', 'import', 'load'


class DockerVolumeAttribution(Base):
    """Attribution of a Docker volume to a user. Persisted on slave.
    
    Attribution priority:
    1. qman.user label on volume (source='label')
    2. First container (by creation time) that mounts it (source='container')
    3. Unattributed (not stored - handled as unattributed_bytes)
    
    Once attributed, ownership persists even if the container is removed (dangling volume).
    """

    __tablename__ = "docker_volume_attribution"

    volume_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    host_user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    attribution_source: Mapped[str] = mapped_column(String(32), default="container")  # 'label', 'container'
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DockerVolumeDiskUsage(Base):
    """Actual disk usage (du) scan results per volume. Success tuple + last attempt + pending.
    
    Success tuple (actual_disk_bytes, scan_started_at, scan_finished_at) updated only on success.
    Last attempt (last_scan_started_at, last_scan_finished_at, last_scan_status) on every run.
    pending_scan_started_at set when scan starts, cleared when it finishes.
    """

    __tablename__ = "docker_volume_disk_usage"

    volume_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    actual_disk_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scan_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pending_scan_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_scan_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_scan_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_scan_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # success, timeout, permission_denied, parse_failure


class DockerVolumeLastUsed(Base):
    """Last time a volume was mounted (from container start events). Used for smart skip of disk scan."""

    __tablename__ = "docker_volume_last_used"

    volume_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_mounted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# --- Default user quota per device (slave; used by all disk types) ---


class DeviceDefaultQuota(Base):
    """Per-device default user quota (soft/hard block and inode). Stored on slave."""

    __tablename__ = "device_default_quota"

    device_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    block_soft_limit: Mapped[int] = mapped_column(Integer, default=0)
    block_hard_limit: Mapped[int] = mapped_column(Integer, default=0)
    inode_soft_limit: Mapped[int] = mapped_column(Integer, default=0)
    inode_hard_limit: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationEmailLog(Base):
    """Log of quota-related notification emails sent (or attempted) by the master."""

    __tablename__ = "notification_email_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    oauth_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    host_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quota_type: Mapped[str] = mapped_column(String(32), default="unknown")

    event_type: Mapped[str] = mapped_column(String(64))

    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)

    send_status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_state: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional identifier to link multiple log rows that were sent in a single
    # batched email (e.g. multiple disk quota events combined into one message).
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Full HTML body of the email (optional, for detailed inspection in admin UI).
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)


class DiskQuotaNotificationState(Base):
    """Last known quota notification state per user/device on a slave."""

    __tablename__ = "disk_quota_notification_state"

    device_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    uid: Mapped[int] = mapped_column(Integer, primary_key=True)

    last_status: Mapped[str] = mapped_column(String(32))
    last_block_time_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_inode_time_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationEvent(Base):
    """Generic quota/Docker event received from slaves.

    Represents a single logical event (disk or Docker). Email sending is tracked
    separately via NotificationEmailLog, and events may or may not be linked to
    an email log row.
    """

    __tablename__ = "notification_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    oauth_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    host_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quota_type: Mapped[str] = mapped_column(String(32), default="unknown")

    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Normalized state identifier used for throttling (e.g. disk/docker + host/user/device + state category).
    state_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Optional link to the email log row that included this event (if any).
    email_log_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("notification_email_log.id"), nullable=True)
