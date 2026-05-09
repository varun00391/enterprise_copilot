"""Create analytics tables: department_analytics and coverage_gaps

Revision ID: 004
Revises: 003
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "department_analytics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dept_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("health_score", sa.Float(), nullable=True),
        sa.Column("avg_confidence", sa.Float(), nullable=True),
        sa.Column("coverage_gap_ratio", sa.Float(), nullable=True),
        sa.Column("stale_doc_ratio", sa.Float(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index("ix_dept_analytics_dept_id", "department_analytics", ["dept_id"])

    op.create_table(
        "coverage_gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "dept_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_topic", sa.Text(), nullable=False),
        sa.Column("query_count", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("avg_confidence", sa.Float(), nullable=True),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index("ix_coverage_gaps_dept_id", "coverage_gaps", ["dept_id"])


def downgrade() -> None:
    op.drop_index("ix_coverage_gaps_dept_id", table_name="coverage_gaps")
    op.drop_table("coverage_gaps")
    op.drop_index("ix_dept_analytics_dept_id", table_name="department_analytics")
    op.drop_table("department_analytics")
