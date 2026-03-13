"""add label_print_mode to print_settings

Revision ID: 20260312_label_mode
Revises: 20260312_print_scale
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


revision = "20260312_label_mode"
down_revision = "20260312_print_scale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("label_print_mode", sa.String(30), nullable=True, server_default="standard_58x40_noscale"),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "label_print_mode")
