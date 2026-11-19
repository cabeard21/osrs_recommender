"""Spawned Auto workers preserve order, ownership and cancellation boundaries."""

import os
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from threading import Thread
from time import monotonic, sleep

import pytest

from tests.gear.test_auto_disciplines import context
from tracker.gear.auto import branch_requests
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.optimizer import optimize
from tracker.gear.parallel import AutoProcessPool


def unresponsive_branch(*args):
    sleep(30)
    return {}


def inputs():
    snapshot, request, catalog, content, prices, now = context()
    return snapshot, request, EquipmentCatalog(catalog.items), content, prices, now


def test_native_worker_checks_release_readiness_before_barrier(monkeypatch):
    from types import SimpleNamespace

    from tracker.gear import parallel
    from tracker.gear.native import readiness

    calls = []
    monkeypatch.setattr(parallel, "decode_context", lambda *_: (None, None))
    monkeypatch.setattr(readiness, "require_native", lambda: calls.append("native"))
    barrier = SimpleNamespace(wait=lambda **_: calls.append("barrier") or 0)
    parallel._initialize({}, "test", None, barrier, native_required=True)
    assert calls == ["native", "barrier"]


def test_native_pool_validates_before_creating_processes(monkeypatch):
    from tracker.gear.native import readiness

    _, _, catalog, content, _, _ = inputs()

    def missing():
        raise RuntimeError("native missing")

    monkeypatch.setattr(readiness, "require_native", missing)
    pool = AutoProcessPool(6)
    try:
        with pytest.raises(RuntimeError, match="native missing"):
            pool.start(content, catalog, native_required=True)
        assert pool._executor is None
    finally:
        pool.close()


@pytest.mark.parametrize("potion", [False, True])
def test_native_pool_rejects_python_job_before_dispatch(monkeypatch, potion):
    from tracker.gear.native import readiness
    from tracker.gear.potions import PotionPolicy

    monkeypatch.setattr(readiness, "require_native", lambda: None)
    pool, executors = fake_pool(monkeypatch, native_required=True)
    args = inputs()
    branches = [args[1].model_copy(update={"potions": PotionPolicy(mode="fixed")})]
    try:
        with pytest.raises(RuntimeError, match="requires native"):
            if potion:
                pool.run_potions(*args, branches=branches)
            else:
                pool.run(*args)
        assert not executors[0].jobs
    finally:
        pool.close()


def without_timings(value):
    if isinstance(value, dict):
        return {key: without_timings(row) for key, row in value.items() if key != "timings_seconds"}
    if isinstance(value, list):
        return [without_timings(row) for row in value]
    return value


@pytest.mark.parametrize("workers", [0, 7, -1, True, False, 1.0, 1.5, "2", None])
def test_worker_capacity_is_bounded(workers):
    with pytest.raises(ValueError):
        AutoProcessPool(workers)


@pytest.mark.parametrize("workers", range(1, 7))
def test_worker_capacity_accepts_supported_integers(workers):
    pool = AutoProcessPool(workers)
    try:
        assert pool.workers == workers
    finally:
        pool.close()


@pytest.mark.parametrize("multi", [False, True, "auto"])
def test_potion_workers_match_serial_for_concrete_and_multi_roles(multi):
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = inputs()
    roles = (RoleConfig(id="melee", style="slash"),)
    if multi is True:
        roles = (*roles, RoleConfig(id="ranged", style="ranged"))
    if multi == "auto":
        roles = request.roles
    request = request.model_copy(update={"roles": roles})
    branches = [
        request.model_copy(update={"potions": PotionPolicy(mode="fixed", selected_ids=ids)})
        for ids in ((), ("super_strength",))
    ]
    progress = []
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        results = pool.run_potions(
            snapshot,
            request,
            catalog,
            content,
            prices,
            now,
            branches=branches,
            progress=progress.append,
        )
        expected = [
            optimize(snapshot, branch, catalog, content, prices, now, _complete_frontiers=True)
            for branch in branches
        ]
        assert without_timings(results) == without_timings(expected)
        assert progress[-1]["completed_profiles"] == len(branches)
        assert progress[-1]["total_profiles"] == len(branches)
    finally:
        pool.close()


