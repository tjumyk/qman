"""add_layer_override_size_bytes

Revision ID: p6q7r8s9t012
Revises: s2t3u4v5w6x7
Create Date: 2026-03-23

Store incremental layer size on manual layer overrides so quota does not rely on
docker_layer_attribution rows or a full image scan for override-only layers.

Uses ``batch_alter_table`` so SQLite (limited ``ALTER TABLE``) and PostgreSQL both work;
same pattern as ``c8e9f0a1b234_drop_payload_from_notification_email_log``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p6q7r8s9t012"
down_revision: Union[str, Sequence[str], None] = "s2t3u4v5w6x7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("docker_layer_attribution_override") as batch_op:
        batch_op.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("docker_layer_attribution_override") as batch_op:
        batch_op.drop_column("size_bytes")
