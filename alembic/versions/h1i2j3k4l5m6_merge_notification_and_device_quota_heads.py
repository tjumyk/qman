"""merge_notification_and_device_quota_heads

Revision ID: h1i2j3k4l5m6
Revises: c8e9f0a1b234, g2b3c4d5e6f7
Create Date: 2026-03-13

This is a pure merge revision that joins the notification-email-log/event
branch and the device_default_quota branch into a single linear head so
`alembic upgrade head` works without ambiguity.
"""
from typing import Sequence, Union

from alembic import op  # noqa: F401  (kept for Alembic API consistency)
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, Sequence[str], None] = ("c8e9f0a1b234", "g2b3c4d5e6f7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    This is an empty merge revision: both parent heads are already applied.
    """
    pass


def downgrade() -> None:
    """Downgrade schema.

    To downgrade past this merge point, Alembic will walk back through both
    parent branches as needed.
    """
    pass