def test_potion_pool_cancellation_drains_and_recovers(monkeypatch):
    from tracker.gear.potions import PotionPolicy

    args = inputs()
    request = args[1].model_copy(update={"potions": PotionPolicy(mode="fixed")})
    pool, executors = fake_pool(monkeypatch)
    executors[0].block = True
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) > 1

    try:
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run_potions(*args, branches=[request], cancelled=cancelled)
        assert all(job.done() for job in executors[0].jobs)
        executors[0].block = False
        assert len(pool.run_potions(*args, branches=[request])) == 1
    finally:
        pool.close()


def test_worker_preparation_reuses_only_identical_validated_base_inputs(monkeypatch):
    from types import SimpleNamespace

    from tracker.gear import optimizer, parallel
    from tracker.gear.parallel_payload import context_payload, job_payload
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = inputs()
    request = request.model_copy(update={"potions": PotionPolicy(mode="fixed")})
    identity = context_payload(content, catalog)[1]
    monkeypatch.setattr(
        parallel, "_CONTEXT", (content, catalog, identity, SimpleNamespace(is_set=lambda: False))
    )
    monkeypatch.setattr(parallel, "_PREPARATION", None)
    preparations = []

    def prepare(*args):
        preparations.append(object())
        return preparations[-1]

    monkeypatch.setattr(optimizer, "prepare_optimization", prepare)
    monkeypatch.setattr(optimizer, "optimize", lambda *args, **kwargs: kwargs["_prepared"])
    first = parallel._execute_branch(job_payload(snapshot, request, prices, now, identity), {})
    boosted = request.model_copy(
        update={"potions": PotionPolicy(mode="fixed", selected_ids=("super_strength",))}
    )
    assert (
        parallel._execute_branch(job_payload(snapshot, boosted, prices, now, identity), {}) is first
    )
    changed_request = request.model_copy(update={"budget_gp": request.budget_gp + 1})
    second = parallel._execute_branch(
        job_payload(snapshot, changed_request, prices, now, identity), {}
    )
    assert second is not first
    changed_snapshot = replace(snapshot, username="changed")
    third = parallel._execute_branch(
        job_payload(changed_snapshot, changed_request, prices, now, identity), {}
    )
    assert third is not second
    price = SimpleNamespace(
        item_id=2436,
        high_price_gp=100,
        high_trade_at=now,
        low_price_gp=90,
        low_trade_at=now,
        fetched_at=now,
        source="live",
    )
    fourth = parallel._execute_branch(
        job_payload(changed_snapshot, changed_request, {2436: price}, now, identity), {}
    )
    assert fourth is not third
    invalid = job_payload(changed_snapshot, changed_request, prices, now, identity)
    invalid["snapshot_id"] = "invalid"
    with pytest.raises(ValueError, match="fingerprint_mismatch"):
        parallel._execute_branch(invalid, {})
    assert len(preparations) == 4


def test_potion_pool_validates_base_context_before_dispatch(monkeypatch):
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = inputs()
    request = request.model_copy(
        update={"excluded_item_ids": (999999,), "potions": PotionPolicy(mode="fixed")}
    )
    pool, executors = fake_pool(monkeypatch)
    try:
        with pytest.raises(ValueError) as serial:
            optimize(snapshot, request, catalog, content, prices, now)
        with pytest.raises(ValueError) as pooled:
            pool.run_potions(snapshot, request, catalog, content, prices, now, branches=[request])
        assert str(serial.value) == str(pooled.value)
        assert not executors[0].jobs
    finally:
        pool.close()


