"""add settings table

Revision ID: a36dfdccfd88
Revises: dd89813b62f8
Create Date: 2026-07-17 00:14:58.724119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a36dfdccfd88'
down_revision: Union[str, Sequence[str], None] = 'dd89813b62f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the settings table (skips if already auto-created by app startup)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "settings" in inspector.get_table_names():
        return  # table already exists on this machine — nothing to do

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop the settings table."""
    op.drop_table("settings")