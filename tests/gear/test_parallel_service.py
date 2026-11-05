"""Parallel dispatch preserves the shared service guard and canonical Auto merger."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from tests.gear.test_auto_disciplines import context, without_timings
from tracker.gear.auto import branch_requests, optimize_auto
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import RoleConfig, optimize
from tracker.gear.service import GearService


def serial_branches(snapshot, request, catalog, content, prices, now, **options):
    return [
        (
            discipline,
            optimize(
                snapshot,
                concrete,
                catalog,
                content,
                prices,
                now,
                _complete_frontiers=True,
                _running_frontier="magic" in request.roles[0].allowed_disciplines,
                **options,
            ),
        )
        for discipline, concrete in branch_requests(request)
    ]


def test_merger_preserves_canonical_order_even_when_runner_finishes_in_reverse():
    args = context()
    expected = optimize(*args)

    def reversed_branches(*args, **kwargs):
        return list(reversed(serial_branches(*args, **kwargs)))

    assert without_timings(
        optimize_auto(*args, branch_runner=reversed_branches)
    ) == without_timings(expected)


@pytest.mark.parametrize("bad", [[], [("melee", {})], [("melee", {}), ("melee", {})]])
def test_merger_rejects_incomplete_or_duplicate_branch_results(bad):
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        optimize_auto(*context(), branch_runner=lambda *a, **kw: bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "future", "skill_overrides": {"unknown_skill": 70}},
        {"mode": "future", "quest_overrides": {"unknown_quest": "complete"}},
        {"excluded_item_ids": (999999,)},
        {"expected_snapshot_id": "stale"},
        {"locks": {"head": 1}},
    ],
)
def test_invalid_frozen_context_keeps_serial_error_before_worker_dispatch(changes):
    snapshot, request, catalog, content, prices, now = context()
    request = request.model_copy(update=changes)
    with pytest.raises(ValueError) as expected:
        optimize(snapshot, request, catalog, content, prices, now)

    def unexpected(*a, **kw):
        pytest.fail("Invalid input reached a worker")

    with pytest.raises(ValueError) as actual:
        optimize_auto(snapshot, request, catalog, content, prices, now, branch_runner=unexpected)
    assert str(actual.value) == str(expected.value)


def test_service_dispatches_auto_and_keeps_serial_default():
    snapshot, request, catalog, content, prices, now = context()
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return serial_branches(*args, **kwargs)

    service = GearService(content, auto_pool=SimpleNamespace(run=run))
    service._equipment = EquipmentCatalog(catalog.items)
    result = service.optimize(snapshot, request, price_records=prices, now=now)
    assert without_timings(result) == without_timings(
        optimize(snapshot, request, service._equipment, content, prices, now)
    )
    assert len(calls) == 1
    assert calls[0]["cancelled"] is None
    default = GearService(content)
    assert default.auto_pool is None


def test_service_potion_dispatch_and_progress_are_request_scoped():
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = context()
    role = RoleConfig(id="melee", style="slash")
    request = request.model_copy(
        update={
            "roles": (role,),
            "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",)),
        }
    )
    calls = []

    def run_potions(
        snapshot, request, catalog, content, prices, now, *, branches, progress=None, **options
    ):
        calls.append(len(branches))
        results = []
        for branch in branches:
            results.append(optimize(snapshot, branch, catalog, content, prices, now, **options))
            progress(
                {
                    "phase": "potion_search",
                    "completed_profiles": len(results),
                    "total_profiles": len(branches),
                }
            )
        return results

    service = GearService(content, auto_pool=SimpleNamespace(run_potions=run_potions))
    service._equipment = EquipmentCatalog(catalog.items)
    result = service.optimize(
        snapshot,
        request,
        price_records=prices,
        now=now,
        progress_identity="request-one",
        progress_fingerprint="scenario",
    )
    assert result["selected_solution"]["potions"]["selected_ids"] == ["super_strength"]
    assert calls == [2]
    progress = service.optimization_progress("request-one")
    assert progress["completed"] == progress["total"] == 2
    assert progress["phase"] == "complete"
    assert progress["scenario_fingerprint"] == "scenario"
    assert service.optimization_progress("request-two") is None


def test_service_phase_updates_preserve_profile_counts(monkeypatch):
    from tracker.gear import optimizer
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = context()
    request = request.model_copy(update={"potions": PotionPolicy(mode="optimize")})
    service = GearService(content)
    service._equipment = EquipmentCatalog(catalog.items)

    def run(*args, progress, **kwargs):
        progress({"phase": "potion_search", "completed_profiles": 3, "total_profiles": 9})
        progress({"phase": "frontiers"})
        assert service.optimization_progress("request")["completed"] == 3
        assert service.optimization_progress("request")["total"] == 9
        return {}

    monkeypatch.setattr(optimizer, "optimize", run)
    service.optimize(snapshot, request, price_records=prices, now=now, progress_identity="request")


@pytest.mark.parametrize("mode", ["fixed", "one_discipline", "multi_role"])
def test_non_auto_and_one_discipline_searches_do_not_use_pool(mode):
    snapshot, request, catalog, content, prices, now = context()
    role = request.roles[0]
    if mode == "fixed":
        roles = (role.model_copy(update={"allowed_disciplines": None}),)
    elif mode == "one_discipline":
        roles = (role.model_copy(update={"allowed_disciplines": ("melee",)}),)
    else:
        roles = (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="ranged"))
    request = request.model_copy(update={"roles": roles})

    def unexpected(*a, **kw):
        pytest.fail("This request must stay on the existing serial search path")

    service = GearService(content, auto_pool=SimpleNamespace(run=unexpected))
    service._equipment = EquipmentCatalog(catalog.items)
    assert without_timings(
        service.optimize(snapshot, request, price_records=prices, now=now)
    ) == without_timings(optimize(snapshot, request, service._equipment, content, prices, now))


def test_service_remains_busy_until_failed_parallel_job_drains_then_recovers():
    snapshot, request, catalog, content, _prices, now = context()
    entered, drained = Event(), Event()

    def failed(*a, **kw):
        entered.set()
        assert drained.wait(10)
        raise ValueError("optimizer_worker_unavailable: test failure")

    pool = SimpleNamespace(run=failed)
    service = GearService(content, auto_pool=pool)
    service._equipment = EquipmentCatalog(catalog.items)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.optimize, snapshot, request, now=now)
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError, match="optimizer_busy"):
                service.optimize(snapshot, request, now=now)
        finally:
            drained.set()
        with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
            future.result(timeout=10)
    pool.run = serial_branches
    assert service.optimize(snapshot, request, now=now)["selected_solution"]