@pytest.mark.parametrize("workers", [2, 4, 6])
def test_real_spawn_branches_match_serial_and_reuse_pool(workers):
    snapshot, request, catalog, content, prices, now = inputs()
    pool = AutoProcessPool(workers)
    try:
        pool.start(content, catalog)
        for _ in range(2):
            rows = pool.run(snapshot, request, catalog, content, prices, now)
            assert [discipline for discipline, _ in rows] == ["melee", "ranged", "magic"]
            for (discipline, concrete), (returned, result) in zip(
                branch_requests(request), rows, strict=True
            ):
                assert discipline == returned
                expected = optimize(
                    snapshot,
                    concrete,
                    catalog,
                    content,
                    prices,
                    now,
                    _complete_frontiers=True,
                    _running_frontier=True,
                )
                assert without_timings(result) == without_timings(expected)
    finally:
        pool.close()
        pool.close()


class FakeExecutor:
    def __init__(self, pool):
        self.pool = pool
        self.closed = False
        self.broken = False
        self.block = False
        self.jobs = []
        self.workers = []

    def submit(self, function, *args):
        future = Future()
        if not args:
            future.set_result(1)
            return future
        if self.broken:
            raise BrokenProcessPool("worker crashed with private details")
        self.jobs.append(future)
        style = args[0]["request"]["roles"][0]["style"]
        if not self.block:
            future.set_result({"style": style})
            return future
        future.set_running_or_notify_cancel()

        def finish():
            self.pool._stopped.wait(timeout=5)
            future.set_exception(ValueError("optimization_cancelled"))

        worker = Thread(target=finish)
        self.workers.append(worker)
        worker.start()
        return future

    def shutdown(self, wait=True, cancel_futures=True):
        self.closed = True
        for worker in self.workers:
            worker.join(timeout=5)


def fake_pool(monkeypatch, workers=2, *, native_required=False):
    pool = AutoProcessPool(workers)
    executors = []

    def create():
        executor = FakeExecutor(pool)
        executors.append(executor)
        return executor

    monkeypatch.setattr(pool, "_new_executor", create)
    _, _, catalog, content, _, _ = inputs()
    pool.start(content, catalog, native_required=native_required)
    return pool, executors


def test_worker_archive_ownership_is_adopted_on_caller_thread(monkeypatch):
    import pickle
    from pathlib import Path

    from tracker.gear.vector_archive import VectorArchive, own_vector_archives
    from tracker.gear.vector_publish import FrontierPoints

    producer = VectorArchive(())
    transferred = pickle.loads(pickle.dumps(FrontierPoints(producer, 0)))
    # The sending worker has finished; only its transferred file remains live.
    producer.connection.close()
    producer._connection = None
    path = Path(producer.path)
    pool, executors = fake_pool(monkeypatch)

    def completed(*args):
        future = Future()
        future.set_result({"objective_frontiers": [{"points": transferred}]})
        return future

    monkeypatch.setattr(executors[0], "submit", completed)

    @own_vector_archives
    def discard_consumed_branch():
        pool._dispatch([{}], {}, None)

    try:
        discard_consumed_branch()
        assert not path.exists()
    finally:
        producer.close()
        pool.close()


@pytest.mark.parametrize("workers", [2, 6])
def test_cancellation_drains_before_reuse(monkeypatch, workers):
    pool, executors = fake_pool(monkeypatch, workers)
    executors[0].block = True
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) > 1

    try:
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(*inputs(), cancelled=cancelled)
        assert executors[0].jobs
        assert all(future.done() for future in executors[0].jobs)
        assert not pool._stopped.is_set()
        executors[0].block = False
        assert len(pool.run(*inputs())) == 3
    finally:
        pool.close()


@pytest.mark.parametrize("workers", [2, 6])
def test_broken_worker_fails_current_request_and_rebuilds_next(monkeypatch, workers):
    pool, executors = fake_pool(monkeypatch, workers)
    executors[0].broken = True
    try:
        with pytest.raises(ValueError, match="optimizer_worker_unavailable") as error:
            pool.run(*inputs())
        assert "private details" not in str(error.value)
        assert executors[0].closed
        assert len(pool.run(*inputs())) == 3
        assert len(executors) == 2
    finally:
        pool.close()


