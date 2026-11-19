"""Coarse Python/native boundaries; candidate loops run inside compiled stages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tracker.gear.native import NativeSearchUnavailable, record

if TYPE_CHECKING:
    from tracker.gear.optimizer import _Winner


def winner(search: Any, equipment: Any, role: Any, prepared: Any = None) -> _Winner | None:
    from tracker.gear.combat import CombatScore
    from tracker.gear.optimizer import _Winner
    from tracker.gear.scoring import PreparedEquipment

    prepared = search.prepare(equipment) if prepared is None else prepared
    if not isinstance(prepared, PreparedEquipment):
        return None
    index = next(index for index, row in enumerate(search.request.roles) if row.id == role.id)
    score = search.native_context.score
    metric = getattr(search, "metric_first", False)
    if role.style == "magic" and getattr(search, "rune_limits_active", False):
        mask = rune_context(search).option_mask(equipment, index, metric)
        result = score(
            equipment,
            index,
            metric,
            option_allowed=search.rune_option_allowed if mask is None else None,
            option_mask=mask,
        )
    else:
        result = score(equipment, index, metric)
    if not result["supported"]:
        return None
    configured, option = search.native_context.option_records[result["option_index"]]
    bonuses = prepared.ranged_bonuses if configured.style == "ranged" else prepared.bonuses
    return _Winner(
        CombatScore(
            True, result["dps"], result["accuracy"], bonuses, result.get("player_defence_rolls")
        ),
        option,
        configured,
    )


def rune_context(search: Any) -> Any:
    from tracker.gear.native._stages import StageContext

    # Winner selection can run while candidate-pool marginals are still being built.
    # An expansion context must capture the finished marginals.
    context = getattr(search, "_native_rune_context", None)
    if context is None or getattr(search, "_native_rune_owner", None) != id(search):
        context = StageContext(search.native_context, search)
        search._native_rune_context = context
        search._native_rune_owner = id(search)
    return context


def expand(
    search: Any,
    kind: str,
    states: Any,
    choices: Any,
    *,
    slot: str = "weapon",
    roles: Any = (),
    cap: int | None = None,
    limit: int,
    tuple_role: str | None = None,
) -> list[Any]:
    from tracker.gear.native._stages import StageContext
    from tracker.gear.optimizer import _assignment_state, _equipment_state

    context = getattr(search, "_native_stage_context", None)
    if context is None or getattr(search, "_native_stage_owner", None) != id(search):
        context = StageContext(search.native_context, search)
        search._native_stage_context = context
        search._native_stage_owner = id(search)
    stage = context.begin(
        kind=kind,
        states=states,
        choices=choices,
        slot=slot,
        roles=tuple(role.id for role in roles),
        cap=cap,
        frontier=getattr(search, "frontier_search", False),
        metric=getattr(search, "metric_first", False),
        tuple_role=tuple_role,
    )
    attempted = 0
    while not stage.done:
        if search.cancelled and search.cancelled():
            raise ValueError("optimization_cancelled")
        remaining = search.native_limit - search.nodes
        if remaining <= 0:
            break
        count = stage.advance(min(1024 - (search.nodes & 1023), remaining))
        if count <= 0:
            raise NativeSearchUnavailable("Native stage made no progress")
        search.nodes += count
        attempted += count
        if not search.nodes & 1023 and hasattr(search, "native_report"):
            search.native_report()
    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")
    vector_search = getattr(search, "vector_search", None)
    from tracker.gear.compact_states import SLOT_NAMES

    complete = (kind in {"loadout", "joint"} and slot == SLOT_NAMES[-1]) or (
        kind == "tuple" and tuple_role == search.request.roles[-1].id
    )
    if vector_search is not None and complete:
        for row in stage.complete_candidates():
            if search.cancelled and search.cancelled():
                raise ValueError("optimization_cancelled")
            assignment = (
                {role.id: row for role in (roles or search.request.roles)}
                if kind == "loadout"
                else row
            )
            vector_search.capture_base(assignment)
    result = stage.finish(limit)
    record(
        "stage",
        stage=kind,
        slot=slot,
        attempts=attempted,
        retained=len(result),
        roles=tuple(role.style for role in (roles or search.request.roles)),
        frontier=getattr(search, "frontier_search", False),
        metric=getattr(search, "metric_first", False),
        cost="gp_per_damage" in getattr(search.native_context, "objective_ids", ()),
    )
    convert = _equipment_state if kind == "loadout" else _assignment_state
    return [convert(row) for row in result]
