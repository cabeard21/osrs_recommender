"""recommendation_entry.bands — §8.2's per-band breakdown, persisted

The estimator has always picked a method per band (``BandEstimate.method_id``) and the
persistence layer has always thrown it away, so §15's "How" line had nothing to render.
This adds the column that closes that gap.

**One JSON column, not five scalars.** A candidate has a variable number of bands — Magic
87→94 is one, 70→99 is three — so scalars would mean either a child table for something
never queried across rows, or a lossy "first band wins". ``RecommendationEntry.factors``
already establishes JSON as the shape for per-entry structured detail.

``server_default="[]"`` rather than nullable: an entry with no bands is an empty list, not
an unknown one. Every existing row was written by an engine that computed bands and
discarded them, so backfilling ``NULL`` would invent a distinction ("we do not know
whether this had bands") that never existed in the data.

Revision ID: a1c7e2f04b93
Revises: bc8475de44e9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1c7e2f04b93"
down_revision = "bc8475de44e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain add_column: SQLite supports ADD COLUMN with a constant default, so no
    # batch_alter_table (table rebuild) is needed here.
    op.add_column(
        "recommendation_entry",
        sa.Column("bands", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("recommendation_entry", "bands")
