"""add_fk_notification_event_email_log_id

Revision ID: 7a2e9b4c6d89
Revises: 0d7f2c3e4a01
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a2e9b4c6d89"
down_revision: Union[str, Sequence[str], None] = "0d7f2c3e4a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite does not support ALTER TABLE ADD CONSTRAINT directly; use batch mode.
    with op.batch_alter_table("notification_event") as batch_op:
        batch_op.create_foreign_key(
            "fk_notification_event_email_log_id",
            "notification_email_log",
            ["email_log_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notification_event") as batch_op:
        batch_op.drop_constraint("fk_notification_event_email_log_id", type_="foreignkey")

