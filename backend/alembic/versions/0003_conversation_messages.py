"""conversation messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Covers both operations: reading the newest N for a session, and finding the
    # rows to trim. Ordering is by id, never created_at — see the design spec.
    op.create_index(
        "ix_conversation_messages_session",
        "conversation_messages",
        ["session_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_session", table_name="conversation_messages")
    op.drop_table("conversation_messages")
