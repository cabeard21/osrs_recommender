"""recommendation_entry.consequences — what a recommended entry is actually *for*

§9.10's "Why" line said how a candidate scored — *"quick to finish (+0.61) · early progress
(+0.30)"* — and never what doing it would achieve. For the generated skill bands that is not
a wording problem but a missing derivation: ``tools/generate_candidates.py`` gives every band
``advances: {}``, so no §9.4 factor carries a goal for it and the chain that explains it
("Slayer 10 gates Desert Treasure I, which advances Ice Barrage NH") was computed nowhere.

This column stores that chain: what the entry unblocks, what it is needed for, which goals it
moves, and which grind it shortens.

**Persisted rather than recomputed on read, for ``blockers``' reason and one sharper.** A
consequence is a fact about the account *at the time of the run*: "unblocks Desert Treasure
I" stops being true the moment the quest is done, so re-deriving it on read would relabel a
historical entry with today's facts — the drift argument that already makes ``reason`` a
stored string. Content moves too, and a capability whose ``requires`` was edited between runs
could make a live recompute claim an unblock that never happened.

``server_default="{}"``: an entry with no consequences has none, which is not the same as
unknown. Every existing row was written before the engine derived them, and an entry that
genuinely had nothing to say — one that ranked on cheapness alone — legitimately records the
empty object. Neither case may be back-filled with invented prose.

Revision ID: f3b7c1d29a54
Revises: d47a19c0e8b2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3b7c1d29a54"
down_revision = "d47a19c0e8b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendation_entry",
        sa.Column("consequences", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("recommendation_entry", "consequences")
