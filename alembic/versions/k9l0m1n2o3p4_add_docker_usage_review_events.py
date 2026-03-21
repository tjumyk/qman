"""add_docker_usage_review_events

Revision ID: k9l0m1n2o3p4
Revises: h1i2j3k4l5m6
Create Date: 2026-03-20

Persist parsed Docker/audit usage events for admin review.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k9l0m1n2o3p4"
down_revision: Union[str, Sequence[str], None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "docker_usage_audit_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="audit"),
        sa.Column("event_ts", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("image_id", sa.String(length=64), nullable=True),
        sa.Column("image_ref", sa.String(length=255), nullable=True),
        sa.Column("volume_name", sa.String(length=255), nullable=True),

        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column("host_user_name", sa.String(length=255), nullable=True),

        sa.Column("audit_key", sa.String(length=64), nullable=True),
        sa.Column("docker_subcommand", sa.String(length=64), nullable=True),

        sa.Column("payload", sa.Text(), nullable=False),

        sa.Column(
            "used_for_auto_attribution",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("manual_resolved_at", sa.DateTime(), nullable=True),
        sa.Column("manual_resolved_by_oauth_user_id", sa.Integer(), nullable=True),

        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_docker_usage_audit_event_fingerprint"),
    )

    op.create_table(
        "docker_usage_docker_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="docker"),
        sa.Column("event_ts", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),

        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("image_id", sa.String(length=64), nullable=True),
        sa.Column("image_ref", sa.String(length=255), nullable=True),
        sa.Column("volume_name", sa.String(length=255), nullable=True),

        sa.Column("uid", sa.Integer(), nullable=True),
        sa.Column("host_user_name", sa.String(length=255), nullable=True),

        sa.Column("docker_event_type", sa.String(length=64), nullable=True),
        sa.Column("docker_action", sa.String(length=64), nullable=True),
        sa.Column("docker_actor_id", sa.String(length=128), nullable=True),

        sa.Column("payload", sa.Text(), nullable=False),

        sa.Column(
            "used_for_auto_attribution",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("manual_resolved_at", sa.DateTime(), nullable=True),
        sa.Column("manual_resolved_by_oauth_user_id", sa.Integer(), nullable=True),

        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_docker_usage_docker_event_fingerprint"),
    )

    # Basic indexes for admin review queue filtering by entity association.
    op.create_index(
        "ix_docker_usage_audit_event_container_id",
        "docker_usage_audit_event",
        ["container_id"],
        unique=False,
    )
    op.create_index(
        "ix_docker_usage_audit_event_image_id",
        "docker_usage_audit_event",
        ["image_id"],
        unique=False,
    )
    op.create_index(
        "ix_docker_usage_audit_event_volume_name",
        "docker_usage_audit_event",
        ["volume_name"],
        unique=False,
    )

    op.create_index(
        "ix_docker_usage_docker_event_container_id",
        "docker_usage_docker_event",
        ["container_id"],
        unique=False,
    )
    op.create_index(
        "ix_docker_usage_docker_event_image_id",
        "docker_usage_docker_event",
        ["image_id"],
        unique=False,
    )
    op.create_index(
        "ix_docker_usage_docker_event_volume_name",
        "docker_usage_docker_event",
        ["volume_name"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("docker_usage_docker_event")
    op.drop_table("docker_usage_audit_event")

