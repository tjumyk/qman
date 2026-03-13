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
  op.create_foreign_key(
      "fk_notification_event_email_log_id",
      "notification_event",
      "notification_email_log",
      ["email_log_id"],
      ["id"],
      ondelete="SET NULL",
  )


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_constraint("fk_notification_event_email_log_id", "notification_event", type_="foreignkey")

