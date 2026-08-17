"""add preview_hook and status to placement_content

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('placement_content', schema=None) as batch_op:
        batch_op.add_column(sa.Column('preview_hook', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(20), nullable=False,
                                      server_default='generated'))


def downgrade():
    with op.batch_alter_table('placement_content', schema=None) as batch_op:
        batch_op.drop_column('status')
        batch_op.drop_column('preview_hook')
