"""drop_payload_from_notification_email_log

Revision ID: c8e9f0a1b234
Revises: b3c4d5e6f701
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8e9f0a1b234"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f701"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: drop unused payload column from notification_email_log."""
    with op.batch_alter_table("notification_email_log") as batch_op:
        batch_op.drop_column("payload")


def downgrade() -> None:
    """Downgrade schema: re-add payload column to notification_email_log."""
    with op.batch_alter_table("notification_email_log") as batch_op:
        batch_op.add_column(sa.Column("payload", sa.Text(), nullable=True))

