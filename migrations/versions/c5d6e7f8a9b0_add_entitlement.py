"""add entitlement table (per-purchase credits: 1 person natal / 2 person pack)

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'entitlement',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=False),
        sa.Column('product', sa.String(length=20), nullable=False),
        sa.Column('profile_a_id', sa.Integer(), nullable=True),
        sa.Column('profile_b_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['payment_id'], ['payment.id']),
        sa.ForeignKeyConstraint(['profile_a_id'], ['profile.id']),
        sa.ForeignKeyConstraint(['profile_b_id'], ['profile.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payment_id', name='uq_entitlement_payment'),
    )
    op.create_index('ix_entitlement_user_id', 'entitlement', ['user_id'])

    # Backfill: existing one-time payments become entitlements (unassigned).
    op.execute(
        "INSERT INTO entitlement (user_id, payment_id, product, created_at) "
        "SELECT user_id, id, product, created_at FROM payment "
        "WHERE payment_type = 'one_time' AND status = 'completed' "
        "AND product IN ('natal', 'complete')"
    )


def downgrade():
    op.drop_index('ix_entitlement_user_id', table_name='entitlement')
    op.drop_table('entitlement')
