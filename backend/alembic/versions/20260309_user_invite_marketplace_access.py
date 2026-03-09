"""user invite codes and marketplace access

Revision ID: 20260309_user_invites
Revises: 20260309_rotate_all
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "20260309_user_invites"
down_revision = "20260309_rotate_all"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # owner_id: упаковщик ссылается на пригласившего его admin
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )

    # Инвайт-коды
    op.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id          SERIAL PRIMARY KEY,
            code        VARCHAR(32) NOT NULL UNIQUE,
            created_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            used_by_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
            used_at     TIMESTAMP WITHOUT TIME ZONE,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_invite_codes_code ON invite_codes(code)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invite_codes_created_by_id ON invite_codes(created_by_id)")

    # Доступ упаковщика к конкретным магазинам
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_marketplace_access (
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            marketplace_id INTEGER NOT NULL REFERENCES marketplaces(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, marketplace_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_uma_user_id ON user_marketplace_access(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_marketplace_access")
    op.execute("DROP TABLE IF EXISTS invite_codes")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS owner_id")
