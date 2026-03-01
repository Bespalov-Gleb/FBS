"""add auto_print_kiz_duplicate to print_settings

Revision ID: 20260219_kiz
Revises: 20260219_metadata
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa


revision = "20260219_kiz"
down_revision = "20260219_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("auto_print_kiz_duplicate", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "auto_print_kiz_duplicate")
