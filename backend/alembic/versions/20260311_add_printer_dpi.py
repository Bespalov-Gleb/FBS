"""add printer_dpi to print_settings

Revision ID: 20260311_printer_dpi
Revises: 20260309_ozon_barcode_90
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa


revision = "20260311_printer_dpi"
down_revision = "20260309_ozon_barcode_90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("printer_dpi", sa.Integer(), nullable=True, server_default=sa.text("203")),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "printer_dpi")
