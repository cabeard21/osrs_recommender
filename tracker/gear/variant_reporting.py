"""Compact frontier alternatives with exact, on-demand report tie breaking."""

from __future__ import annotations

import json
from collections import ChainMap
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from functools import total_ordering
from typing import Any, cast

from tracker.gear.combat import evaluate_prepared_score, numeric_attack_interval
from tracker.gear.priorities import secondary_value
from tracker.gear.scoring import PreparedEquipment

_ACTIVE: ContextVar[bool] = ContextVar("lazy_frontier_variants", default=False)
_EQUALITY_SCALARS = (
    "score",
    "secondary_value",
    "secondary_priority",
    "purchase_cost_gp",
    "maximum_actions",
    "max_gear_inventory_slots",
    "gear_inventory_slots",
    "distinct_items",
    "reserved_supply_slots",
    "remaining_supply_slots",
    "remaining_inventory_slots",
)


@contextmanager
def lazy_variants() -> Iterator[None]:
    """Keep deferred alternatives inside one optimizer execution."""
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active() -> bool:
    return _ACTIVE.get()


def candidate_identity(loadouts: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identify deterministic reports within this frozen search context.

    Every report field is determined by these physical assignments and exact
    attack/prayer choices, with frozen role, account, target and cost inputs.
    This key is only for internal deduplication; published IDs still hash the
    complete original JSON, including performance and resource provenance.
    """
    return tuple(
        (
            rid,
            tuple(sorted(row["equipment"].items())),
            None if row["combat_option"] is None else tuple(sorted(row["combat_option"].items())),
            tuple(row.get("selected_prayer_ids", ())),
        )
        for rid, row in sorted(loadouts.items())
    )


@total_ordering
class _ReportTie:
    """Compare the original lexical JSON only after all numeric keys tie."""

    def __init__(self, report: Callable[[], dict[str, Any]]) -> None:
        self._report: Callable[[], dict[str, Any]] | None = report
        self._text: str | None = None

    def text(self) -> str:
        if self._text is None:
            report = self._report
            assert report is not None
            self._text = json.dumps(report()["loadouts"], sort_keys=True)
            # A resolved rank key needs only its exact text, not its candidate.
            self._report = None
        return self._text

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _ReportTie):
            return self.text() == other.text()
        if isinstance(other, str):
            return self.text() == other
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, _ReportTie):
            return self.text() < other.text()
        if isinstance(other, str):
            return self.text() < other
        return NotImplemented


class CompactVariant(dict[str, Any]):
    """Search-only numeric projection; publication always calls materialize."""

    def __init__(self, values: dict[str, Any], report: Callable[[], dict[str, Any]]) -> None:
        super().__init__(values)
        self._report: Callable[[], dict[str, Any]] | None = report
        self._full: dict[str, Any] | None = None
        # Search candidates are immutable: substitutions construct new rows.
        # Diversity checks revisit these same descriptors many times in Multi.
        self._identity = candidate_identity(values["loadouts"])
        self._equality_scalars = tuple(values.get(key) for key in _EQUALITY_SCALARS)

    def materialize(self) -> dict[str, Any]:
        if self._full is None:
            report = self._report
            assert report is not None
            self._full = materialize(report())
            # Drop captured searches/seeds only after successful publication.
            # Exceptions retain the factory so cancellation can be retried.
            self._report = None
        return self._full

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, dict):
            return NotImplemented
        if "loadouts" not in other:
            return False
        if not isinstance(other, CompactVariant):
            # Plain published rows have no cached scalar tuple. Reject the
            # common differing-score case before allocating its other fields.
            score, expected = other.get("score"), self._equality_scalars[0]
            if expected is not score and expected != score:
                return False
            secondary, expected = other.get("secondary_value"), self._equality_scalars[1]
            if expected is not secondary and expected != secondary:
                return False
        scalars = (
            other._equality_scalars
            if isinstance(other, CompactVariant)
            else tuple(other.get(key) for key in _EQUALITY_SCALARS)
        )
        if self._equality_scalars != scalars:
            return False
        identity = (
            other._identity
            if isinstance(other, CompactVariant)
            else candidate_identity(other["loadouts"])
        )
        if self._identity != identity:
            return False
        return self.materialize() == materialize(other)

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        return NotImplemented if result is NotImplemented else not result


def materialize(solution: dict[str, Any]) -> dict[str, Any]:
    return solution.materialize() if isinstance(solution, CompactVariant) else solution


def loadout_tie(solution: Mapping[str, Any]) -> str | _ReportTie:
    return (
        _ReportTie(solution.materialize)
        if isinstance(solution, CompactVariant)
        else json.dumps(solution["loadouts"], sort_keys=True)
    )


def _report_variant(
    search: Any, state: dict[str, Any], role: Any, configured: Any, option: Any
) -> dict[str, Any]:
    """Use the original exact validation and report path for retained rows."""
    if search.cancelled and search.cancelled():
        raise ValueError("optimization_cancelled")
    full = materialize(state)
    equipment = full["loadouts"][role.id]["equipment"]
    performance = search.evaluate(equipment, configured).model_dump(mode="json")
    variant = copy(search)
    # This boundary already needs a complete report. Avoid wrapping the seeded
    # full evaluations in another lazy solution only to expand it immediately.
    variant._compact_solution_bypass = True
    variant.compact_cache = {}
    variant.performance_cache = ChainMap({}, search.performance_cache)
    variant.option_cache = ChainMap({}, search.option_cache)
    for rid, loadout in full["loadouts"].items():
        key = (rid, tuple(sorted(loadout["equipment"].items())))
        variant.performance_cache[key] = loadout["performance"]
        variant.option_cache[key] = {
            **(loadout["combat_option"] or {}),
            "__prayer_ids": loadout.get("selected_prayer_ids", []),
        }
    key = (role.id, tuple(sorted(equipment.items())))
    variant.performance_cache[key] = performance
    variant.option_cache[key] = {
        **option.model_dump(
            mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
        ),
        "__prayer_ids": list(configured.active_prayer_ids),
    }
    assignment = {rid: row["equipment"] for rid, row in full["loadouts"].items()}
    result = variant.solution(assignment, None)
    # Equipment constraints were already validated for the seed and are unchanged.
    assert result is not None
    return cast(dict[str, Any], result)


def compact_variant(
    search: Any, state: dict[str, Any], role: Any, configured: Any, option: Any
) -> CompactVariant | None:
    """Score an exact attack override without constructing its public report."""
    equipment = state["loadouts"][role.id]["equipment"]
    prepared = search.prepare(equipment)
    if not isinstance(prepared, PreparedEquipment):
        return None
    score = evaluate_prepared_score(
        prepared,
        configured,
        search.levels,
        include_defence=search.request.secondary_priority.endswith("_defence_roll"),
    )
    if not score.supported:
        return None
    performance = {
        "supported": True,
        "dps": score.dps,
        "accuracy": score.accuracy,
        "ring_charge_probability": score.ring_charge_probability,
        "bonuses": score.bonuses.__dict__,
        "player_defence_rolls": score.player_defence_rolls,
        "attack_interval": numeric_attack_interval(prepared.weapon, configured),
    }
    # The original override cache always adds __prayer_ids, even for an
    # unscored special role whose option was None. combat_option() therefore
    # publishes {} for that retained role after removing the private key.
    retained = {
        rid: {**row, "combat_option": row["combat_option"] or {}}
        for rid, row in state["loadouts"].items()
    }
    loadouts = {
        **retained,
        role.id: {
            **state["loadouts"][role.id],
            "performance": performance,
            "combat_option": option.model_dump(
                mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
            ),
            "selected_prayer_ids": list(configured.active_prayer_ids),
        },
    }
    roles = [r for r in search.request.roles if r.style != "special"]
    weight = sum(r.weight for r in roles) or 1
    dps = sum((loadouts[r.id]["performance"].get("dps") or 0) * r.weight for r in roles) / weight
    priority = search.request.secondary_priority
    secondary = (
        search.variant_secondary(loadouts)
        if hasattr(search, "variant_secondary")
        else sum(secondary_value(priority, loadouts[r.id]["performance"]) * r.weight for r in roles)
        / weight
        if priority != "default"
        else None
    )
    values = {**state, "score": dps, "secondary_value": secondary, "loadouts": loadouts}
    return CompactVariant(values, lambda: _report_variant(search, state, role, configured, option))
