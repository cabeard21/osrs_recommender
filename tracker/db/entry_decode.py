"""Decoding the JSON columns of :class:`~tracker.db.models.RecommendationEntry`.

Both LLM surfaces read the *persisted* entries of the latest run rather than re-ranking —
:mod:`tracker.sync.guidance` for §21 and :mod:`tracker.sync.advisor` for §22, each for the
reason §6.10 gives: the persisted entry is what the user is looking at, and re-deriving it
could hand the model a reason, an estimate or a consequence the ranked list never displayed.

That left the same JSON→dataclass code written twice, and the second copy was written without
``consequences`` — so §22 spent its life relaying an empty ``Consequences`` while a renderer for
it sat unreachable in :mod:`tracker.advisor.dispatch`. One copy, imported twice, is the fix and
also the guard: a field added here reaches both surfaces or neither.

**Pure functions over already-loaded JSON.** No session, no row access, no clock. ``_estimate``
stays behind in :mod:`tracker.sync.guidance` because it reads columns off a row, which is a
different kind of thing. The encode direction lives in
:func:`tracker.db.persist_engine_output._consequences_json`.

Every decoder treats an absent column as an empty result rather than an error. A run that
predates a column, an entry that genuinely had nothing to say — both are legitimate, and §9.5
forbids inventing something to fill the gap.
"""

from __future__ import annotations

from typing import Any

from tracker.domain.types import (
    Acceleration,
    BandEstimate,
    Confidence,
    Consequences,
    FactorContribution,
    GateProgress,
    GoalLink,
    GoalProgress,
    LeafRef,
    UnblockedCapability,
)


def blockers_from_json(raw: list[dict[str, Any]] | None) -> tuple[LeafRef, ...]:
    """The unsatisfied leaves §9.1 recorded, back into :class:`LeafRef`."""
    return tuple(
        LeafRef(
            leaf_type=str(leaf.get("leaf_type", "")),
            key=str(leaf.get("key", "")),
            description=str(leaf.get("description", "")),
            target=leaf.get("target"),
        )
        for leaf in (raw or ())
    )


def bands_from_json(raw: list[dict[str, Any]] | None) -> tuple[BandEstimate, ...]:
    """§8's per-level-band estimates, including which method each band was costed with."""
    return tuple(
        BandEstimate(
            from_level=int(band.get("from_level", 0)),
            to_level=int(band.get("to_level", 0)),
            method_id=band.get("method_id"),
            hours=float(band.get("hours", 0.0)),
            gp=int(band.get("gp", 0)),
            fallback=bool(band.get("fallback", False)),
        )
        for band in (raw or ())
    )


def factors_from_json(raw: dict[str, Any] | None) -> dict[str, FactorContribution]:
    """§9.6's per-factor value, weight and log contribution."""
    return {
        name: FactorContribution(
            name=name,
            value=float(values.get("value", 0.0)),
            weight=float(values.get("weight", 0.0)),
            log_contribution=float(values.get("log_contribution", 0.0)),
        )
        for name, values in (raw or {}).items()
    }


def consequences_from_json(raw: dict[str, Any] | None) -> Consequences:
    """§9.10's consequences, back from the JSON ``asdict`` wrote.

    An absent or empty object is a legitimate result — an entry that ranked on cheapness alone
    genuinely has nothing to say, and inventing something for it here would be exactly the
    authored justification §9.5 forbids.
    """
    data = raw or {}
    return Consequences(
        unblocks_capabilities=tuple(
            UnblockedCapability(**item) for item in data.get("unblocks_capabilities", ())
        ),
        gate_progress=tuple(
            GateProgress(
                candidate_id=item["candidate_id"],
                name=item["name"],
                remaining_before=item["remaining_before"],
                remaining_after=item["remaining_after"],
                satisfied=blockers_from_json(item.get("satisfied")),
            )
            for item in data.get("gate_progress", ())
        ),
        goal_progress=tuple(
            GoalProgress(
                capability_id=item["capability_id"],
                name=item["name"],
                weight=item["weight"],
                remaining_before=item["remaining_before"],
                remaining_after=item["remaining_after"],
                on_roadmap=item["on_roadmap"],
                satisfied=blockers_from_json(item.get("satisfied")),
            )
            for item in data.get("goal_progress", ())
        ),
        speeds_up=tuple(Acceleration(**item) for item in data.get("speeds_up", ())),
        goal_links=tuple(GoalLink(**item) for item in data.get("goal_links", ())),
    )


def confidence_word(raw: object) -> str:
    """§8.4's confidence as the lowercase word both prompts render.

    Anything unrecognised — including ``None`` — becomes *unknown* rather than a default level.
    An estimate with no confidence attached has not been assessed, and calling that *low* would
    assert an assessment nobody made.
    """
    if isinstance(raw, Confidence):
        return raw.name.lower()
    try:
        return Confidence(raw).name.lower()  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return "unknown"
