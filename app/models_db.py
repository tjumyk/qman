"""SQLAlchemy ORM models (minimal schema for project rules)."""

from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
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
