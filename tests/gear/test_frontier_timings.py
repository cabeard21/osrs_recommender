"""Frontier phase diagnostics account for both objective passes without changing results."""

from itertools import count

import pytest

from tests.gear.test_optimizer import run, weapon
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig

FRONTIER_PHASES = {
    "pool_preparation",
    "metric_lane",
    "diverse_equipment",
    "assignments",
    "combat_variants",
    "ammunition_refinement",
    "finalist_refinement",
    "publication",
    "total",
}


def scenario():
    return run(
        [weapon(1, "magic"), weapon(2, "magic", 30)],
        (
            RoleConfig(
                id="mage",
                style="magic",
                combat_options=CombatOptionFilters(
                    attack_types=("magic",),
                    stances=("accurate", "longrange"),
                    spells=("fire_strike",),
                ),
            ),
        ),
        secondary_priority="balanced_defence",
        max_swaps=0,
    )


def without_timings(value):
    if isinstance(value, dict):
        return {
            key: without_timings(row)
            for key, row in value.items()
            if not key.endswith("timings_seconds")
        }
    if isinstance(value, list):
        return [without_timings(row) for row in value]
    return value


def assert_accounted(timings, phases):
    assert set(timings) == phases
    assert all(value >= 0 for value in timings.values())
    assert sum(value for key, value in timings.items() if key != "total") == pytest.approx(
        timings["total"]
    )


def test_scalar_frontier_reports_complete_phase_timings():
    result = scenario()
    secondary = result["search"]["secondary_frontier"]
    assert_accounted(secondary["timings_seconds"], FRONTIER_PHASES)
    assert result["secondary_frontiers"][0]["points"]
    assert not result["search"].get("running_cost_frontier")


def test_phase_clock_does_not_change_pareto_points_or_work(monkeypatch):
    import tracker.gear.frontier as frontier
    import tracker.gear.running_frontier as running

    clock = count()
    monkeypatch.setattr(frontier, "perf_counter", lambda: next(clock), raising=False)
    monkeypatch.setattr(running, "perf_counter", lambda: next(clock), raising=False)
    measured = scenario()
    monkeypatch.setattr(frontier, "perf_counter", lambda: 0, raising=False)
    monkeypatch.setattr(running, "perf_counter", lambda: 0, raising=False)
    timeless = scenario()
    assert without_timings(measured) == without_timings(timeless)
    assert measured["search"]["secondary_frontier"]["timings_seconds"]["total"] > 0
    assert timeless["search"]["secondary_frontier"]["timings_seconds"]["total"] == 0
