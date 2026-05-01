"""add auto_kiz_autofill to print_settings

Revision ID: 20260501_auto_kiz_autofill
Revises: 20260421_kiz_groups_pool
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260501_auto_kiz_autofill"
down_revision = "20260421_kiz_groups_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("auto_kiz_autofill", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "auto_kiz_autofill")
