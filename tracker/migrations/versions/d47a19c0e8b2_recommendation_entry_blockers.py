"""recommendation_entry.blockers — why a blocked entry is blocked

§15's Blocked section named a candidate and nothing else, so "Complete Lunar Diplomacy —
blocked" gave a reader a goal with no path. The Capabilities page has shown blockers since
it was built; the Recommendations page never did.

**Persisted rather than re-derived, for the reason ``bands`` is.** A gate's unsatisfied
leaves are a function of the account's facts *at the time of the run*, and a snapshot
accumulates (§6.10) — re-evaluating on read would relabel a historical entry with today's
facts, which is the same drift argument that makes ``reason`` a stored string.

``server_default="[]"``: an entry with no blockers has none, which is not the same as
unknown. Every existing row was written before candidates carried them, and an actionable
entry legitimately has an empty list.

Revision ID: d47a19c0e8b2
Revises: c93f5ab61d20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d47a19c0e8b2"
down_revision = "c93f5ab61d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendation_entry",
        sa.Column("blockers", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("recommendation_entry", "blockers")
