"""add_docker_layer_attribution_table

Revision ID: d2026759b218
Revises: c9e4d2f3a601
Create Date: 2026-02-18 00:31:15.318375

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2026759b218'
down_revision: Union[str, Sequence[str], None] = 'c9e4d2f3a601'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_layer_attribution",
        sa.Column("layer_id", sa.String(length=64), nullable=False),
        sa.Column("first_puller_uid", sa.Integer(), nullable=True),
        sa.Column("first_puller_host_user_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("creation_method", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("layer_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_layer_attribution")
