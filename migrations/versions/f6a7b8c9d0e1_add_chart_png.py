"""add chart_png column to reading

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reading',
        sa.Column('chart_png', sa.LargeBinary(length=16777215), nullable=True)
    )


def downgrade():
    op.drop_column('reading', 'chart_png')
