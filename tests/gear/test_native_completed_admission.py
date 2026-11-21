from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW
from tracker.gear.compact_solutions import CompactSolution
from tracker.gear.optimizer import OptimizationRequest, RoleConfig
from tracker.gear.vector_search import VectorSearch


def test_joint_cap_screen_matches_full_reports_and_queues_rejected_gear():
    pytest.importorskip("tracker.gear.native._frontier")
    roles = tuple(RoleConfig(id=rid, style="slash") for rid in ("a", "b"))
    request = OptimizationRequest(
        roles=roles, max_swaps=1, objectives=[{"kind": "gp_per_damage"}, {"kind": "prayer_bonus"}]
    )

    def exercise(native):
        search = SimpleNamespace(
            request=request,
            running_prices={},
            running_at=NOW,
            native_context=object() if native else None,
        )
        engine = VectorSearch(search)
        reports = []
        try:
            # Each candidate has a distinct physical ID; equal numeric and resource
            # prefixes must still compare the complete loadout reports lexically.
            for item, swaps, dps, cost, purchase in (
                (90, 1, 10, 2, 100),
                (80, 0, 8, 2, 100),
                (70, 1, 7, 5, 10),
                (60, 1, 10, 2, 200),
                (10, 1, 10, 2, 100),
                (11, 1, 11, None, 100),
                (12, 1, 9, None, 1),
            ):
                assignment = {r.id: {"weapon": item} for r in roles}
                values = {
                    "score": dps,
                    "maximum_actions": swaps,
                    "secondary_value": None,
                    "carried_item_ids": [item],
                    "purchase_cost_gp": purchase,
                    "max_gear_inventory_slots": 1,
                    "transitions": [],
                    "running_cost": {"gp_per_damage": cost},
                    "loadouts": {
                        rid: {
                            "equipment": gear,
                            "combat_option": None,
                            "performance": {"bonuses": {"prayer": 4}},
                        }
                        for rid, gear in assignment.items()
                    },
                }

                def report(values=values, item=item):
                    reports.append(item)
                    return {**values, "purchases": [{"item_id": item}]}

                row = CompactSolution(values, report)
                search.solution = lambda *_args, row=row: row
                engine.capture_base(assignment)
            pending = engine.seen.execute(
                "SELECT cursor, complete FROM seen_assignments"
            ).fetchall()
            assert pending == [(0, 0)] * 7
            assert engine.baselines[0]["score"] == 8
            assert engine.baselines[1]["score"] == 11
            assert "gp_per_damage" not in engine.baselines[1]["objective_values"]
            assert engine._unpriced_screened == (2 if native else 0)
            return (
                reports,
                engine.baselines,
                {cap: ar.solutions() for cap, ar in engine.archives.items()},
            )
        finally:
            for archive in engine.archives.values():
                archive.close()

    reference, native = exercise(False), exercise(True)
    assert native[1:] == reference[1:]
    assert reference[0] == [90, 80, 70, 60, 10, 11, 12]
    assert native[0] == [90, 80, 10, 11]


def test_repeated_base_gear_reuses_only_identical_unseeded_inputs():
    pytest.importorskip("tracker.gear.native._frontier")
    from tests.gear.test_prayer_search_efficiency import search as make_search
    from tests.gear.test_variant_reporting import inputs
    from tracker.gear.objectives import ObjectiveDescriptor

    args = inputs(priority="default", joint=True)
    args[1] = args[1].model_copy(
        update={"objectives": (ObjectiveDescriptor(kind="gp_per_damage"),)}
    )
    search = make_search(args)
    search.performance_cache.clear()
    search.option_cache.clear()
    search.running_prices, search.running_at = {}, NOW
    search.compact_states = True
    search.native_context = object()
    engine = VectorSearch(search)
    gear = {"a": {"weapon": 2, "head": 7}, "b": {"weapon": 2}}
    reordered = {**gear, "a": dict(reversed(gear["a"].items()))}
    solved = []
    search.solution = lambda *args: solved.append(args)
    try:
        engine.capture_base(gear)
        engine.seen.execute("UPDATE seen_assignments SET cursor=8")
        engine.capture_base(gear)
        engine.capture_base(reordered)
        engine.capture_base(reordered)
        key = ("a", tuple(sorted(gear["a"].items())))
        search.performance_cache[key] = {"dps": 1}
        engine.capture_base(reordered)
        search.performance_cache[key]["dps"] = 2
        engine.capture_base(reordered)
        del search.performance_cache[key]
        engine.capture_base(reordered)
        assert len(solved) == 5
        assert engine.seen.execute("SELECT cursor,complete FROM seen_assignments").fetchall() == [
            (8, 0)
        ]
    finally:
        for archive in engine.archives.values():
            archive.close()


def test_native_baseline_screen_includes_unrestricted_and_keeps_exact_ties():
    frontier = pytest.importorskip("tracker.gear.native._frontier")
    index = frontier.CapBaselines(2)

    def candidate(score, rank):
        return SimpleNamespace(baseline_prefix=(-score, rank))

    # Caps 0, 1, 2 and unrestricted have independent DPS winners.
    for cap, score in ((0, 3.0), (1, 5.0), (2, 5.0)):
        assert index.may_win(0, 4.0, candidate(4, 1))
        index.update(cap, score, candidate(score, 1).baseline_prefix)
    assert index.may_win(7, 1.0, candidate(1, 99))
    index.update(None, 6.0, candidate(6, 0).baseline_prefix)
    assert index.may_win(0, 4.0, candidate(4, 1))
    # Strict DPS decisions require no rich tie key.
    assert not index.may_win(1, 4.0, None)
    assert index.may_win(3, 7.0, None)
    assert index.may_win(2, 5.0, candidate(5, 1))
    assert index.may_win(2, 5.0, candidate(5, 0))
    assert not index.may_win(2, 5.0, candidate(5, 2))
