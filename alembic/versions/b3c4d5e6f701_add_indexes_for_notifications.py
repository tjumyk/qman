"""add_indexes_for_notifications

Revision ID: b3c4d5e6f701
Revises: 7a2e9b4c6d89
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f701"
down_revision: Union[str, Sequence[str], None] = "7a2e9b4c6d89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Helpful composite index for common admin notification filters.
    op.create_index(
        "ix_notification_email_log_host_email_event_created",
        "notification_email_log",
        ["host_id", "email", "event_type", "send_status", "created_at"],
        unique=False,
    )

    # Additional indexes to speed up event introspection.
    op.create_index(
        "ix_notification_event_event_type",
        "notification_event",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_notification_event_host_id",
        "notification_event",
        ["host_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notification_event_host_id", table_name="notification_event")
    op.drop_index("ix_notification_event_event_type", table_name="notification_event")
    op.drop_index(
        "ix_notification_email_log_host_email_event_created",
        table_name="notification_email_log",
    )

