"""add_batch_id_to_notification_email_log

Revision ID: ff6c1b2a3d45
Revises: f4a6b8c9d012
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ff6c1b2a3d45"
down_revision: Union[str, Sequence[str], None] = "f4a6b8c9d012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notification_email_log",
        sa.Column("batch_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notification_email_log",
        sa.Column("body_html", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_notification_email_log_batch_id",
        "notification_email_log",
        ["batch_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notification_email_log", "body_html")
    op.drop_index("ix_notification_email_log_batch_id", table_name="notification_email_log")
    op.drop_column("notification_email_log", "batch_id")

