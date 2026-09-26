"""SQLAlchemy account facts, raw market prices, and sync audit models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tracker.db.types import UtcDateTime
from tracker.domain.types import (
    Container,
    GpSensitivity,
    PriceSourceLayer,
    QuestStatus,
    Source,
    UnlockState,
)

#: Alembic autogenerate needs deterministic names for every constraint and index to emit
#: correct ``op.drop_constraint(...)`` calls in downgrades; without this, unnamed
#: constraints get dialect-generated names that differ between the model and a later
#: reflection pass. This is the naming convention Alembic's own docs recommend.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with aware UTC timestamp and named-constraint defaults."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
    # ``ClassVar`` is required, not cosmetic: the declarative machinery maps every other
    # annotated class attribute to a column, and ``ClassVar`` is the documented opt-out.
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UtcDateTime()}


def _enum_column(enum_cls: type[Enum]) -> sa.Enum:
    """Store enum member names as lowercase strings for stable SQLite values."""
    return sa.Enum(
        enum_cls, values_callable=lambda members: [member.name.lower() for member in members]
    )


# ---------------------------------------------------------------------------
# §6.1 Player
# ---------------------------------------------------------------------------


class Player(Base):
    """§6.1. Multi-character is supported by the schema from v1; the UI may expose one."""

    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Hiscores/WOM lookup key (§6.1). Unique — two rows for the same account make every
    #: downstream sync ambiguous about which player the observation belongs to.
    username: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str]
    created_at: Mapped[datetime]
    #: Nullable — ``NULL`` before the first sync. Drives the ``combat_level``/
    #: ``quest_points`` leaves' ``unknown`` resolution (§9.1: "account never synced").
    last_sync_at: Mapped[datetime | None] = mapped_column(default=None)
    #: Nullable for the same reason as ``last_sync_at`` — unobserved before first sync.
    combat_level: Mapped[int | None] = mapped_column(default=None)
    quest_points: Mapped[int | None] = mapped_column(default=None)
    #: Settings-supplied facts. ``None`` means unobserved, never an assumed main/member.
    account_type: Mapped[str | None] = mapped_column(default=None)
    members: Mapped[bool | None] = mapped_column(default=None)
    gp_sensitivity: Mapped[GpSensitivity] = mapped_column(
        _enum_column(GpSensitivity), default=GpSensitivity.NORMAL
    )


# ---------------------------------------------------------------------------
# §6.2 SkillSnapshot
# ---------------------------------------------------------------------------


class SkillSnapshot(Base):
    """§6.2. History log feeding the §15 XP chart — one row per observation, not per skill.

    ``xp`` is nullable and ``NULL`` means unranked, **never 0** (G5). Hiscores return
    ``-1`` for unranked skills; normalizing that to ``NULL`` is the adapter boundary's job
    (Step 7), not this table's — this column simply must be able to hold the absence.
    """

    __tablename__ = "skill_snapshot"
    __table_args__ = (sa.Index("ix_skill_snapshot_player_id_skill", "player_id", "skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )
    skill: Mapped[str]
    level: Mapped[int]
    xp: Mapped[int | None] = mapped_column(default=None)
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    observed_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# §6.3 Unlock
# ---------------------------------------------------------------------------


class Unlock(Base):
    """§6.3. One row per ``(player_id, key)`` — the current unlock state, overwritten as
    fresher observations arrive. ``key`` also carries the ``spellbook_*`` / ``diary_*`` /
    ``ca_*`` reserved prefixes (A12) — no separate tables for those.

    The composite primary key *is* the ``(player_id, key)`` index the task list asks for;
    SQLite builds an index to enforce a non-integer primary key, so no second index is
    declared here.
    """

    __tablename__ = "unlock"

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    state: Mapped[UnlockState] = mapped_column(_enum_column(UnlockState))
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    observed_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# §6.4 QuestState
# ---------------------------------------------------------------------------


class QuestState(Base):
    """§6.4. One row per ``(player_id, quest_id)`` — current status, overwritten in place."""

    __tablename__ = "quest_state"

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    quest_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[QuestStatus] = mapped_column(_enum_column(QuestStatus))
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    observed_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# §6.5 ObservedItem and ContainerScan
# ---------------------------------------------------------------------------


class ObservedItem(Base):
    """§6.5. One row per ``(player_id, item_id, container)`` — the latest sighting.

    Absence of a row is *not* "not owned" on its own; it is ambiguous with "never
    scanned" until read together with ``ContainerScan`` (§4.5, §6.5's own three-way
    table). That resolution is Step 3b's ``build_player_state`` job, not this table's.

    The composite primary key already is the ``(player_id, item_id, container)`` index
    the task list asks for.
    """

    __tablename__ = "observed_item"

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(primary_key=True)
    container: Mapped[Container] = mapped_column(_enum_column(Container), primary_key=True)
    quantity: Mapped[int]
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    observed_at: Mapped[datetime]


class ContainerScan(Base):
    """§6.5. The staleness anchor — without this, "no ``ObservedItem`` row" is ambiguous
    between "you don't own it" and "we've never looked" (§4.5).

    ``source`` is not in §6.5's own table listing but is added here — see the module
    docstring's "schema-level deviation" note; §6's preamble states *"all tables carry
    provenance"* and this is the one fact table whose subsection forgot to list it.
    """

    __tablename__ = "container_scan"

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    container: Mapped[Container] = mapped_column(_enum_column(Container), primary_key=True)
    #: Last time this container was seen *in full* (§6.5).
    scanned_at: Mapped[datetime]
    source: Mapped[Source] = mapped_column(_enum_column(Source))


# ---------------------------------------------------------------------------
# §6.8 ItemPrice
# ---------------------------------------------------------------------------


class ItemPrice(Base):
    """Raw, globally cached market observations and their provenance."""

    __tablename__ = "item_price"

    item_id: Mapped[int] = mapped_column(primary_key=True)
    high_price_gp: Mapped[int | None] = mapped_column(default=None)
    #: When that trade occurred — distinct from ``fetched_at`` (§4.5, §8.4).
    high_trade_at: Mapped[datetime | None] = mapped_column(default=None)
    low_price_gp: Mapped[int | None] = mapped_column(default=None)
    low_trade_at: Mapped[datetime | None] = mapped_column(default=None)
    provider: Mapped[str]
    #: When *we* called the API — not when the trade happened (§4.5, §8.4).
    fetched_at: Mapped[datetime]
    source: Mapped[PriceSourceLayer] = mapped_column(_enum_column(PriceSourceLayer))


# ---------------------------------------------------------------------------
# §6.11 SyncEvent
# ---------------------------------------------------------------------------


class SyncEvent(Base):
    """§6.11, A17. Audit trail for plugin/app version drift *and* rejected requests.

    ``player_id`` is nullable and ``ondelete="SET NULL"`` — an unauthenticated caller has
    no trusted identity, so a rejected request is recorded with ``player_id = NULL``
    rather than either dropping the audit row (defeats §11.3) or trusting an
    attacker-supplied id (writes attacker-controlled data into the audit trail). The
    audit row must also outlive the player it names: deleting a ``Player`` sets this
    column ``NULL`` instead of cascading the delete into the audit log.
    """

    __tablename__ = "sync_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("player.id", ondelete="SET NULL"), default=None
    )
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    #: Nullable — absent or unparseable on malformed requests (§6.11).
    payload_version: Mapped[int | None] = mapped_column(default=None)
    remote_addr: Mapped[str | None] = mapped_column(default=None)
    received_at: Mapped[datetime]
    accepted: Mapped[bool]
    #: Why a request was rejected (§6.11, §11.3) — nullable, populated only on rejection.
    reason: Mapped[str | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(default=None)
