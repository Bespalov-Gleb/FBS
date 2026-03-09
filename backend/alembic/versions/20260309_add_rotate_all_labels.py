"""add rotate for wb_label, barcodes, kiz

Revision ID: 20260309_rotate_all
Revises: 20260309_label_rotate
Create Date: 2026-03-09
"""
from alembic import op

revision = "20260309_rotate_all"
down_revision = "20260309_label_rotate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS wb_label_rotate INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS barcode_rotate INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE print_settings "
        "ADD COLUMN IF NOT EXISTS kiz_rotate INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.drop_column("print_settings", "wb_label_rotate")
    op.drop_column("print_settings", "barcode_rotate")
    op.drop_column("print_settings", "kiz_rotate")
