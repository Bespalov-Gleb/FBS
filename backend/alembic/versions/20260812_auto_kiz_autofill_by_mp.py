"""auto_kiz_autofill per marketplace (wb/ozon)

Revision ID: 20260812_kiz_autofill_mp
Revises: 20260811_kiz_settings
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa


revision = "20260812_kiz_autofill_mp"
down_revision = "20260811_kiz_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("auto_kiz_autofill_wb", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "print_settings",
        sa.Column("auto_kiz_autofill_ozon", sa.String(length=10), nullable=True),
    )
    # Перенос старого глобального флага: true/null → оба включены, false → оба выключены.
    op.execute(
        """
        UPDATE print_settings
        SET
            auto_kiz_autofill_wb = CASE
                WHEN auto_kiz_autofill = 'false' THEN 'false'
                ELSE 'true'
            END,
            auto_kiz_autofill_ozon = CASE
                WHEN auto_kiz_autofill = 'false' THEN 'false'
                ELSE 'true'
            END
        """
    )


def downgrade() -> None:
    op.drop_column("print_settings", "auto_kiz_autofill_ozon")
    op.drop_column("print_settings", "auto_kiz_autofill_wb")
