"""add yandex to marketplacetype enum

Revision ID: 20261013_yandex_mp
Revises: 20260812_kiz_autofill_mp
Create Date: 2026-10-13

"""
from alembic import op


revision = "20261013_yandex_mp"
down_revision = "20260812_kiz_autofill_mp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE marketplacetype ADD VALUE IF NOT EXISTS 'yandex'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значений из enum
    pass
