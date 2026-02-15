"""add_oauth_host_user_mapping

Revision ID: b8f3c1d2e590
Revises: a56208869480
Create Date: 2026-02-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f3c1d2e590"
down_revision: Union[str, Sequence[str], None] = "a56208869480"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_host_user_mapping",
        sa.Column("oauth_user_id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.String(length=255), nullable=False),
        sa.Column("host_user_name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("oauth_user_id", "host_id", "host_user_name"),
    )
    op.create_table(
        "oauth_user_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("oauth_user_cache")
    op.drop_table("oauth_host_user_mapping")
