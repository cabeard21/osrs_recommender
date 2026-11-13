"""Real spawned requests retain profile isolation and normalized result parity."""

import pytest

from tests.gear.test_parallel import inputs
from tools.benchmark_gear_desktop import without_observations
from tracker.gear.auto import branch_requests
from tracker.gear.optimizer import optimize
from tracker.gear.parallel import AutoProcessPool
from tracker.gear.potions import PotionPolicy


def test_profiles_switch_on_warm_workers_and_potion_branches():
    a, r, c, t, p, n = inputs()
    pool = AutoProcessPool(2)
    try:
        pool.start(t, c)
        for profile in ("combined", "baseline", "lazy"):
            rows = pool.run(a, r, c, t, p, n, _execution_profile=profile)
            for (_, concrete), (_, result) in zip(branch_requests(r), rows, strict=True):
                reference = optimize(
                    a, concrete, c, t, p, n, _complete_frontiers=True, _running_frontier=True
                )
                assert without_observations(result) == without_observations(reference)
        concrete = next(branch_requests(r))[1]
        branches = [
            concrete.model_copy(update={"potions": PotionPolicy(mode="fixed", selected_ids=ids)})
            for ids in ((), ("super_strength",))
        ]
        rows = pool.run_potions(
            a, concrete, c, t, p, n, branches=branches, _execution_profile="combined"
        )
        for result, branch in zip(rows, branches, strict=True):
            assert without_observations(result) == without_observations(
                optimize(a, branch, c, t, p, n, _complete_frontiers=True)
            )
        for bad in ("wrong", True):
            with pytest.raises(ValueError, match="profile"):
                pool.run(a, r, c, t, p, n, _execution_profile=bad)
            with pytest.raises(ValueError, match="profile"):
                pool.run_potions(a, concrete, c, t, p, n, branches=branches, _execution_profile=bad)
    finally:
        pool.close()


def test_profile_cancellation_then_baseline_recovery():
    a, r, c, t, p, n = inputs()
    pool = AutoProcessPool(2)
    try:
        pool.start(t, c)
        polls = []

        def cancelled():
            polls.append(True)
            return len(polls) > 1

        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(
                a,
                r,
                c,
                t,
                p,
                n,
                _execution_profile="combined",
                cancelled=cancelled,
            )
        assert len(pool.run(a, r, c, t, p, n, _execution_profile="baseline")) == 3
    finally:
        pool.close()


def test_fixed_reporting_propagates_potions_on_warm_pool_and_recovers(monkeypatch):
    from tracker.gear.prayers import PrayerPolicy

    a, request, c, t, p, n = inputs()
    concrete = next(branch_requests(request))[1]
    role = concrete.roles[0].model_copy(update={"combat_options": None, "prayers": PrayerPolicy()})
    concrete = concrete.model_copy(update={"roles": (role,)})
    branches = [
        concrete.model_copy(update={"potions": PotionPolicy(mode="fixed", selected_ids=ids)})
        for ids in ((), ("super_strength",))
    ]
    pool = AutoProcessPool(2)
    try:
        pool.start(t, c)
        for enabled in (True, False, True):
            rows = pool.run_potions(
                a,
                concrete,
                c,
                t,
                p,
                n,
                branches=branches,
                _execution_profile="combined",
                _fixed_reporting=enabled,
            )
            for result, branch in zip(rows, branches, strict=True):
                reference = optimize(a, branch, c, t, p, n, _complete_frontiers=True)
                assert without_observations(result) == without_observations(reference)
        # The Auto dispatch path admits the private boolean too.
        assert (
            len(
                pool.run(
                    a, request, c, t, p, n, _execution_profile="combined", _fixed_reporting=True
                )
            )
            == 3
        )
        for bad in (1, "true", None):
            with pytest.raises(ValueError, match="worker options"):
                pool.run(a, request, c, t, p, n, _fixed_reporting=bad)
            with pytest.raises(ValueError, match="worker options"):
                pool.run_potions(a, concrete, c, t, p, n, branches=branches, _fixed_reporting=bad)
        polls = []
        aborted = []
        original_abort = pool._abort

        def cancelled():
            polls.append(True)
            # The first poll is the predispatch guard. Cancel only after submit.
            return len(polls) > 1

        def record_abort(futures):
            aborted.extend(futures)
            return original_abort(futures)

        monkeypatch.setattr(pool, "_abort", record_abort)
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run_potions(
                a,
                concrete,
                c,
                t,
                p,
                n,
                branches=branches,
                _execution_profile="combined",
                _fixed_reporting=True,
                cancelled=cancelled,
            )
        assert len(polls) == 2
        assert len(aborted) == len(branches)
        assert all(future.done() for future in aborted)
        assert (
            len(
                pool.run_potions(
                    a, concrete, c, t, p, n, branches=branches, _execution_profile="baseline"
                )
            )
            == 2
        )
    finally:
        pool.close()
