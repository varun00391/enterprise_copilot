"""answer evaluations (RAGAS) + Langfuse trace link

Revision ID: 005_answer_evaluation
Revises: 004_analytics_tables
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "005_answer_evaluation"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answer_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answer_relevancy", sa.Float(), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_metrics", sa.JSON(), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dept_id"], ["departments.id"]),
        sa.UniqueConstraint("message_id", name="uq_answer_evaluations_message_id"),
    )
    op.create_index(
        "ix_answer_evaluations_flagged_created",
        "answer_evaluations",
        ["flagged", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_answer_evaluations_langfuse_trace_id"), "answer_evaluations", ["langfuse_trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_answer_evaluations_langfuse_trace_id"), table_name="answer_evaluations")
    op.drop_index("ix_answer_evaluations_flagged_created", table_name="answer_evaluations")
    op.drop_table("answer_evaluations")
