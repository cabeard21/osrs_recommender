"""Full P1 crosses real desktop worker boundaries and rolls back cleanly."""

import pytest

from tests.gear.test_parallel import inputs
from tools.benchmark_gear_desktop import without_observations
from tools.gear_search_quality_fixture import load_case
from tracker.gear.auto import branch_requests
from tracker.gear.optimizer import optimize
from tracker.gear.parallel import AutoProcessPool
from tracker.gear.potions import PotionPolicy
from tracker.gear.service import GearService, _timing_key


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
def test_service_factored_dispatch_and_timing_identity(profile, monkeypatch):
    case = load_case("melee_1m")
    service = GearService(
        case.content,
        optimization_profile=profile,
        fixed_reporting=True,
        factored_evaluation=True,
    )
    service._equipment = case.catalog
    calls = []
    monkeypatch.setattr("tracker.gear.optimizer.optimize", lambda *a, **k: calls.append(k) or {})
    service.optimize(case.snapshot, case.request, now=case.at)
    assert calls[0].get("_factored_evaluation", False) == (profile == "combined")
    assert _timing_key(case.request, False, False, "combined", True, True) != _timing_key(
        case.request, False, False, "combined", True, False
    )


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_service_factored_flag_validation(bad):
    with pytest.raises(ValueError, match="factored evaluation"):
        GearService(load_case("melee_1m").content, factored_evaluation=bad)


def test_factored_warm_workers_auto_potions_and_cancellation():
    a, request, c, t, p, n = inputs()
    concrete = next(branch_requests(request))[1]
    branches = [
        concrete.model_copy(update={"potions": PotionPolicy(mode="fixed", selected_ids=ids)})
        for ids in ((), ("super_strength",))
    ]
    pool = AutoProcessPool(2)
    options = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
    }
    try:
        pool.start(t, c)
        rows = pool.run(a, request, c, t, p, n, **options)
        for (_, branch), (_, row) in zip(branch_requests(request), rows, strict=True):
            expected = optimize(
                a, branch, c, t, p, n, _complete_frontiers=True, _running_frontier=True
            )
            assert without_observations(row) == without_observations(expected)
        for enabled in (True, False, True):
            rows = pool.run_potions(
                a,
                concrete,
                c,
                t,
                p,
                n,
                branches=branches,
                **{**options, "_factored_evaluation": enabled},
            )
            for row, branch in zip(rows, branches, strict=True):
                expected = optimize(a, branch, c, t, p, n, _complete_frontiers=True)
                assert without_observations(row) == without_observations(expected)
        polls = []

        def cancelled():
            polls.append(True)
            return len(polls) > 1

        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(a, request, c, t, p, n, **options, cancelled=cancelled)
        assert len(polls) >= 2
        assert len(pool.run(a, request, c, t, p, n, _execution_profile="baseline")) == 3
        for bad in (1, "true", None):
            with pytest.raises(ValueError, match="worker options"):
                pool.run(a, request, c, t, p, n, _factored_evaluation=bad)
    finally:
        pool.close()
