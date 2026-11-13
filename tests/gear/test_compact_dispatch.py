import pytest

from tools.gear_search_quality_fixture import load_case
from tracker.gear import execution_profile as profiles
from tracker.gear.service import GearService, _timing_key


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
@pytest.mark.parametrize("factored", [False, True])
def test_compact_context_gating_and_exception_cleanup(profile, factored):
    request = load_case("melee_1m").request
    assert not profiles.compact_states_active()
    with (
        pytest.raises(RuntimeError),
        profiles.execution_context(
            profile, request, factored_evaluation=factored, compact_states=True
        ),
    ):
        assert profiles.compact_states_active() == (profile == "combined" and factored)
        with profiles.execution_context("baseline", request):
            assert not profiles.compact_states_active()
        assert profiles.compact_states_active() == (profile == "combined" and factored)
        raise RuntimeError("cancelled")
    assert not profiles.compact_states_active()


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_compact_flags_are_strict(bad):
    case = load_case("melee_1m")
    with pytest.raises(ValueError, match="compact states"):
        GearService(case.content, compact_states=bad)
    with (
        pytest.raises(ValueError, match="compact states"),
        profiles.execution_context("combined", case.request, compact_states=bad),
    ):
        pass


@pytest.mark.parametrize("profile", ["baseline", "lazy", "combined"])
@pytest.mark.parametrize("factored", [False, True])
def test_service_compact_dispatch(profile, factored, monkeypatch):
    case = load_case("melee_1m")
    service = GearService(
        case.content,
        optimization_profile=profile,
        factored_evaluation=factored,
        compact_states=True,
    )
    service._equipment = case.catalog
    calls = []
    monkeypatch.setattr("tracker.gear.optimizer.optimize", lambda *a, **k: calls.append(k) or {})
    service.optimize(case.snapshot, case.request, now=case.at)
    assert calls[0].get("_compact_states", False) == (profile == "combined" and factored)
    assert _timing_key(case.request, False, False, compact_states=True) != _timing_key(
        case.request, False, False
    )


def test_compact_worker_validation_and_recovery():
    from tests.gear.test_parallel import inputs
    from tracker.gear.auto import branch_requests
    from tracker.gear.parallel import AutoProcessPool

    a, request, catalog, content, prices, now = inputs()
    concrete = next(branch_requests(request))[1]
    pool = AutoProcessPool(1)
    try:
        pool.start(content, catalog)
        for bad in (None, 0, 1, "true"):
            with pytest.raises(ValueError, match="worker options"):
                pool.run(a, request, catalog, content, prices, now, _compact_states=bad)
            with pytest.raises(ValueError, match="worker options"):
                pool.run_potions(
                    a,
                    concrete,
                    catalog,
                    content,
                    prices,
                    now,
                    branches=[concrete],
                    _compact_states=bad,
                )
    finally:
        pool.close()


def test_compact_workers_auto_potions_and_cancellation():
    from tests.gear.test_parallel import inputs
    from tools.benchmark_gear_desktop import without_observations
    from tracker.gear.auto import branch_requests
    from tracker.gear.optimizer import optimize
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.potions import PotionPolicy

    a, request, catalog, content, prices, now = inputs()
    concrete = next(branch_requests(request))[1]
    branches = [
        concrete.model_copy(update={"potions": PotionPolicy(mode="fixed", selected_ids=ids)})
        for ids in ((), ("super_strength",))
    ]
    options = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_fixed_reporting": True,
    }
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        rows = pool.run(a, request, catalog, content, prices, now, **options, _compact_states=True)
        for (_, branch), (_, row) in zip(branch_requests(request), rows, strict=True):
            expected = optimize(
                a,
                branch,
                catalog,
                content,
                prices,
                now,
                **options,
                _complete_frontiers=True,
                _running_frontier=True,
            )
            assert without_observations(row) == without_observations(expected)
        for enabled in (True, False, True):
            rows = pool.run_potions(
                a,
                concrete,
                catalog,
                content,
                prices,
                now,
                branches=branches,
                **options,
                _compact_states=enabled,
            )
            for row, branch in zip(rows, branches, strict=True):
                expected = optimize(
                    a, branch, catalog, content, prices, now, **options, _complete_frontiers=True
                )
                assert without_observations(row) == without_observations(expected)
        polls = []

        def cancelled():
            polls.append(True)
            return len(polls) > 1

        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(
                a,
                request,
                catalog,
                content,
                prices,
                now,
                **options,
                _compact_states=True,
                cancelled=cancelled,
            )
        assert (
            len(
                pool.run(a, request, catalog, content, prices, now, **options, _compact_states=True)
            )
            == 3
        )
    finally:
        pool.close()
