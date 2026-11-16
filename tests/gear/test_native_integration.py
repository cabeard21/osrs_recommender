"""Native stages preserve complete optimizer results on portable scenarios."""

import pytest

from tools.accept_compact_states import derive_case
from tools.benchmark_gear_desktop import case_provenance, result_digest
from tools.gear_search_quality_fixture import load_case
from tracker.gear.native import capture
from tracker.gear.optimizer import optimize


def inputs(name):
    case = load_case("melee_1m")
    case, _ = derive_case(case, case_provenance(case), name)
    return case.snapshot, case.request, case.catalog, case.content, case.prices, case.at


FLAGS = {
    "_execution_profile": "combined",
    "_fixed_reporting": True,
    "_factored_evaluation": True,
    "_compact_states": True,
    "_complete_frontiers": True,
}


@pytest.mark.parametrize("mode", ["single", "multi", "auto"])
@pytest.mark.parametrize(
    "priority",
    [
        "melee_defence_roll",
        "melee_magic_defence_roll",
        "melee_ranged_defence_roll",
        "stab_magic_defence_roll",
        "stab_ranged_defence_roll",
        "stab_magic_ranged_defence_roll",
        "slash_magic_defence_roll",
        "slash_ranged_defence_roll",
        "slash_magic_ranged_defence_roll",
        "crush_magic_defence_roll",
        "crush_ranged_defence_roll",
        "crush_magic_ranged_defence_roll",
    ],
)
def test_melee_roll_complete_frontiers_match_python_without_fallback(mode, priority):
    pytest.importorskip("tracker.gear.native._stages")
    from tests.gear.test_factored_multi import multi_case
    from tests.gear.test_multi_auto import inputs as auto_inputs

    args = list(auto_inputs(count=1) if mode == "auto" else multi_case(True))
    roles = args[1].roles[:1] if mode == "single" else args[1].roles
    args[1] = args[1].model_copy(
        update={"roles": roles, "secondary_priority": priority, "max_dps_loss_pct": 100}
    )
    reference = optimize(*args, **FLAGS)
    with capture() as evidence:
        actual = optimize(*args, **FLAGS, _native_search=True)
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] >= 1
    assert evidence.snapshot()["fallback_requests"] == 0
    assert any(row["event"] == "stage" for row in evidence.snapshot()["events"])


@pytest.mark.parametrize(
    "name",
    [
        "fixed_melee",
        "configured_ranged",
        "fixed_magic",
        "configured_magic",
        "fixed_defence_roll",
        "multi",
    ],
)
def test_native_complete_results_match_python(name):
    pytest.importorskip("tracker.gear.native._stages")
    args = inputs(name)
    reference = optimize(*args, **FLAGS)
    with capture() as evidence:
        result = optimize(*args, **FLAGS, _native_search=True)
    assert result_digest(result) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] >= 1
    assert evidence.snapshot()["fallback_requests"] == 0
    assert any(row["event"] == "stage" for row in evidence.snapshot()["events"])


@pytest.mark.parametrize("name", ["multi", "multi_auto", "multi_auto_mixed", "multi_auto_fixed"])
def test_native_running_frontiers_match_python_and_execute(name):
    pytest.importorskip("tracker.gear.native._stages")
    # Mechanism fixture stays small; the frozen full-catalog adoption cohort
    # separately verifies these modes without reducing search budgets.
    from tests.gear.test_factored_multi import multi_case
    from tests.gear.test_multi_auto import inputs as auto_inputs

    args = list(multi_case(True) if name == "multi" else auto_inputs())
    if name in {"multi_auto_mixed", "multi_auto_fixed"}:
        first, second = args[1].roles
        second = second.model_copy(
            update={
                "allowed_disciplines": None,
                "combat_options": None if name == "multi_auto_fixed" else second.combat_options,
            }
        )
        args[1] = args[1].model_copy(update={"roles": (first, second)})
    reference = optimize(*args, **FLAGS, _running_frontier=True)
    with capture() as evidence:
        result = optimize(*args, **FLAGS, _native_search=True, _running_frontier=True)
    assert result_digest(result) == result_digest(reference)
    diagnostics = evidence.snapshot()
    assert diagnostics["native_requests"] >= 1
    assert diagnostics["fallback_requests"] == 0
    assert any(row["event"] == "stage" for row in diagnostics["events"])