def test_context_changes_and_closed_pool_fail_cleanly(monkeypatch):
    pool, executors = fake_pool(monkeypatch)
    snapshot, request, catalog, content, prices, now = inputs()
    try:
        with pytest.raises(ValueError, match="context"):
            pool.run(snapshot, request, replace(catalog, revision="new"), content, prices, now)
        assert not executors[0].jobs
    finally:
        pool.close()
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        pool.run(*inputs())


def test_close_cancels_active_job_and_busy_state_is_preserved(monkeypatch):
    pool, executors = fake_pool(monkeypatch)
    executors[0].block = True
    errors = []

    def run():
        try:
            pool.run(*inputs())
        except ValueError as error:
            errors.append(str(error))

    runner = Thread(target=run)
    runner.start()
    deadline = monotonic() + 5
    while not executors[0].jobs and monotonic() < deadline:
        sleep(0.005)
    try:
        assert executors[0].jobs
        with pytest.raises(ValueError, match="optimizer_busy"):
            pool.run(*inputs())
        pool.close()
    finally:
        pool.close()
        runner.join(timeout=5)
    assert not runner.is_alive()
    assert errors == ["optimization_cancelled"]
    assert all(future.done() for future in executors[0].jobs)
    assert executors[0].closed


def test_real_spawn_cancellation_then_new_request_works():
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.optimizer import CombatOptionFilters

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
    pool = AutoProcessPool(2)
    try:
        pool.start(case.content, case.catalog)
        started = monotonic()
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(
                case.snapshot,
                request,
                case.catalog,
                case.content,
                case.prices,
                case.at,
                cancelled=lambda: monotonic() - started > 0.05,
            )
        assert not pool._stopped.is_set()
        assert (
            len(pool.run(case.snapshot, request, case.catalog, case.content, case.prices, case.at))
            == 3
        )
    finally:
        pool.close()


def test_startup_failure_cleans_up_and_run_options_are_validated(monkeypatch):
    pool, _executors = fake_pool(monkeypatch)
    try:
        for options in ({"unexpected": True}, {"local_refinement": "yes"}):
            with pytest.raises(ValueError, match="worker options"):
                pool.run(*inputs(), **options)
    finally:
        pool.close()
    failing = AutoProcessPool(2)
    executor = FakeExecutor(failing)

    def failure(*args):
        future = Future()
        future.set_exception(RuntimeError("startup failed"))
        return future

    monkeypatch.setattr(executor, "submit", failure)
    monkeypatch.setattr(failing, "_new_executor", lambda: executor)
    _, _, catalog, content, _, _ = inputs()
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        failing.start(content, catalog)
    assert executor.closed
    failing.close()


@pytest.mark.parametrize("workers", [2, 6])
def test_real_crashed_worker_is_rebuilt_for_next_request(workers):
    snapshot, request, catalog, content, prices, now = inputs()
    pool = AutoProcessPool(workers)
    try:
        pool.start(content, catalog)
        crash = pool._executor.submit(os._exit, 1)
        with pytest.raises(BrokenProcessPool):
            crash.result(timeout=10)
        with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
            pool.run(snapshot, request, catalog, content, prices, now)
        assert pool._executor is None
        assert len(pool.run(snapshot, request, catalog, content, prices, now)) == 3
    finally:
        pool.close()


@pytest.mark.parametrize("workers", [2, 6])
def test_unresponsive_children_are_stopped_before_cancel_returns_and_pool_recovers(
    monkeypatch, workers
):
    from tracker.gear import parallel

    args = inputs()
    pool = AutoProcessPool(workers)
    monkeypatch.setattr(pool, "GRACE_SECONDS", 0.05)
    original = parallel._execute_branch
    try:
        pool.start(args[3], args[2])
        children = tuple(pool._executor._processes.values())
        monkeypatch.setattr(parallel, "_execute_branch", unresponsive_branch)
        started = monotonic()
        with pytest.raises(ValueError, match="optimization_cancelled"):
            pool.run(*args, cancelled=lambda: monotonic() - started > 0.1)
        assert monotonic() - started < 5
        assert all(not child.is_alive() for child in children)
        assert pool._executor is None
        monkeypatch.setattr(parallel, "_execute_branch", original)
        assert len(pool.run(*args)) == 3
    finally:
        pool.close()


