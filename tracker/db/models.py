"""SQLAlchemy 2.0 models for every table in SDD §6, plus amendments A12/A13/A17/A18.

This module is the *storage* projection of §6, not the engine's view of the account —
that is ``tracker.domain.types.PlayerState``, built from these tables by
``tracker.db.projection`` (Step 3b). The engine never queries the database (§16.1); it
only ever sees the frozen dataclasses in ``tracker.domain``. Nothing here should leak
into ``tracker/progression/``, ``tracker/recommendations/`` or ``tracker/estimation/`` —
that boundary is enforced by ``tests/progression/test_import_boundary.py`` (Step 4).

## Which tables get a surrogate ``id`` and which get a composite key

§6's own table listings are the tie-breaker here. Where a table's SDD listing shows an
explicit ``id | int PK`` row (``Player``, ``SkillSnapshot``, ``PracticeEvent``,
``RecommendationSnapshot``, ``SyncEvent``), that is because the row is one entry in a
growing history or audit log — ``SkillSnapshot`` feeds the §15 History XP chart,
``PracticeEvent`` is an immutable evidence log, ``RecommendationSnapshot`` exists so two
runs can be diffed (§6.10), ``SyncEvent`` is an audit trail (§6.11) — and a synthetic key
is the only sane identity for a log row.

Every other table's SDD listing omits ``id`` entirely, and reading §6 closely shows why:
those tables hold *the current value of a fact* (``Unlock.state``, ``Milestone.achieved``,
``CapabilityState.status``, ...), addressed by their natural key and overwritten in place
as new observations arrive — never accumulated. §6.6 says outright that ``achieved`` is
"never set back to false by the passage of time", which only makes sense as a statement
about a single mutable row. This module therefore gives those tables a composite primary
key on their natural key (``player_id`` plus whatever the fact is keyed by) instead of
inventing an ``id`` column the SDD never lists. It also means the composite-key indexes
Step 3a's task list calls for on ``Unlock``, ``Milestone`` and ``ObservedItem`` — all
``(player_id, key-ish-column...)`` — are exactly the primary key SQLite already builds an
index for; a second, redundant index is not added on top of it, only noted at each class.

## A schema-level deviation from §6's literal table text

§6's preamble states plainly: *"All tables carry provenance."* Every fact table's own
listing honours that except ``ContainerScan`` (§6.5), whose table shows only
``player_id``, ``container`` and ``scanned_at`` — no ``source``. A container scan is
exactly as much an observed fact as an ``ObservedItem`` row (today it can only come from
RuneLite, but nothing in the schema should assume that stays true forever), so this
module adds ``ContainerScan.source`` to make the preamble's own rule hold everywhere. This
is the same category of gap A17/A18 already closed elsewhere in §6 — a rule stated once
at the top that one subsection's table forgot to carry through — and is called out in the
step 3a commit rather than silently "fixed".

## Enum storage

Every ``Mapped[SomeDomainEnum]`` column stores a lowercase string (``"runelite"``, not
``"RUNELITE"``) via ``_enum_column``'s ``values_callable`` — see that function's docstring
for why this is ``member.name.lower()`` rather than ``member.value`` (short version:
``Confidence`` is an ``IntEnum``, and ``sa.Enum`` cannot use its integer ``.value`` as a
column string). The on-disk result is the same string the SDD's own tables print either way.

A few columns use enums that live in ``tracker.db.enums`` instead of ``tracker.domain.types``
— see that module's docstring for why: they describe storage/provenance concerns particular
tables define with their own value sets (§6.7's two-valued ``confidence``, §6.8's price cascade
layer, §6.10's ``candidate_kind``), not vocabulary the engine reasons over.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tracker.db.enums import (
    PracticeEventConfidence,
    PriceSelectionPolicy,
    PriceSourceLayer,
    RecommendationCandidateKind,
)
from tracker.domain.types import (
    Confidence,
    Container,
    Freshness,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    PracticeDomain,
    QuestStatus,
    Source,
    Status,
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
    """Declarative base. ``tracker/migrations/env.py`` targets ``Base.metadata``."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def _enum_column(enum_cls: type[Enum]) -> sa.Enum:
    """Build an ``Enum`` column type that stores lowercase member names as strings.

    Every enum in ``tracker.domain.types`` and ``tracker.db.enums`` follows the
    convention ``MEMBER.value == MEMBER.name.lower()`` — except ``Confidence``, which is
    an ``IntEnum`` (``LOW = 0`` ...) so that ``recommended_now`` can compare it against a
    threshold (A9). Storing ``.value`` directly would therefore store integers for every
    other enum's sibling column but the string ``"0"``/``"1"``/``"2"`` is not even what
    ``.value`` gives you for an ``IntEnum`` passed through ``sa.Enum`` — it raises, since
    ``sa.Enum`` assumes string-valued members. ``.name.lower()`` sidesteps the distinction
    entirely and produces the same on-disk string (``"low"``, ``"runelite"``, ...) for
    every enum in this schema.
    """
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
# §6.6 Milestone
# ---------------------------------------------------------------------------