def test_spawned_workers_preserve_native_results_and_merge_evidence():
    pytest.importorskip("tracker.gear.native._stages")
    from tests.gear.test_parallel import inputs as worker_inputs
    from tracker.gear.auto import branch_requests
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.running_frontier import needs_running_cost_frontier

    snapshot, request, catalog, content, prices, now = worker_inputs()
    role = request.roles[0].model_copy(update={"allowed_disciplines": ("melee", "ranged")})
    request = request.model_copy(update={"roles": (role,)})
    expected = [
        (
            name,
            optimize(
                snapshot,
                branch,
                catalog,
                content,
                prices,
                now,
                **FLAGS,
                _running_frontier=needs_running_cost_frontier(request),
            ),
        )
        for name, branch in branch_requests(request)
    ]
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        worker_flags = {key: value for key, value in FLAGS.items() if key != "_complete_frontiers"}
        with capture() as evidence:
            actual = pool.run(
                snapshot,
                request,
                catalog,
                content,
                prices,
                now,
                **worker_flags,
                _native_search=True,
            )
    finally:
        pool.close()
    assert [(name, result_digest(row)) for name, row in actual] == [
        (name, result_digest(row)) for name, row in expected
    ]
    # Resource-frontier lanes may create additional native contexts per branch.
    assert evidence.snapshot()["native_requests"] >= len(expected)
    assert evidence.snapshot()["fallback_requests"] == 0


@pytest.mark.parametrize("configured", [False, True])
def test_native_preserves_special_role_inheritance_without_damage(configured):
    pytest.importorskip("tracker.gear.native._stages")
    from tests.gear.test_factored_multi import multi_case

    args = multi_case(configured, True)
    reference = optimize(*args, **FLAGS, _running_frontier=True)
    with capture() as evidence:
        actual = optimize(*args, **FLAGS, _native_search=True, _running_frontier=True)
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["fallback_requests"] == 0
    assert evidence.snapshot()["native_requests"] >= 1


def test_six_native_workers_cancel_crash_and_recover():
    import os
    from concurrent.futures.process import BrokenProcessPool

    from tracker.gear.optimizer import CombatOptionFilters
    from tracker.gear.parallel import AutoProcessPool

    pytest.importorskip("tracker.gear.native._stages")
    case = load_case("owned_slash")
    role = case.request.roles[0].model_copy(
        update={
            "allowed_disciplines": ("melee", "ranged", "magic"),
            "combat_options": CombatOptionFilters(
                attack_types=("stab", "slash", "crush", "light", "standard", "heavy", "magic"),
                stances=("accurate", "aggressive", "rapid"),
                spells=("fire_bolt",),
            ),
        }
    )
    request = case.request.model_copy(update={"roles": (role,)})
    args = (case.snapshot, request, case.catalog, case.content, case.prices, case.at)
    flags = {key: value for key, value in FLAGS.items() if key != "_complete_frontiers"}
    pool = AutoProcessPool(6)
    progress = []
    try:
        pool.start(case.content, case.catalog)
        assert len(pool._executor._processes) == 6
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(
                *args,
                **flags,
                _native_search=True,
                progress=progress.append,
                cancelled=lambda: any(
                    event.get("phase") == "gear_search" and event.get("stage_done", 0) > 0
                    for event in progress
                ),
            )
        assert not pool._stopped.is_set()
        with capture() as evidence:
            first = pool.run(*args, **flags, _native_search=True)
        assert evidence.snapshot()["native_requests"] >= 3
        assert evidence.snapshot()["fallback_requests"] == 0
        assert any(event["event"] == "stage" for event in evidence.snapshot()["events"])
        crash = pool._executor.submit(os._exit, 1)
        with pytest.raises(BrokenProcessPool):
            crash.result(timeout=10)
        with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
            pool.run(*args, **flags, _native_search=True)
        assert pool._executor is None
        with capture() as recovered:
            second = pool.run(*args, **flags, _native_search=True)
        assert recovered.snapshot()["native_requests"] >= 3
        assert recovered.snapshot()["fallback_requests"] == 0
        assert [(name, result_digest(row)) for name, row in second] == [
            (name, result_digest(row)) for name, row in first
        ]
    finally:
        pool.close()
    assert pool._executor is None