def test_child_that_os_cannot_stop_poison_pool_instead_of_rebuilding(monkeypatch):
    pool, executors = fake_pool(monkeypatch)
    actions = []

    class Survivor:
        def is_alive(self):
            return True

        def terminate(self):
            actions.append("terminate")

        def kill(self):
            actions.append("kill")

        def join(self, timeout):
            assert timeout <= pool.REAP_SECONDS

    child = Survivor()
    executors[0]._processes = {12345: child}
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        pool.close()
    assert actions == ["terminate", "kill"]
    assert pool._unsafe_children == (child,)
    assert pool._stopped.is_set()
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        pool.run(*inputs())
    assert len(executors) == 1


def test_surviving_manager_poison_pool_and_close_can_retry_join(monkeypatch):
    pool, executors = fake_pool(monkeypatch)

    class Manager:
        alive = True

        def join(self, timeout):
            assert timeout <= pool.GRACE_SECONDS

        def is_alive(self):
            return self.alive

    manager = Manager()
    executors[0]._executor_manager_thread = manager
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        pool.close()
    assert pool._unsafe_manager is manager
    with pytest.raises(ValueError, match="optimizer_worker_unavailable"):
        pool.run(*inputs())
    assert len(executors) == 1
    manager.alive = False
    pool.close()
    assert pool._unsafe_manager is None


def test_ranged_only_auto_cost_frontier_matches_serial_worker():
    from types import SimpleNamespace

    from tests.gear.test_auto_disciplines import OPTIONS
    from tests.gear.test_optimizer import weapon
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.domain.types import Container
    from tracker.gear.objectives import ObjectiveDescriptor
    from tracker.gear.optimizer import RoleConfig

    snapshot, request, _, content, _, now = inputs()
    items = [
        weapon(806, "ranged", 1, attack_profiles=(("ranged", "rapid"),)),
        weapon(811, "ranged", 40, attack_profiles=(("ranged", "rapid"),)),
    ]
    snapshot = replace(
        snapshot,
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", now)
            for i in items
        },
    )
    catalog = EquipmentCatalog({i.id: i for i in items})
    prices = {
        i: SimpleNamespace(
            item_id=i,
            high_price_gp=gp,
            low_price_gp=gp,
            high_trade_at=now,
            low_trade_at=now,
            fetched_at=now,
            source="live",
        )
        for i, gp in [(806, 1), (811, 100)]
    }
    request = request.model_copy(
        update={
            "secondary_priority": "default",
            "objectives": (ObjectiveDescriptor(kind="gp_per_damage"),),
            "roles": (
                RoleConfig(
                    id="a", style="ranged", allowed_disciplines=("ranged",), combat_options=OPTIONS
                ),
            ),
            "max_dps_loss_pct": 100,
        }
    )
    pool = AutoProcessPool(1)
    try:
        pool.start(content, catalog)
        rows = pool.run(snapshot, request, catalog, content, prices, now)
        concrete = next(branch_requests(request))[1]
        expected = optimize(
            snapshot, concrete, catalog, content, prices, now, _complete_frontiers=True
        )
        for result in (rows[0][1], expected):
            archives = []
            for group in result["objective_frontiers"]:
                points = group["points"]
                group["points"] = list(points)
                archives.append(points.archive)
            for archive in set(archives):
                archive.close()
        assert without_timings(rows[0][1]) == without_timings(expected)
        auto = optimize(snapshot, request, catalog, content, prices, now)
        assert len(auto["objective_frontiers"][0]["points"]) == 2
        assert len(rows[0][1]["objective_frontiers"][0]["points"]) == 2
    finally:
        pool.close()
