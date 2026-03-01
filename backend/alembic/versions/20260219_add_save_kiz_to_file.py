"""add save_kiz_to_file to marketplaces

Revision ID: 20260219_save_kiz
Revises: 20260219_kiz
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa


revision = "20260219_save_kiz"
down_revision = "20260219_kiz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplaces",
        sa.Column("save_kiz_to_file", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("marketplaces", "save_kiz_to_file")
