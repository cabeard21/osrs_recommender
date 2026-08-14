"""§22.6 — advisor conversations and messages.

**Two new tables and nothing else**, and that is worth stating in the migration rather than
only in the model docstrings. D14 makes advisor output terminal: if this revision altered a
column on ``recommendation_entry``, ``capability_state`` or ``item_price``, the feature would
have acquired a route into the engine's own data at exactly the layer where such a route is
hardest to notice. The absence of any ``alter_`` call here is part of that guarantee, and the
downgrade is a clean drop for the same reason — removing the advisor leaves an install byte
identical to one that never had it.

Revision ID: e2f8a34b91c7
Revises: b6e4a91d37c2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f8a34b91c7"
down_revision = "b6e4a91d37c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "advisor_conversation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("digest_hash", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_advisor_conversation_player_updated",
        "advisor_conversation",
        ["player_id", "updated_at"],
    )

    op.create_table(
        "advisor_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        # Stored as its value string, matching how every other enum column in this schema is
        # persisted. Two members only — a tool call is not a message (D16).
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("uncertain", sa.JSON(), nullable=True),
        # Names, arguments and result sizes. Never results — D16.
        sa.Column("tool_trace", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("digest_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["advisor_conversation.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # A thread's ordering is data, not an artefact of insertion order: the messages are
        # replayed into a prompt, and two rows sharing an ordinal would replay ambiguously.
        sa.UniqueConstraint("conversation_id", "ordinal", name="uq_advisor_message_ordinal"),
    )
    op.create_index(
        "ix_advisor_message_conversation", "advisor_message", ["conversation_id", "ordinal"]
    )


def downgrade() -> None:
    op.drop_index("ix_advisor_message_conversation", table_name="advisor_message")
    op.drop_table("advisor_message")
    op.drop_index("ix_advisor_conversation_player_updated", table_name="advisor_conversation")
    op.drop_table("advisor_conversation")
