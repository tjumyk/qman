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
