"""Coarse native partial expansion must preserve every complete frontier and budget prefix."""

import pytest

from tests.gear.test_factored_multi import multi_case
from tools.benchmark_objectives import result_summary
from tracker.gear.objective_store import close_result_archives
from tracker.gear.objectives import canonical_objectives
from tracker.gear.optimizer import optimize
from tracker.gear.vector_search import VectorSearch


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("configured", [False, True])
def test_native_partial_expansion_matches_python_loops_exactly(monkeypatch, single, configured):
    stages = pytest.importorskip("tracker.gear.native._stages")
    assert hasattr(stages.StageContext, "begin_projection"), (
        "Rebuild native vector projection stages"
    )
    args = multi_case(configured, priority="default")
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
        "_native_search": True,
        "_complete_frontiers": True,
    }
    expected = actual = None
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(VectorSearch, "_native_equipment", lambda *args: None)
            expected = optimize(*args, **flags)
        actual = optimize(*args, **flags)
        assert result_summary(actual) == result_summary(expected)
        assert actual["search"]["objective_frontier"] == expected["search"]["objective_frontier"]
        assert actual["selected_solution"] == expected["selected_solution"]
    finally:
        close_result_archives(expected)
        close_result_archives(actual)


@pytest.mark.parametrize("quota", [1, 4, 6])
def test_native_partial_expansion_keeps_the_same_phase_budget_prefix(quota):
    from tests.gear.test_prayer_search_efficiency import search
    from tracker.gear.execution_profile import execution_context

    stages = pytest.importorskip("tracker.gear.native._stages")
    assert hasattr(stages.StageContext, "begin_projection"), (
        "Rebuild native vector projection stages"
    )
    args = multi_case(False, priority="default")
    args[1] = args[1].model_copy(
        update={
            "objectives": canonical_objectives(
                [
                    {"kind": "defence_roll", "styles": ["stab", "magic"]},
                ]
            )
        }
    )
    with execution_context(
        "combined",
        args[1],
        fixed_reporting=True,
        factored_evaluation=True,
        compact_states=True,
        native_search=True,
    ):
        instance = search(args)
        engine = VectorSearch(instance)
        try:
            role = instance.request.roles[0]
            states, choices = [{}, {"weapon": 1}], [None, 1, 2]
            engine.nodes, engine.phase_limit = 1022, 1022 + quota
            expected = engine._python_equipment((role,), states, choices, "weapon")
            expected_nodes = engine.nodes
            engine.nodes = 1022
            actual = engine._native_equipment((role,), states, choices, "weapon")
            assert actual == expected
            assert engine.nodes == expected_nodes == 1022 + quota
        finally:
            for archive in set(engine.archives.values()):
                archive.close()
