"""add static invite code to users

Revision ID: 20260309_static_invite
Revises: 20260309_user_invites
Create Date: 2026-03-09
"""
from alembic import op
import secrets

revision = "20260309_static_invite"
down_revision = "20260309_user_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS static_invite_code VARCHAR(16) UNIQUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_static_invite_code "
        "ON users(static_invite_code)"
    )
    # Заполнить статичные коды для существующих администраторов
    from sqlalchemy import text
    conn = op.get_bind()
    admins = conn.execute(
        text("SELECT id FROM users WHERE role = 'admin' AND static_invite_code IS NULL")
    ).fetchall()
    for (admin_id,) in admins:
        code = secrets.token_hex(8)
        conn.execute(
            text("UPDATE users SET static_invite_code = :code WHERE id = :id"),
            {"code": code, "id": admin_id},
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_static_invite_code")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS static_invite_code")
