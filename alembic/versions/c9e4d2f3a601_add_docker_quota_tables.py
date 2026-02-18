"""add_docker_quota_tables

Revision ID: c9e4d2f3a601
Revises: b8f3c1d2e590
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e4d2f3a601"
down_revision: Union[str, Sequence[str], None] = "b8f3c1d2e590"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_container_attribution",
        sa.Column("container_id", sa.String(length=64), nullable=False),
        sa.Column("host_user_name", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column("image_id", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("container_id"),
    )
    op.create_table(
        "docker_image_attribution",
        sa.Column("image_id", sa.String(length=64), nullable=False),
        sa.Column("puller_host_user_name", sa.String(length=255), nullable=False),
        sa.Column("puller_uid", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("image_id"),
    )
    op.create_table(
        "docker_user_quota_limit",
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("block_hard_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("uid"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_user_quota_limit")
    op.drop_table("docker_image_attribution")
    op.drop_table("docker_container_attribution")
