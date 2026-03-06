"""add ozon wb dimensions to print_settings

Revision ID: 20260305_print_dims
Revises: 20260305_delivered
Create Date: 2026-03-05

"""
from alembic import op
import sqlalchemy as sa


revision = "20260305_print_dims"
down_revision = "20260305_delivered"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("ozon_width_mm", sa.Integer(), nullable=True),
    )
    op.add_column(
        "print_settings",
        sa.Column("ozon_height_mm", sa.Integer(), nullable=True),
    )
    op.add_column(
        "print_settings",
        sa.Column("wb_width_mm", sa.Integer(), nullable=True),
    )
    op.add_column(
        "print_settings",
        sa.Column("wb_height_mm", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "wb_height_mm")
    op.drop_column("print_settings", "wb_width_mm")
    op.drop_column("print_settings", "ozon_height_mm")
    op.drop_column("print_settings", "ozon_width_mm")
