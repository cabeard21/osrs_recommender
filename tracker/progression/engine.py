"""The progression engine: requirement trees in, :class:`CapabilityView`s out (§9.2).

§4.4 splits capability state into three layers, and §9.2 fixes the direction information
may travel between them::

    requirement tree  ──►  status
                              └──►  readiness_confidence   (only when status = unlocked)
                                          └──►  recommended_now

This module is written so those arrows are the only paths that exist:

* ``status`` comes from :mod:`tracker.progression.evaluate` alone. Freshness is not an
  input to it and is not in scope when it is computed — **G2**, and the reason D8 exists.
* ``readiness_confidence`` is computed **only** in the ``unlocked`` branch, so an unknown
  requirement stops at ``status`` and can never produce §6.9's incoherent pair *"Unlocked:
  yes / Confidence: low because ownership is unknown"* — **G3**.
* ``recommended_now`` compares the confidence against the capability's declared bar. It
  is the only layer allowed to be conservative, and it never reaches back (§4.4).
* ``warnings`` are generated last, from the same values, and are never an input to any of
  them (§6.9).

Everything is derived from the leaves that §6.9 calls **contributing** — those reached by
the transitive requirement walk that evaluated ``satisfied``. A losing branch of an
``any_of`` never affects readiness, so a Voidwaker last seen in a year-old bank scan
cannot drag down a capability the player satisfied through their Armadyl godsword.

Pure by construction (§16.1): the account arrives as a :class:`PlayerState`, the corpus as
:class:`Content`, the tuning knobs as :class:`ScoringProfile`, and the clock as ``now``.
No database, no HTTP, no ``datetime.now()``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from tracker.content.loader import Content
from tracker.content.schema import Capability, ScoringProfile
from tracker.domain.types import (
    CapabilityView,
    Confidence,
    Container,
    Freshness,
    LeafRef,
    MilestoneClass,
    PlayerState,
    Status,
    Tri,
)
from tracker.freshness.policy import classify_age, freshness
from tracker.progression.evaluate import EvalResult, Evaluator

#: §6.9's tri-valued status, one arm per ``Tri`` member. A mapping rather than a chain of
#: conditionals so that no arm can be forgotten.
_STATUS_OF: Mapping[Tri, Status] = {
    Tri.SATISFIED: Status.UNLOCKED,
    Tri.UNSATISFIED: Status.LOCKED,
    Tri.UNKNOWN: Status.UNKNOWN,
}

#: Which blocker §6.9's *"names the highest-value blocker"* should name.
#:
#: True value ranking needs hours and GP, which live in the estimation subsystem — a
#: layer that depends on *this* one (Step 5 depends on Step 4), so importing it here
#: would be a cycle as well as a purity violation. The stand-in is structural: a locked
#: prerequisite capability subsumes a whole subtree and is the most informative thing to
#: name, then the gates in roughly descending effort. Ties break on the highest target
#: (``94 Magic`` before ``75 Defence``) and then on the key, so the prose is stable
#: across runs.
_BLOCKER_PRIORITY: Mapping[str, int] = {
    "capability": 0,
    "skill": 1,
    "quest": 2,
    "unlock": 3,
    "item": 4,
    "milestone": 5,
    "combat_level": 6,
    "quest_points": 7,
}

#: The order §6.9's unknown-evidence prose prefers to name containers in. Bank first
#: because it is both the largest and the one §4.4's worked example names.
_CONTAINER_PROSE_ORDER: tuple[Container, ...] = (
    Container.BANK,
    Container.INVENTORY,
    Container.EQUIPMENT,
)

_REFRESHER_REASON = "complete a refresher session first"


@dataclass(frozen=True, slots=True)
class _Context:
    """The four pure inputs, bundled so the generators below stay readable."""

    state: PlayerState
    content: Content
    profile: ScoringProfile
    now: datetime


@dataclass(frozen=True, slots=True)
class _Sighting:
    """The freshest scan backing a satisfied ``item:`` leaf.

    ``seen_at`` is the :class:`~tracker.domain.types.ContainerScan` time §6.9 measures
    against, falling back to the observation's own timestamp when no scan is recorded for
    that container — the observation must have come from somewhere.
    """

    container: Container
    seen_at: datetime


def compute_capability_states(
    state: PlayerState,
    content: Content,
    profile: ScoringProfile,
    now: datetime,
) -> dict[str, CapabilityView]:
    """Compute §6.9's ``CapabilityState`` for every declared capability.

    One :class:`Evaluator` serves the whole run, so a capability required by three others
    is evaluated once (§4.1's DAG). Results are keyed and iterated in id order to make the
    output stable for snapshot diffs and golden-corpus tests (§16.1).
    """
    evaluator = Evaluator(state, content)
    context = _Context(state=state, content=content, profile=profile, now=now)
    return {
        capability_id: _view(content.capabilities[capability_id], evaluator, context)
        for capability_id in sorted(content.capabilities)
    }


def _view(capability: Capability, evaluator: Evaluator, context: _Context) -> CapabilityView:
    """The three layers of §4.4, in the order §9.2 requires and no other."""
    result = evaluator.capability(capability.id)
    status = _STATUS_OF[result.value]

    # Layer 2 exists only under `unlocked` (G3). Not "computed and then discarded" —
    # never computed, so there is no value for a later edit to accidentally surface.
    readiness = _readiness(result.contributing, context) if status is Status.UNLOCKED else None

    recommended_now = readiness is not None and readiness >= capability.recommended_readiness

    return CapabilityView(
        capability_id=capability.id,
        status=status,
        unlock_fraction=result.unlock_fraction,
        blockers=result.blockers,
        unknowns=result.unknowns,
        readiness_confidence=readiness,
        warnings=_warnings(result.contributing, context),
        recommended_now=recommended_now,
        recommended_now_reason=_reason(capability, status, readiness, result, context),
    )


# ---------------------------------------------------------------------------
# Layer 2 — readiness confidence (§6.9)
# ---------------------------------------------------------------------------


def _readiness(contributing: Iterable[LeafRef], context: _Context) -> Confidence:
    """§6.9's confidence table over the contributing leaves.

    * ``high`` — all contributing execution milestones ``current``, and all contributing
      positive observations fresh.
    * ``medium`` — ≥1 contributing execution milestone ``stale``, **or** a contributing
      observation aged.
    * ``low`` — ≥1 contributing execution milestone ``very_stale``.

    Implemented as a floor that only ever descends, so the worst contributing evidence
    decides — one ``very_stale`` milestone gives ``low`` however much fresh evidence sits
    beside it. ``knowledge`` and ``threshold`` milestones cannot appear in this
    computation at all: :func:`~tracker.freshness.policy.freshness` returns ``None`` for
    them, which is §6.6's *"never affects readiness"* enforced at the only place it could
    be violated.
    """
    confidence = Confidence.HIGH
    for ref in contributing:
        match ref.leaf_type:
            case "milestone":
                match _practice_freshness(ref.key, context):
                    case Freshness.VERY_STALE:
                        confidence = min(confidence, Confidence.LOW)
                    case Freshness.STALE:
                        confidence = min(confidence, Confidence.MEDIUM)
                    case Freshness.CURRENT | None:
                        pass
            case "item":
                sighting = _sighting(ref, context)
                if sighting is not None and _is_aged(sighting.seen_at, context):
                    confidence = min(confidence, Confidence.MEDIUM)
    return confidence


def _practice_freshness(milestone_key: str, context: _Context) -> Freshness | None:
    """Freshness of one milestone, or ``None`` where §6.6 says freshness does not apply."""
    observed = context.state.milestones.get(milestone_key)
    if observed is None:  # pragma: no cover — a contributing leaf implies an achieved row
        return None
    return freshness(observed.last_practiced_at, context.now, observed.class_)


def _sighting(ref: LeafRef, context: _Context) -> _Sighting | None:
    """The most recent scan that supports a satisfied ``item:`` leaf.

    *Most recent*, because holding an item in equipment seen an hour ago is fresh
    evidence regardless of how long ago the bank was last opened. Taking the oldest
    supporting container would penalise players for owning more than one of something.

    ``None`` means *no age could be established*, which never downgrades anything (G6).
    The first two guards cannot fire for a contributing leaf — it would not be satisfied
    without a matched observation — and are here so the function is total.
    """
    item = context.content.items.get(ref.key)
    if item is None or item.item_id is None:  # pragma: no cover — defensive
        return None
    observation = context.state.observed_items.get(item.item_id)
    if observation is None:  # pragma: no cover — defensive
        return None

    sightings = [
        _Sighting(
            container=container,
            seen_at=context.state.container_scans.get(container, observation.observed_at),
        )
        for container in observation.containers
    ]
    if not sightings:
        return None
    return max(sightings, key=lambda sighting: sighting.seen_at)


def _is_aged(seen_at: datetime, context: _Context) -> bool:
    """A4: aged means ``now − scanned_at > observation_aged_days`` (default 14).

    The threshold is a scoring-profile value, not a constant here, because it is a tuning
    knob rather than a fact about the game (§9.7, §10.8).
    """
    return context.now - seen_at > timedelta(days=context.profile.observation_aged_days)


# ---------------------------------------------------------------------------
# Layer 3 — recommendation reason (§6.9, A10)
# ---------------------------------------------------------------------------


def _reason(
    capability: Capability,
    status: Status,
    readiness: Confidence | None,
    result: EvalResult,
    context: _Context,
) -> str | None:
    """§6.9's three reason cases, in priority order. ``None`` when nothing is wrong.

    Ordering matters: a capability that is both unknown and below its readiness bar
    should say what is unobserved, not suggest practice for something we cannot confirm
    it can do.
    """
    if status is Status.UNKNOWN:
        return _unknown_reason(result.unknowns, context)
    if status is Status.LOCKED:
        return _locked_reason(result.blockers)
    if readiness is not None and readiness < capability.recommended_readiness:
        return _REFRESHER_REASON
    return None


def _unknown_reason(unknowns: tuple[LeafRef, ...], context: _Context) -> str:
    """Name the unknown evidence — *"bank contents have never been observed"* (§4.4)."""
    if not unknowns:  # pragma: no cover — an unknown result always carries an unknown leaf
        return "some requirements have never been observed"
    ref = unknowns[0]
    match ref.leaf_type:
        case "item":
            return _unobserved_container_prose(context)
        case "skill":
            skill = context.content.skills.get(ref.key)
            name = skill.name if skill is not None else ref.key
            return f"your {name} level has never been observed"
        case "unlock":
            return f"whether you have {ref.description} has never been observed"
        case "quest":
            return f"your progress in {ref.description} has never been observed"
        case "milestone":
            return f"you have never been asked about {ref.description.lower()}"
        case "capability":
            return f"{ref.description} is itself unknown"
        case "combat_level" | "quest_points":
            return "this account has never been synced"
        case _:  # pragma: no cover — every leaf type of §10.2 is covered above
            return f"{ref.description} has never been observed"


def _unobserved_container_prose(context: _Context) -> str:
    """§6.5's phrasing: name the container we have never looked in, not the item.

    *"bank contents have never been observed"* — never *"you don't have a Voidwaker"*.
    """
    for container in _CONTAINER_PROSE_ORDER:
        if container not in context.state.container_scans:
            return f"{container.value} contents have never been observed"
    # Every container scanned, yet the leaf is unknown: the item carries no numeric id,
    # so no observation could ever refer to it (§10.5).
    return "this item cannot be matched to an in-game item id"


def _locked_reason(blockers: tuple[LeafRef, ...]) -> str:
    """Name the highest-value blocker — *"requires 94 Magic"* (§6.9)."""
    if not blockers:
        # Reachable only through `not`, whose unsatisfied form has no LeafRef vocabulary
        # (see `Evaluator._not`).
        return "its requirements are not met"
    return f"requires {min(blockers, key=_blocker_rank).description}"


def _blocker_rank(ref: LeafRef) -> tuple[int, int, str]:
    return (
        _BLOCKER_PRIORITY.get(ref.leaf_type, len(_BLOCKER_PRIORITY)),
        -(ref.target or 0),
        ref.key,
    )


# ---------------------------------------------------------------------------
# Warnings (§6.9, A11)
# ---------------------------------------------------------------------------


def _warnings(contributing: Iterable[LeafRef], context: _Context) -> tuple[str, ...]:
    """§6.9's three warning generators.

    1. Contributing ``execution`` milestones that are ``stale`` or ``very_stale``.
    2. Contributing observations that are aged — phrased as observation *age*, never as
       absence (§6.5).
    3. An informational staleness note on ``class: knowledge`` milestones, which §6.6
       permits while forbidding any readiness effect. This is the only place such a
       milestone may appear, and it appears here *because* it appears nowhere in
       :func:`_readiness`.

    Warnings explain a computed result; they are never an input to one. Nothing in this
    function's output is read back by any layer above.
    """
    milestone_notes: list[str] = []
    aged_containers: dict[Container, datetime] = {}

    for ref in contributing:
        match ref.leaf_type:
            case "milestone":
                note = _milestone_warning(ref, context)
                if note is not None:
                    milestone_notes.append(note)
            case "item":
                sighting = _sighting(ref, context)
                if sighting is None or not _is_aged(sighting.seen_at, context):
                    continue
                # One warning per container, not per item: three aged items in the same
                # bank scan are one fact about the bank.
                previous = aged_containers.get(sighting.container)
                if previous is None or sighting.seen_at < previous:
                    aged_containers[sighting.container] = sighting.seen_at

    observation_notes = [
        f"last saw your {container.value} {_humanize(context.now - aged_containers[container])} ago"
        for container in _CONTAINER_PROSE_ORDER
        if container in aged_containers
    ]
    return (*milestone_notes, *observation_notes)


def _milestone_warning(ref: LeafRef, context: _Context) -> str | None:
    observed = context.state.milestones.get(ref.key)
    if observed is None or observed.last_practiced_at is None:
        return None
    age = _humanize(context.now - observed.last_practiced_at)

    band = freshness(observed.last_practiced_at, context.now, observed.class_)
    match band:
        case Freshness.STALE | Freshness.VERY_STALE:
            return (
                f"{ref.description} was last practiced {age} ago ({band.value.replace('_', ' ')})"
            )
        case Freshness.CURRENT:
            return None
        case None:
            pass

    # §6.6 permits an informational note on knowledge milestones and forbids any
    # readiness effect. `freshness` returned None for this class, so the note has to
    # reach for the band table directly — which is why `classify_age` is separate.
    if observed.class_ is not MilestoneClass.KNOWLEDGE:
        return None
    if classify_age(context.now - observed.last_practiced_at) is Freshness.CURRENT:
        return None
    return (
        f"{ref.description} was last practiced {age} ago "
        "(informational — knowledge milestones never affect readiness)"
    )


def _humanize(age: timedelta) -> str:
    """Observation age as §6.5's UI phrases it — *"3 weeks"*, not a timestamp."""
    days = max(int(age.total_seconds() // 86_400), 0)
    if days < 1:
        return "less than a day"
    if days < 14:
        return _plural(days, "day")
    if days < 60:
        return _plural(days // 7, "week")
    return _plural(days // 30, "month")


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
