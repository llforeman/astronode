"""add cached sun/moon/ascendant signs to profile

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-09-30

Note: the historical initial Alembic migration does not create the
'profile' table (databases got it via db.create_all() before Alembic was
introduced). This migration therefore creates the table if it is missing
and adds only the columns that are absent otherwise.
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def _get_columns(bind, table):
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()

    if _get_columns(bind, 'profile') is None:
        # Fresh database: create the full profile table (current schema).
        op.create_table(
            'profile',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False, server_default='Me'),
            sa.Column('birth_date', sa.Date(), nullable=True),
            sa.Column('birth_time', sa.Time(), nullable=True),
            sa.Column('birth_place', sa.String(length=255), nullable=True),
            sa.Column('birth_lat', sa.Float(), nullable=True),
            sa.Column('birth_lng', sa.Float(), nullable=True),
            sa.Column('gender', sa.String(length=20), nullable=True),
            sa.Column('is_self', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('sun_sign', sa.String(length=20), nullable=True),
            sa.Column('moon_sign', sa.String(length=20), nullable=True),
            sa.Column('asc_sign', sa.String(length=20), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_profile_user_id', 'profile', ['user_id'])
        return

    cols = _get_columns(bind, 'profile')
    with op.batch_alter_table('profile', schema=None) as batch_op:
        if 'sun_sign' not in cols:
            batch_op.add_column(sa.Column('sun_sign', sa.String(20), nullable=True))
        if 'moon_sign' not in cols:
            batch_op.add_column(sa.Column('moon_sign', sa.String(20), nullable=True))
        if 'asc_sign' not in cols:
            batch_op.add_column(sa.Column('asc_sign', sa.String(20), nullable=True))


def downgrade():
    cols = _get_columns(op.get_bind(), 'profile')
    if cols is None:
        return
    with op.batch_alter_table('profile', schema=None) as batch_op:
        if 'asc_sign' in cols:
            batch_op.drop_column('asc_sign')
        if 'moon_sign' in cols:
            batch_op.drop_column('moon_sign')
        if 'sun_sign' in cols:
            batch_op.drop_column('sun_sign')
