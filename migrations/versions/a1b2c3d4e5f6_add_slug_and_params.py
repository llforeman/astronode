"""add slug to reading_type and params to reading

Revision ID: a1b2c3d4e5f6
Revises: 486c94ebc4fa
Create Date: 2026-08-16

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '486c94ebc4fa'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reading_type', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slug', sa.String(length=50), nullable=True))

    with op.batch_alter_table('reading', schema=None) as batch_op:
        batch_op.add_column(sa.Column('params', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('reading', schema=None) as batch_op:
        batch_op.drop_column('params')

    with op.batch_alter_table('reading_type', schema=None) as batch_op:
        batch_op.drop_column('slug')
