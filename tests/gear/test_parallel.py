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


@pytest.mark.parametrize("workers", [0, 4, True])
def test_worker_capacity_is_bounded(workers):
    with pytest.raises(ValueError):
        AutoProcessPool(workers)


def test_real_spawn_branches_match_serial_and_reuse_pool():
    snapshot, request, catalog, content, prices, now = inputs()
    pool = AutoProcessPool(2)
    try:
        pool.start(content, catalog)
        for _ in range(2):
            rows = pool.run(snapshot, request, catalog, content, prices, now)
            assert [discipline for discipline, _ in rows] == ["melee", "ranged", "magic"]
            for (discipline, concrete), (returned, result) in zip(
                branch_requests(request), rows, strict=True
            ):
                assert discipline == returned
                assert result == optimize(
                    snapshot,
                    concrete,
                    catalog,
                    content,
                    prices,
                    now,
                    _complete_frontiers=True,
                    _running_frontier=True,
                )
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


def fake_pool(monkeypatch):
    pool = AutoProcessPool(2)
    executors = []

    def create():
        executor = FakeExecutor(pool)
        executors.append(executor)
        return executor

    monkeypatch.setattr(pool, "_new_executor", create)
    _, _, catalog, content, _, _ = inputs()
    pool.start(content, catalog)
    return pool, executors


def test_cancellation_drains_before_reuse(monkeypatch):
    pool, executors = fake_pool(monkeypatch)
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


def test_broken_worker_fails_current_request_and_rebuilds_next(monkeypatch):
    pool, executors = fake_pool(monkeypatch)
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


def test_real_crashed_worker_is_rebuilt_for_next_request():
    snapshot, request, catalog, content, prices, now = inputs()
    pool = AutoProcessPool(2)
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


def test_unresponsive_children_are_stopped_before_cancel_returns_and_pool_recovers(monkeypatch):
    from tracker.gear import parallel

    args = inputs()
    pool = AutoProcessPool(2)
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
