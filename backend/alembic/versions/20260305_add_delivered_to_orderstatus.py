"""add delivered to orderstatus enum

Revision ID: 20260305_delivered
Revises: 20260219_save_kiz
Create Date: 2026-03-05

"""
from alembic import op


revision = "20260305_delivered"
down_revision = "20260219_save_kiz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'delivered'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значений из enum
    pass
