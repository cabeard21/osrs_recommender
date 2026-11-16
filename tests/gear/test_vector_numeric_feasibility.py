"""Numeric feasibility must match the complete report's physical/resource checks."""

import pytest

from tests.gear.test_factored_multi import multi_case
from tests.gear.test_prayer_search_efficiency import search
from tracker.gear.objectives import canonical_objectives
from tracker.gear.vector_options import VectorOptions


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("reserve", [25, 28])
def test_numeric_feasibility_matches_rich_single_multi_and_prayer_reports(
    configured, single, reserve
):
    args = multi_case(configured, priority="default")
    args[1] = args[1].model_copy(
        update={
            "roles": args[1].roles[:1] if single else args[1].roles,
            "reserved_supply_slots": reserve,
            "objectives": canonical_objectives([{"kind": "defence_roll", "styles": ["stab"]}]),
        }
    )
    instance = search(args)
    instance.running_prices, instance.running_at = args[4], args[5]
    options = VectorOptions(instance)
    assignment = {
        role.id: {"weapon": 1 if role.id == "a" else 2, "head": 10 if role.id == "a" else 20}
        for role in instance.request.roles
    }
    alternatives = [options.variants(assignment[role.id], role) for role in instance.request.roles]
    selected = tuple(values[0] for values in alternatives)
    numeric = options.numeric_feasibility(assignment, selected)
    rich = options.solution(assignment, selected)
    assert (numeric is None) == (rich is None)
    if rich is not None:
        assert numeric is not None
        for field in (
            "maximum_actions",
            "purchase_cost_gp",
            "gear_inventory_slots",
            "max_gear_inventory_slots",
        ):
            assert getattr(numeric, field) == rich[field]


def test_numeric_feasibility_rejects_budget_and_lock_violations_without_rich_combat(monkeypatch):
    args = multi_case(False, priority="default")
    instance = search(args)
    options = VectorOptions(instance)
    assignment = {"a": {"weapon": 1}, "b": {"weapon": 2}}
    selected = tuple(
        options.variants(assignment[role.id], role)[0] for role in instance.request.roles
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Numeric feasibility constructed a combat report")

    monkeypatch.setattr("tracker.gear.vector_options.evaluate_prepared_loadout", unexpected)
    assert options.numeric_feasibility(assignment, selected) is not None
    assert options.numeric_feasibility({"a": {"weapon": 2}, "b": {"weapon": 2}}, selected) is None
    monkeypatch.setattr(instance, "cost", lambda carried: 1)
    assert options.numeric_feasibility(assignment, selected) is None


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_deferred_reports_preserve_complete_archives_and_running_costs(monkeypatch, single, native):
    from tools.benchmark_objectives import result_summary
    from tracker.gear.objective_store import close_result_archives
    from tracker.gear.optimizer import optimize
    from tracker.gear.vector_options import NumericFeasibility

    if native:
        pytest.importorskip("tracker.gear.native._scoring")
    args = multi_case(True, priority="default")
    args[1] = args[1].model_copy(
        update={
            "roles": args[1].roles[:1] if single else args[1].roles,
            "objectives": canonical_objectives(
                [
                    {"kind": "defence_roll", "styles": ["stab", "magic"]},
                    {"kind": "prayer_bonus"},
                ]
            ),
        }
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_native_search": native,
        "_running_frontier": True,
        "_complete_frontiers": True,
    }
    expected = actual = None
    try:
        with monkeypatch.context() as scoped:
            # Reference the former eager first-option feasibility behavior. Its
            # full report remains the independent oracle for every admitted cap.
            def eager(options, assignment, selected, **kwargs):
                report = options.solution(assignment, selected)
                if report is None:
                    return None
                return NumericFeasibility(
                    *(
                        report[field]
                        for field in (
                            "maximum_actions",
                            "purchase_cost_gp",
                            "gear_inventory_slots",
                            "max_gear_inventory_slots",
                        )
                    )
                )

            scoped.setattr(VectorOptions, "numeric_feasibility", eager)
            expected = optimize(*args, **flags)
        actual = optimize(*args, **flags)
        assert result_summary(actual) == result_summary(expected)
        assert actual["selected_solution"] == expected["selected_solution"]
        assert actual["running_cost_frontiers"] == expected["running_cost_frontiers"]
        assert actual["search"]["objective_frontier"] == expected["search"]["objective_frontier"]
    finally:
        close_result_archives(expected)
        close_result_archives(actual)
