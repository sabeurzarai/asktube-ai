"""initial analytics schema

Revision ID: 0001
Revises:
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON_VARIANT = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("session_id", sa.String(120), nullable=True, index=True),
        sa.Column("user_id", sa.String(120), nullable=True, index=True),
        sa.Column("page", sa.String(240), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "video_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.String(40), nullable=False, index=True),
        sa.Column("processing_time", sa.Float(), nullable=False),
        sa.Column("transcript_time", sa.Float(), nullable=False),
        sa.Column("embedding_time", sa.Float(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("whisper_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "chat_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(120), nullable=False, index=True),
        sa.Column("questions_count", sa.Integer(), nullable=False),
        sa.Column("avg_response_time", sa.Float(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False),
        sa.Column("followup_questions", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )
    op.create_table(
        "rag_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("retrieval_latency", sa.Float(), nullable=False),
        sa.Column("generation_latency", sa.Float(), nullable=False),
        sa.Column("chunks_retrieved", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("citation_coverage", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("context_tokens", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("response_length", sa.Integer(), nullable=False),
        sa.Column("hallucination_warning", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", JSON_VARIANT, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rag_metrics")
    op.drop_table("chat_metrics")
    op.drop_table("video_metrics")
    op.drop_table("analytics_events")
