"""restructure zones as buildings, cameras belong to zones, rules multi-camera

Revision ID: a1b2c3d4e5f6
Revises: REPLACE_WITH_YOUR_CURRENT_HEAD_REVISION
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '71d3ba715ae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Camera now belongs to a Zone (a named building/place) ──
    op.add_column('cameras', sa.Column('zone_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_cameras_zone_id', 'cameras', 'zones',
        ['zone_id'], ['id'], ondelete='SET NULL',
    )

    # ── Zone drops everything that made it a hand-drawn region tied to one
    # camera — it's now purely a name. Existing polygon/color/camera_id
    # data is not preserved; this is a deliberate clean cut, not a partial
    # migration, per the new architecture. ──
    op.drop_constraint('zones_camera_id_fkey', 'zones', type_='foreignkey')
    op.drop_constraint('zones_created_by_fkey', 'zones', type_='foreignkey')
    op.drop_column('zones', 'camera_id')
    op.drop_column('zones', 'polygon')
    op.drop_column('zones', 'color')
    op.drop_column('zones', 'created_by')

    # ── Rule no longer has a single zone_id — which camera(s) it applies to
    # now lives in rule_cameras below, since one rule can span many cameras
    # across many zones. ──
    op.drop_constraint('rules_zone_id_fkey', 'rules', type_='foreignkey')
    op.drop_column('rules', 'zone_id')

    # ── New join table: one row per (rule, camera) pair ──
    op.create_table(
        'rule_cameras',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.id', ondelete='CASCADE'), nullable=False),
    )
    op.create_index('ix_rule_cameras_rule_id', 'rule_cameras', ['rule_id'])
    op.create_index('ix_rule_cameras_camera_id', 'rule_cameras', ['camera_id'])


def downgrade() -> None:
    op.drop_index('ix_rule_cameras_camera_id', table_name='rule_cameras')
    op.drop_index('ix_rule_cameras_rule_id', table_name='rule_cameras')
    op.drop_table('rule_cameras')

    op.add_column('rules', sa.Column('zone_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'rules_zone_id_fkey', 'rules', 'zones',
        ['zone_id'], ['id'], ondelete='SET NULL',
    )

    op.add_column('zones', sa.Column('created_by', sa.Integer(), nullable=True))
    op.add_column('zones', sa.Column('color', sa.Text(), nullable=True))
    op.add_column('zones', sa.Column('polygon', sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column('zones', sa.Column('camera_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'zones_created_by_fkey', 'zones', 'users', ['created_by'], ['id'],
    )
    op.create_foreign_key(
        'zones_camera_id_fkey', 'zones', 'cameras',
        ['camera_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_constraint('fk_cameras_zone_id', 'cameras', type_='foreignkey')
    op.drop_column('cameras', 'zone_id')
