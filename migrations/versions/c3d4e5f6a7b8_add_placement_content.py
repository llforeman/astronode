"""add placement_content and sun_moon_interaction tables

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-17

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'placement_content',
        sa.Column('id',           sa.Integer(),     nullable=False),
        sa.Column('body',         sa.String(10),    nullable=False),
        sa.Column('sign',         sa.String(20),    nullable=False),
        sa.Column('seo_body',     sa.Text(),        nullable=True),
        sa.Column('preview_text', sa.Text(),        nullable=True),
        sa.Column('meta_title',   sa.String(100),   nullable=True),
        sa.Column('meta_desc',    sa.String(200),   nullable=True),
        sa.Column('lang',         sa.String(5),     nullable=False, server_default='es'),
        sa.Column('updated_at',   sa.DateTime(),    nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('body', 'sign', 'lang', name='uq_placement_lang'),
    )

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


def downgrade():
    op.drop_table('sun_moon_interaction')
    op.drop_table('placement_content')
