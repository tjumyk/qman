"""add_docker_volume_attribution_table

Revision ID: e3f5a7b9c812
Revises: d2026759b218
Create Date: 2026-02-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f5a7b9c812'
down_revision: Union[str, Sequence[str], None] = 'd2026759b218'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_volume_attribution",
        sa.Column("volume_name", sa.String(length=255), nullable=False),
        sa.Column("host_user_name", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attribution_source", sa.String(length=32), nullable=False, server_default="container"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("volume_name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_volume_attribution")
