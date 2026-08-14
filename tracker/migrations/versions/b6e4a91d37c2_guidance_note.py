"""guidance_note — generated task guidance, pinned to the prompt that produced it

§21 adds an explanation of *how* to carry out a recommended task. §21.5 stores each answer
rather than caching it in memory, for the reason §6.10 already stores ``reason``, ``factors``
and ``bands``: a rendered claim must not drift from the run that produced it. An in-memory
cache also dies on restart, and a restart followed by a page reload is then a fresh paid call
for advice the user already has.

**The unique constraint is the cache.** ``(player_id, candidate_id, context_hash)`` — a
repeat click on an unchanged account finds the existing row and never reaches the provider.
§21.6 checks that lookup *before* any throttle, so re-reading advice is never rate limited.

**Nothing is back-filled and no other table is touched.** D14 makes guidance a terminal
output: an install that never enables the feature has an empty table and behaves identically
to one without it, which is why this migration adds a table and nothing else.

Revision ID: b6e4a91d37c2
Revises: f3b7c1d29a54
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from tracker.db.types import UtcDateTime

revision = "b6e4a91d37c2"
down_revision = "f3b7c1d29a54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guidance_note",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        # sha256 over the schema version, §21.3's instruction block and the rendered context.
        sa.Column("context_hash", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        # The model that wrote this, for §15's attribution. Stored, never re-read from config:
        # a note written by one model must not be relabelled with whatever is configured now.
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("generated_at", UtcDateTime(), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["player.id"],
            name=op.f("fk_guidance_note_player_id_player"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guidance_note")),
        sa.UniqueConstraint(
            "player_id", "candidate_id", "context_hash", name="uq_guidance_note_context"
        ),
    )
    op.create_index(
        "ix_guidance_note_player_candidate",
        "guidance_note",
        ["player_id", "candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_guidance_note_player_candidate", table_name="guidance_note")
    op.drop_table("guidance_note")
