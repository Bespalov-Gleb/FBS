"""set ozon_label_rotate and barcode_rotate default 90 for 58x40 labels

Revision ID: 20260309_ozon_barcode_90
Revises: 20260309_static_invite
Create Date: 2026-03-09

"""
from alembic import op


revision = "20260309_ozon_barcode_90"
down_revision = "20260309_static_invite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE print_settings SET ozon_label_rotate = 90 WHERE ozon_label_rotate = 0"
    )
    op.execute(
        "UPDATE print_settings SET wb_label_rotate = 90 WHERE wb_label_rotate = 0"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE print_settings SET ozon_label_rotate = 0 WHERE ozon_label_rotate = 90"
    )
    op.execute(
        "UPDATE print_settings SET wb_label_rotate = 0 WHERE wb_label_rotate = 90"
    )
