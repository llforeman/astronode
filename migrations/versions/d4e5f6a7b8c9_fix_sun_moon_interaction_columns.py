"""fix sun_moon_interaction: directional sun_sign/moon_sign instead of alphabetical sign_a/sign_b

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # Table is empty — drop and recreate with correct column names
    op.drop_table('sun_moon_interaction')
    op.create_table(
        'sun_moon_interaction',
        sa.Column('id',        sa.Integer(),  nullable=False),
        sa.Column('sun_sign',  sa.String(20), nullable=False),
        sa.Column('moon_sign', sa.String(20), nullable=False),
        sa.Column('text',      sa.Text(),     nullable=True),
        sa.Column('lang',      sa.String(5),  nullable=False, server_default='es'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sun_sign', 'moon_sign', 'lang', name='uq_sunmoon_lang'),
    )


def downgrade():
    op.drop_table('sun_moon_interaction')
    op.create_table(
        'sun_moon_interaction',
        sa.Column('id',     sa.Integer(),  nullable=False),
        sa.Column('sign_a', sa.String(20), nullable=False),
        sa.Column('sign_b', sa.String(20), nullable=False),
        sa.Column('text',   sa.Text(),     nullable=True),
        sa.Column('lang',   sa.String(5),  nullable=False, server_default='es'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sign_a', 'sign_b', 'lang', name='uq_sunmoon_lang'),
    )
