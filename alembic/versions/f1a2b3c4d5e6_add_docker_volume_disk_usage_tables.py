"""add_docker_volume_disk_usage_and_last_used_tables

Revision ID: f1a2b3c4d5e6
Revises: e3f5a7b9c812
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e3f5a7b9c812'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_volume_disk_usage",
        sa.Column("volume_name", sa.String(length=255), nullable=False),
        sa.Column("actual_disk_bytes", sa.Integer(), nullable=True),
        sa.Column("scan_started_at", sa.DateTime(), nullable=True),
        sa.Column("scan_finished_at", sa.DateTime(), nullable=True),
        sa.Column("pending_scan_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_scan_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_scan_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_scan_status", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("volume_name"),
    )
    op.create_table(
        "docker_volume_last_used",
        sa.Column("volume_name", sa.String(length=255), nullable=False),
        sa.Column("last_mounted_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("volume_name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_volume_last_used")
    op.drop_table("docker_volume_disk_usage")
