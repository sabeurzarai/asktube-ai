"""transcript chunks with pgvector

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Matches text-embedding-3-small. Changing the embedding provider changes this
# number, which requires a new migration plus a full re-ingest — the same
# constraint CLAUDE.md already documents for the Chroma setup.
EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.create_table(
        "transcript_chunks",
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column("video_id", sa.Text(), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("segment_indices", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "create index ix_transcript_chunks_embedding on transcript_chunks "
        "using hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_chunks_embedding", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
