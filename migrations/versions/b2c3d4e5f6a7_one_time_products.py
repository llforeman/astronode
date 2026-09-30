"""one-time products: rename tiers, add payment.product, unique stripe_session_id

Revision ID: b2c3d4e5f6a7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    # Old monthly tiers -> one-time entitlement names
    op.execute("UPDATE user SET tier = 'complete' WHERE tier = 'vip'")
    op.execute("UPDATE user SET tier = 'natal' WHERE tier = 'basic'")
    op.execute("UPDATE reading_type SET min_tier = 'complete' WHERE min_tier = 'vip'")
    op.execute("UPDATE reading_type SET min_tier = 'natal' WHERE min_tier = 'basic'")
    op.execute("UPDATE subscription SET tier = 'complete' WHERE tier = 'vip'")
    op.execute("UPDATE subscription SET tier = 'natal' WHERE tier = 'basic'")

    with op.batch_alter_table('payment', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product', sa.String(length=20), nullable=True))

    # Idempotency guard: dedupe replays before enforcing uniqueness.
    op.execute(
        "DELETE FROM payment WHERE stripe_session_id IS NOT NULL AND id NOT IN ("
        "  SELECT MIN(id) FROM ("
        "    SELECT id, stripe_session_id FROM payment WHERE stripe_session_id IS NOT NULL"
        "  ) AS p GROUP BY p.stripe_session_id)"
    )
    with op.batch_alter_table('payment', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_payment_stripe_session', ['stripe_session_id'])


def downgrade():
    with op.batch_alter_table('payment', schema=None) as batch_op:
        batch_op.drop_constraint('uq_payment_stripe_session', type_='unique')
        batch_op.drop_column('product')

    op.execute("UPDATE user SET tier = 'vip' WHERE tier = 'complete'")
    op.execute("UPDATE user SET tier = 'basic' WHERE tier = 'natal'")
    op.execute("UPDATE reading_type SET min_tier = 'vip' WHERE min_tier = 'complete'")
    op.execute("UPDATE reading_type SET min_tier = 'basic' WHERE min_tier = 'natal'")
    op.execute("UPDATE subscription SET tier = 'vip' WHERE tier = 'complete'")
    op.execute("UPDATE subscription SET tier = 'basic' WHERE tier = 'natal'")