class Milestone(Base):
    """§6.6. One row per ``(player_id, key)`` — current milestone state.

    ``class`` is a Python keyword, so the mapped attribute is ``class_``; the column
    itself is still literally named ``class`` in SQLite (§6.6's own spelling).

    ``attested_at IS NULL`` means never prompted — a different fact from "asked and
    declined" (§4.5, §6.6). ``achieved`` must never be written back to ``False`` once
    true (§6.6) — that invariant is enforced by whoever writes this table (Step 3b/9),
    not by a database constraint, because SQLite has no clean way to express "this
    column may only transition false -> true".

    ``freshness`` is a real column per A18, materialized by Step 9's freshness pipeline
    from ``last_practiced_at``; it is never authoritative and may be rebuilt at any time
    (§6.6), so it carries no default and no constraint tying it to ``last_practiced_at``.
    """

    __tablename__ = "milestone"

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[MilestoneKind] = mapped_column(_enum_column(MilestoneKind))
    class_: Mapped[MilestoneClass] = mapped_column("class", _enum_column(MilestoneClass))
    achieved: Mapped[bool] = mapped_column(default=False)
    value: Mapped[int | None] = mapped_column(default=None)
    attested_at: Mapped[datetime | None] = mapped_column(default=None)
    last_practiced_at: Mapped[datetime | None] = mapped_column(default=None)
    freshness: Mapped[Freshness | None] = mapped_column(_enum_column(Freshness), default=None)
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    observed_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# §6.7 PracticeEvent
# ---------------------------------------------------------------------------


