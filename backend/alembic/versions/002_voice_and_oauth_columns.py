"""Add voice + OAuth columns

Revision ID: 002
Revises: 001
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chat_messages: voice metadata + suggested follow-ups
    op.add_column("chat_messages", sa.Column("suggested_followups", sa.JSON(), nullable=True))
    op.add_column("chat_messages", sa.Column("is_voice", sa.Boolean(), nullable=True, server_default="false"))
    op.add_column("chat_messages", sa.Column("audio_url", sa.Text(), nullable=True))

    # users: OAuth provider tracking
    op.add_column("users", sa.Column("auth_provider", sa.String(20), nullable=True, server_default="email"))
    op.add_column("users", sa.Column("google_id", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_google_id", "users", type_="unique")
    op.drop_column("users", "google_id")
    op.drop_column("users", "auth_provider")
    op.drop_column("chat_messages", "audio_url")
    op.drop_column("chat_messages", "is_voice")
    op.drop_column("chat_messages", "suggested_followups")
