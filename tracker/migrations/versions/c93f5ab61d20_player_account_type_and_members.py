"""player.account_type and player.members — §4.2's account mode

Both **nullable, with no default**, and that is the whole design.

The plan this implements called for ``account_type`` to default to ``"main"``. That would
have asserted the exact fact whose absence is the bug: an ironman cannot buy a Voidwaker at
any price, and a column defaulting to ``main`` states that every unasked account can. §4.5's
rule is that absence of evidence is not evidence, and the plan already applied it to
``members`` ("*``null`` must make the leaf unknown, not unsatisfied*") — the same argument
holds one column to the left.

``NULL`` therefore means *nobody has said*, which the evaluator resolves to ``unknown``. An
unknown gate does not block (§10.6, G3), so a main who never opens Settings loses nothing
while an ironman who answers once stops being told to buy things.

Neither field comes from the plugin: payload v1 has no place for them and this migration
deliberately does not add one. The UI writes them.

Revision ID: c93f5ab61d20
Revises: a1c7e2f04b93
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c93f5ab61d20"
down_revision = "a1c7e2f04b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("player", sa.Column("account_type", sa.String(), nullable=True))
    op.add_column("player", sa.Column("members", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("player", "members")
    op.drop_column("player", "account_type")