class PracticeEvent(Base):
    """§6.7. Immutable evidence log — integrations append rows; only the freshness
    service (Step 9) reads them and maps them onto milestones (§7.6). Client-side
    detection logic never touches ``Milestone`` rows directly.

    The mapped attribute is ``event_metadata``, not ``metadata`` — ``metadata`` is a
    reserved attribute name on every SQLAlchemy declarative class (it holds the table
    catalog), so the SDD's own column name would shadow it. The database column is still
    literally named ``metadata``.
    """

    __tablename__ = "practice_event"
    __table_args__ = (
        sa.Index("ix_practice_event_player_id_domain_ended_at", "player_id", "domain", "ended_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[PracticeDomain] = mapped_column(_enum_column(PracticeDomain))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime]
    source: Mapped[Source] = mapped_column(_enum_column(Source))
    confidence: Mapped[PracticeEventConfidence] = mapped_column(
        _enum_column(PracticeEventConfidence)
    )
    #: e.g. ``lms_match_completed``, ``wilderness_player_combat`` (§6.7).
    evidence_type: Mapped[str]
    #: Summarized only (§7.6's collection boundary) — never opponent names, chat, tick-
    #: by-tick location, or individual prayer selections.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", sa.JSON, default=None)


# ---------------------------------------------------------------------------
# §6.8 ItemPrice
# ---------------------------------------------------------------------------


class ItemPrice(Base):
    """§6.8. One row per item, global (not per-player) — prices are shared market facts,
    scoped only by which items the active roadmap references (§8.3's fetch-scope rule),
    which is a query-time concern, not a schema one.

    The provider client (§7.5) writes every column except the three ``selected_*``
    columns; those are the *output* of the §8.3 resolution policy, computed by the
    estimator (Step 5) and persisted by Step 9. They exist here, nullable, with no writer
    yet — that is intentional, not an omission.
    """

    __tablename__ = "item_price"

    item_id: Mapped[int] = mapped_column(primary_key=True)
    high_price_gp: Mapped[int | None] = mapped_column(default=None)
    #: When that trade occurred — distinct from ``fetched_at`` (§4.5, §8.4).
    high_trade_at: Mapped[datetime | None] = mapped_column(default=None)
    low_price_gp: Mapped[int | None] = mapped_column(default=None)
    low_trade_at: Mapped[datetime | None] = mapped_column(default=None)
    #: No writer in Step 3a — see class docstring.
    selected_price_gp: Mapped[int | None] = mapped_column(default=None)
    selection_policy: Mapped[PriceSelectionPolicy | None] = mapped_column(
        _enum_column(PriceSelectionPolicy), default=None
    )
    #: Which cascade layer supplied ``selected_price_gp``, in prose (§6.8).
    selection_reason: Mapped[str | None] = mapped_column(default=None)
    provider: Mapped[str]
    #: When *we* called the API — not when the trade happened (§4.5, §8.4).
    fetched_at: Mapped[datetime]
    source: Mapped[PriceSourceLayer] = mapped_column(_enum_column(PriceSourceLayer))


# ---------------------------------------------------------------------------
# §6.9 CapabilityState
# ---------------------------------------------------------------------------


class CapabilityState(Base):
    """§6.9. Materialized output of the progression engine — one row per
    ``(player_id, capability_id)``, overwritten on every recompute. ``status`` is never
    influenced by freshness (G2); ``readiness_confidence`` is only meaningful when
    ``status = unlocked`` (§9.2's "information flows only downward").
    """

    __tablename__ = "capability_state"
    __table_args__ = (
        sa.CheckConstraint(
            "unlock_fraction >= 0 AND unlock_fraction <= 1", name="unlock_fraction_range"
        ),
    )

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    capability_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[Status] = mapped_column(_enum_column(Status))
    #: ``satisfied_leaves / total_leaves``; unknown leaves sit in the denominator but are
    #: never credited (§6.9).
    unlock_fraction: Mapped[float]
    #: Leaves evaluating to ``unsatisfied`` — "do this" (§6.9).
    blockers: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    #: Leaves evaluating to ``unknown`` — "sync this", not "do this" (§6.9).
    unknowns: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)
    #: ``NULL`` unless ``status = unlocked`` (§9.2) — never a caveat on an unlocked+low
    #: pair that shouldn't exist in the first place.
    readiness_confidence: Mapped[Confidence | None] = mapped_column(
        _enum_column(Confidence), default=None
    )
    warnings: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    recommended_now: Mapped[bool] = mapped_column(default=False)
    recommended_now_reason: Mapped[str | None] = mapped_column(default=None)
    computed_at: Mapped[datetime]


# ---------------------------------------------------------------------------
# §6.10 RecommendationSnapshot / RecommendationEntry
# ---------------------------------------------------------------------------


class RecommendationSnapshot(Base):
    """§6.10. One row per recommendation run — required by the History UI (§15) and by
    engine debuggability: two runs can be diffed to see which factor moved.
    """

    __tablename__ = "recommendation_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )
    run_at: Mapped[datetime]
    #: Which roadmaps and selection weights produced this run — distinct from the *live*
    #: setting in ``ActiveRoadmap`` (§6.12), which may have changed since.
    roadmap_selection: Mapped[dict[str, float]] = mapped_column(sa.JSON)
    scoring_profile_version: Mapped[int]


class RecommendationEntry(Base):
    """§6.10. One row per ranked (or blocked) candidate within a snapshot.

    §6.10's listing has no ``id`` column, unlike its parent ``RecommendationSnapshot`` —
    consistent with this module's rule (see module docstring) that a table without one is
    keyed by its natural identity. Here that is ``(snapshot_id, candidate_id)``: a given
    candidate appears at most once per run, whether ranked or blocked, which ``rank``
    alone cannot guarantee (blocked candidates are "surfaced separately", §9.4, and their
    ``rank`` semantics belong to the engine that populates this table — Step 5/9 — not to
    this schema).
    """

    __tablename__ = "recommendation_entry"

    snapshot_id: Mapped[int] = mapped_column(
        sa.ForeignKey("recommendation_snapshot.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[str] = mapped_column(primary_key=True)
    rank: Mapped[int]
    candidate_kind: Mapped[RecommendationCandidateKind] = mapped_column(
        _enum_column(RecommendationCandidateKind)
    )
    score: Mapped[float]
    #: Per-factor values *and* log-contributions (§9.5) — the "Why" line is generated by
    #: reading off the largest terms here, not authored separately.
    factors: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    reason: Mapped[str]
    estimated_hours: Mapped[float | None] = mapped_column(default=None)
    estimated_gp: Mapped[int | None] = mapped_column(default=None)
    estimate_confidence: Mapped[Confidence] = mapped_column(_enum_column(Confidence))
    blocked: Mapped[bool] = mapped_column(default=False)


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


# ---------------------------------------------------------------------------
# §6.12 ActiveRoadmap (A13)
# ---------------------------------------------------------------------------


class ActiveRoadmap(Base):
    """§6.12, A13. The player's live roadmap selection — distinct from
    ``RecommendationSnapshot.roadmap_selection``, which records what a *past run* used.

    Weights are normalized on **read**, not on write (§6.12, §4.3), so this column stores
    whatever raw weight the user set; removing one roadmap row must not require rewriting
    the others. See ``tracker.domain.types.RoadmapSelection.normalized`` for the read-side
    normalization this table's readers are expected to apply.
    """

    __tablename__ = "active_roadmap"
    __table_args__ = (
        sa.CheckConstraint(
            "selection_weight >= 0 AND selection_weight <= 1", name="selection_weight_range"
        ),
    )

    player_id: Mapped[int] = mapped_column(
        sa.ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    roadmap_id: Mapped[str] = mapped_column(primary_key=True)
    selection_weight: Mapped[float]
