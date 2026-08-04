"""add training_jobs table

Revision ID: 71d3ba715ae6
Revises: 6bc96a8af982
Create Date: 2026-08-04 21:06:57.457108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '71d3ba715ae6'
down_revision: Union[str, Sequence[str], None] = '6bc96a8af982'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'training_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('site_id', sa.Integer(), nullable=False),
        sa.Column('class_name', sa.Text(), nullable=False),          # e.g. 'trousers'
        sa.Column('rule_id', sa.Integer(), nullable=True),           # pending rule waiting on this model
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        # pending -> searching_data -> preparing_dataset -> training -> evaluating -> awaiting_approval -> approved / failed / cancelled
        sa.Column('current_stage', sa.Text(), nullable=True),
        sa.Column('stages', postgresql.JSONB(), nullable=False, server_default='[]'),
        # [{"name": "searching_data", "status": "done", "started_at": "...", "finished_at": "...", "detail": "Found 3 datasets"}]
        sa.Column('dataset_info', postgresql.JSONB(), nullable=True),   # source, image counts, version path
        sa.Column('checkpoint_path', sa.Text(), nullable=True),         # resume point for training
        sa.Column('model_path', sa.Text(), nullable=True),               # final best.pt when done
        sa.Column('metrics', postgresql.JSONB(), nullable=True),         # precision/recall/mAP from evaluation
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_training_jobs_status', 'training_jobs', ['status'])
    op.create_index('ix_training_jobs_class_name', 'training_jobs', ['class_name'])


def downgrade() -> None:
    op.drop_index('ix_training_jobs_class_name', table_name='training_jobs')
    op.drop_index('ix_training_jobs_status', table_name='training_jobs')
    op.drop_table('training_jobs')