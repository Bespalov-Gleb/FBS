"""add label_scale_factor to print_settings

Revision ID: 20260317_scale
Revises: 20260312_label_mode
Create Date: 2026-03-17

"""
from alembic import op
import sqlalchemy as sa


revision = "20260317_scale"
down_revision = "20260312_label_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("label_scale_factor", sa.Float(), nullable=True, server_default="1.0"),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "label_scale_factor")
