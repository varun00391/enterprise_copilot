"""Add source_type and source_url to documents

Revision ID: 003
Revises: 002
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("source_type", sa.String(30), nullable=True, server_default="upload"),
    )
    op.add_column("documents", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "source_url")
    op.drop_column("documents", "source_type")
