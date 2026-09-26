"""Retire recommendation persistence after factual runtime consumers have moved.

Revision ID: 7c9a4e10d2f6
Revises: e2f8a34b91c7

The removed tables contain generated recommendations, utility state, advisor history,
practice events, and milestones. The three removed item_price columns are persisted
outputs of the former price selection run; all raw observations and provenance survive.
The player.gp_sensitivity preference is retained even though current factual services
do not use it.

This is an intentionally destructive forward migration. Before applying it to a live
SQLite database, stop writers and make a verified SQLite backup (the backup API handles
WAL state). Restoring that backup is the rollback path. A schema-only downgrade could
recreate empty tables but could not recover the discarded user and history rows.
"""

from __future__ import annotations

from alembic import op

revision = "7c9a4e10d2f6"
down_revision = "e2f8a34b91c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dependents before parents; account and price fact tables are untouched.
    op.drop_table("advisor_message")
    op.drop_table("advisor_conversation")
    op.drop_table("guidance_note")
    op.drop_table("recommendation_entry")
    op.drop_table("recommendation_snapshot")
    op.drop_table("capability_state")
    op.drop_table("active_roadmap")
    op.drop_table("practice_event")
    op.drop_table("milestone")

    with op.batch_alter_table("item_price") as batch_op:
        batch_op.drop_column("selection_reason")
        batch_op.drop_column("selection_policy")
        batch_op.drop_column("selected_price_gp")


def downgrade() -> None:
    raise RuntimeError(
        "M3 retirement deletes persisted rows; restore the verified pre-M3 SQLite backup "
        "rather than attempting a lossy schema-only downgrade"
    )
