"""add pdf_content to reading

Revision ID: b1c2d3e4f5a6
Revises: f6a7b8c9d0e1
Create Date: 2026-08-28


"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reading',
        sa.Column('pdf_content', sa.LargeBinary(length=16777215), nullable=True)
    )


def downgrade():
    op.drop_column('reading', 'pdf_content')
