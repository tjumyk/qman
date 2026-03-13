"""add_notification_email_log

Revision ID: f4a6b8c9d012
Revises: e3f5a7b9c812
Create Date: 2026-03-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a6b8c9d012"
down_revision: Union[str, Sequence[str], None] = "e3f5a7b9c812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_email_log",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("oauth_user_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("host_id", sa.String(length=255), nullable=True),
        sa.Column("host_user_name", sa.String(length=255), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("quota_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("send_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("last_state", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_notification_email_log_dedupe_key",
        "notification_email_log",
        ["dedupe_key"],
        unique=False,
    )
    op.create_index(
        "ix_notification_email_log_created_at",
        "notification_email_log",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "disk_quota_notification_state",
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("last_status", sa.String(length=32), nullable=False),
        sa.Column("last_block_time_limit", sa.Integer(), nullable=True),
        sa.Column("last_inode_time_limit", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("device_name", "uid"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("disk_quota_notification_state")
    op.drop_index("ix_notification_email_log_created_at", table_name="notification_email_log")
    op.drop_index("ix_notification_email_log_dedupe_key", table_name="notification_email_log")
    op.drop_table("notification_email_log")

