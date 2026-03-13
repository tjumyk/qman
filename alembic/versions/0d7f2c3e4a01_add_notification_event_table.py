"""add_notification_event_table

Revision ID: 0d7f2c3e4a01
Revises: ff6c1b2a3d45
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0d7f2c3e4a01"
down_revision: Union[str, Sequence[str], None] = "ff6c1b2a3d45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_event",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("oauth_user_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("host_id", sa.String(length=255), nullable=True),
        sa.Column("host_user_name", sa.String(length=255), nullable=True),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("quota_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("state_key", sa.String(length=255), nullable=True),
        sa.Column("email_log_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_notification_event_created_at",
        "notification_event",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_event_state_key",
        "notification_event",
        ["state_key"],
        unique=False,
    )
    op.create_index(
        "ix_notification_event_oauth_user_id",
        "notification_event",
        ["oauth_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notification_event_oauth_user_id", table_name="notification_event")
    op.drop_index("ix_notification_event_state_key", table_name="notification_event")
    op.drop_index("ix_notification_event_created_at", table_name="notification_event")
    op.drop_table("notification_event")

