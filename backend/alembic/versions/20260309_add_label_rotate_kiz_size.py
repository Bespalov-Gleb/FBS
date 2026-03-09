"""add label rotate and kiz size to print_settings

Revision ID: 20260309_label_rotate
Revises: 20260307_collected
Create Date: 2026-03-09
"""
from alembic import op

revision = "20260309_label_rotate"
down_revision = "20260307_collected"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS ozon_label_rotate INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS kiz_width_mm INTEGER"
    )
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS kiz_height_mm INTEGER"
    )


def downgrade() -> None:
    op.drop_column("print_settings", "ozon_label_rotate")
    op.drop_column("print_settings", "kiz_width_mm")
    op.drop_column("print_settings", "kiz_height_mm")
