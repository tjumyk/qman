"""add_docker_attribution_override_tables

Revision ID: s2t3u4v5w6x7
Revises: k9l0m1n2o3p4
Create Date: 2026-03-20

Add admin-only manual attribution override tables for container/image/layer/volume.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s2t3u4v5w6x7"
down_revision: Union[str, Sequence[str], None] = "k9l0m1n2o3p4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_container_attribution_override",
        sa.Column("container_id", sa.String(length=64), nullable=False),
        sa.Column("host_user_name", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_by_oauth_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("container_id"),
    )

    op.create_table(
        "docker_image_attribution_override",
        sa.Column("image_id", sa.String(length=64), nullable=False),
        sa.Column("puller_host_user_name", sa.String(length=255), nullable=False),
        sa.Column("puller_uid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_by_oauth_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("image_id"),
    )

    op.create_table(
        "docker_layer_attribution_override",
        sa.Column("layer_id", sa.String(length=64), nullable=False),
        sa.Column("first_puller_host_user_name", sa.String(length=255), nullable=False),
        sa.Column("first_puller_uid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_by_oauth_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("layer_id"),
    )

    op.create_table(
        "docker_volume_attribution_override",
        sa.Column("volume_name", sa.String(length=255), nullable=False),
        sa.Column("host_user_name", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_by_oauth_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("volume_name"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_volume_attribution_override")
    op.drop_table("docker_layer_attribution_override")
    op.drop_table("docker_image_attribution_override")
    op.drop_table("docker_container_attribution_override")

