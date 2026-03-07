"""add_device_default_quota_table

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "device_default_quota",
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("block_soft_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("block_hard_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inode_soft_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inode_hard_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("device_name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("device_default_quota")
