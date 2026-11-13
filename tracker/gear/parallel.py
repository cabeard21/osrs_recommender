"""Desktop-owned spawned workers for independent concrete search alternatives."""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import os
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from functools import partial
from threading import Lock
from time import monotonic, sleep
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.estimation.prices import PriceRecord
from tracker.gear.auto import branch_requests
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.discipline_assignments import has_auto
from tracker.gear.optimizer import OptimizationRequest
from tracker.gear.parallel_payload import context_payload, decode_context, decode_job, job_payload
from tracker.gear.progress import SlotReader, SlotWriter, WorkerSlots
from tracker.gear.running_frontier import needs_running_cost_frontier

logger = logging.getLogger(__name__)
_CONTEXT: tuple[Content, EquipmentCatalog, str, Any] | None = None
_PREPARATION: tuple[str, Any] | None = None
_PROGRESS: tuple[WorkerSlots, int] | None = None
_UNAVAILABLE = "optimizer_worker_unavailable: desktop workers unavailable; retry the calculation"


class _CancellationFlag:
    """One parent writes one shared byte; child polling never acquires a semaphore.

    A killed child cannot leave the cancellation token locked. The desktop's
    single-byte shared-memory reads/writes require no compound read-modify-write.
    """

    def __init__(self, context: Any) -> None:
        self._value = context.RawValue("b", 0)

    def is_set(self) -> bool:
        return bool(self._value.value)

    def set(self) -> None:
        self._value.value = 1

    def clear(self) -> None:
        self._value.value = 0

    def wait(self, timeout: float) -> bool:
        deadline = monotonic() + timeout
        while not self.is_set() and monotonic() < deadline:
            sleep(0.005)
        return self.is_set()


def _initialize(
    payload: dict[str, Any],
    identity: str,
    stopped: Any,
    ready: Any,
    slots: WorkerSlots | None = None,
    native_required: bool = False,
) -> None:
    global _CONTEXT, _PREPARATION, _PROGRESS
    if native_required:
        from tracker.gear.native.readiness import require_native

        require_native()
    content, catalog = decode_context(payload, identity)
    _CONTEXT = content, catalog, identity, stopped
    _PREPARATION = None
    # Ensure startup has initialized every child, not just one quick warmup task.
    # The barrier index is unique per child, so it doubles as this child's slot.
    index = ready.wait(timeout=30)
    _PROGRESS = (slots, index) if slots is not None else None


def _warm() -> int:
    return os.getpid()


def _execute_branch(
    payload: dict[str, Any], options: dict[str, Any], lane: int | None = None
) -> dict[str, Any]:
    from tracker.gear.optimizer import optimize, prepare_optimization

    global _PREPARATION

    if _CONTEXT is None:
        raise ValueError(_UNAVAILABLE)
    content, catalog, identity, stopped = _CONTEXT
    snapshot, request, prices, now = decode_job(payload, identity)
    if request.potions.mode != "fixed" and has_auto(request):
        raise ValueError("Worker requires concrete disciplines")
    prepared = None
    if request.potions.mode == "fixed":
        # Decode/validate every job before consulting the single-entry cache. The
        # entire frozen input identity participates except the boost selection.
        base_request = {k: v for k, v in payload["request"].items() if k != "potions"}
        base_payload = {**payload, "request": base_request}
        key = hashlib.sha256(
            json.dumps(base_payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        if _PREPARATION is None or _PREPARATION[0] != key:
            _PREPARATION = (
                key,
                prepare_optimization(snapshot, request, catalog, content, prices, now),
            )
        prepared = _PREPARATION[1]
    progress = (
        SlotWriter(_PROGRESS[0], _PROGRESS[1], lane)
        if lane is not None and _PROGRESS is not None and isinstance(_PROGRESS[1], int)
        else None
    )
    from contextlib import nullcontext

    from tracker.gear.native import capture

    with capture() if options.get("_native_search") else nullcontext(None) as evidence:
        result = optimize(
            snapshot,
            request,
            catalog,
            content,
            prices,
            now,
            cancelled=stopped.is_set,
            _complete_frontiers=True,
            _prepared=prepared,
            progress=progress,
            **options,
        )
    if evidence is None:
        return result
    return {"_native_payload": result, "_native_evidence": evidence.snapshot()}


class AutoProcessPool:
    """One app's warm pool; a request owns its cancellation token until all jobs drain."""

    GRACE_SECONDS = 5.0
    REAP_SECONDS = 1.0

    def __init__(self, workers: int) -> None:
        if type(workers) is not int or not 1 <= workers <= 6:
            raise ValueError("Gear worker count must be an integer from one through six")
        self.workers = workers
        self._context = multiprocessing.get_context("spawn")
        self._run_lock = Lock()
        self._closed = False
        self._executor: ProcessPoolExecutor | None = None
        self._payload: dict[str, Any] | None = None
        self._identity: str | None = None
        self._stopped: Any = None
        self._slots: WorkerSlots | None = None
        self._unsafe_children: tuple[Any, ...] = ()
        self._unsafe_manager: Any = None
        self._native_required = False

    def _new_executor(self) -> ProcessPoolExecutor:
        assert self._payload is not None and self._identity is not None
        return ProcessPoolExecutor(
            max_workers=self.workers,
            mp_context=self._context,
            initializer=partial(
                _initialize,
                self._payload,
                self._identity,
                self._stopped,
                self._context.Barrier(self.workers),
                self._slots,
                self._native_required,
            ),
        )

    def _build(self) -> None:
        self._stopped = _CancellationFlag(self._context)
        self._slots = WorkerSlots(self._context, self.workers)
        try:
            self._executor = self._new_executor()
            futures = [self._executor.submit(_warm) for _ in range(self.workers)]
            for future in futures:
                future.result(timeout=35)
        except Exception as error:
            self._stopped.set()
            self._dispose()
            raise ValueError(_UNAVAILABLE) from error

    def start(
        self, content: Content, catalog: EquipmentCatalog, *, native_required: bool = False
    ) -> None:
        if type(native_required) is not bool:
            raise ValueError("native_required must be a boolean")
        if native_required:
            from tracker.gear.native.readiness import require_native

            require_native()
        payload, identity = context_payload(content, catalog)
        with self._run_lock:
            if self._closed:
                raise ValueError(_UNAVAILABLE)
            if self._identity is not None and self._identity != identity:
                raise ValueError("optimizer_worker_context_mismatch")
            if self._executor is not None and self._native_required != native_required:
                raise ValueError("optimizer_worker_native_context_mismatch")
            self._native_required = native_required
            self._payload, self._identity = payload, identity
            if self._executor is None:
                self._build()

    def _dispose(self, *, force: bool = False) -> None:
        executor, self._executor = self._executor, None
        if executor is not None:
            # Python 3.12 has no public terminate_workers API. Capture only this
            # executor's owned Process handles before shutdown detaches them.
            children = tuple((getattr(executor, "_processes", None) or {}).values())
            manager = getattr(executor, "_executor_manager_thread", None)
            if manager is not None:
                self._unsafe_manager = manager
            try:
                executor.shutdown(wait=False, cancel_futures=True)
                if manager is not None and not force:
                    manager.join(timeout=self.GRACE_SECONDS)
            except Exception:
                logger.exception("Desktop Gear worker shutdown failed")
            try:
                self._stop_children(children)
            finally:
                self._join_manager(manager)

    def _join_manager(self, manager: Any) -> None:
        if manager is None:
            return
        self._unsafe_manager = manager
        try:
            manager.join(timeout=self.REAP_SECONDS)
        except RuntimeError:
            # A thread which never started has nothing to reap. A live manager
            # must remain retained even if its join failed during shutdown.
            logger.exception("Desktop Gear worker manager join failed")
        if manager.is_alive():
            self._closed = True
            raise ValueError(_UNAVAILABLE)
        self._unsafe_manager = None

    def _stop_children(self, children: tuple[Any, ...]) -> None:
        for child in children:
            if child.is_alive():
                try:
                    child.terminate()
                except Exception:
                    logger.exception("Desktop Gear child termination failed")
        for child in children:
            child.join(timeout=self.REAP_SECONDS)
            if child.is_alive():
                try:
                    child.kill()
                except Exception:
                    logger.exception("Desktop Gear child kill failed")
                child.join(timeout=self.REAP_SECONDS)
        self._unsafe_children = tuple(child for child in children if child.is_alive())
        if self._unsafe_children:
            # Never rebuild alongside a child the OS refused to stop. Preserve
            # the cancellation flag and fail closed until a desktop restart.
            self._closed = True
            raise ValueError(_UNAVAILABLE)

    def close(self) -> None:
        self._closed = True
        if self._stopped is not None:
            self._stopped.set()
        with self._run_lock:
            if self._unsafe_children:
                self._stop_children(self._unsafe_children)
            if self._unsafe_manager is not None:
                self._join_manager(self._unsafe_manager)
            self._dispose()

    def _abort(self, futures: list[Future[dict[str, Any]]]) -> bool:
        """Drain actual running jobs before another request can clear their token."""
        self._stopped.set()
        broken = False
        for future in futures:
            future.cancel()
        deadline = monotonic() + self.GRACE_SECONDS
        while any(not future.done() for future in futures):
            if monotonic() >= deadline:
                self._dispose(force=True)
                return True
            sleep(0.01)
        for future in futures:
            try:
                future.result()
            except BrokenProcessPool:
                broken = True
            except BaseException:
                # Cancellation/worker exceptions have already failed the whole request.
                # Every future is still consumed so none can outlive this job's token.
                continue
        return broken

    def _dispatch(
        self,
        jobs: list[dict[str, Any]],
        options: dict[str, Any],
        cancelled: Any,
        progress: Any = None,
    ) -> list[dict[str, Any]]:
        futures: list[Future[dict[str, Any]]] = []
        try:
            assert self._executor is not None
            if self._slots is not None:
                self._slots.clear()
            lanes: dict[Future[dict[str, Any]], int] = {}
            for lane, job in enumerate(jobs):
                future = self._executor.submit(_execute_branch, job, options, lane)
                futures.append(future)
                lanes[future] = lane
            reader = (
                SlotReader(self._slots, progress)
                if progress is not None and self._slots is not None
                else None
            )
            pending = set(futures)
            started = monotonic()
            while pending:
                if self._closed or (cancelled is not None and cancelled()):
                    raise ValueError("optimization_cancelled")
                completed, pending = wait(pending, timeout=0.025, return_when=FIRST_COMPLETED)
                for future in completed:
                    future.result()
                if reader is not None:
                    reader.poll()
                if progress is None:
                    continue
                for future in sorted(completed, key=lanes.__getitem__):
                    progress(
                        {
                            "phase": "potion_search",
                            "lane": lanes[future],
                            "lane_status": "complete",
                            "completed_profiles": len(futures) - len(pending),
                            "total_profiles": len(futures),
                            "elapsed_seconds": monotonic() - started,
                        }
                    )
            if self._closed or (cancelled is not None and cancelled()):
                raise ValueError("optimization_cancelled")
            results = [future.result() for future in futures]
            if options.get("_native_search"):
                from tracker.gear.native import merge

                for row in results:
                    merge(row["_native_evidence"])
                return [row["_native_payload"] for row in results]
            return results
        except BaseException as error:
            broken = self._abort(futures) or isinstance(error, BrokenProcessPool)
            if broken:
                self._dispose()
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            if str(error) == "optimization_cancelled":
                raise ValueError("optimization_cancelled") from error
            raise ValueError(_UNAVAILABLE) from error

    def run_potions(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        catalog: EquipmentCatalog,
        content: Content,
        price_records: Mapping[int, PriceRecord],
        now: datetime,
        *,
        branches: list[OptimizationRequest],
        progress: Any = None,
        **options: Any,
    ) -> list[dict[str, Any]]:
        """Run frozen potion setups through the same bounded, cancellable desktop pool."""
        cancelled = options.pop("cancelled", None)
        if self._closed or self._identity is None:
            raise ValueError(_UNAVAILABLE)
        if cancelled is not None and cancelled():
            raise ValueError("optimization_cancelled")
        if not self._run_lock.acquire(blocking=False):
            raise ValueError("optimizer_busy: another desktop worker job is running")
        try:
            if context_payload(content, catalog)[1] != self._identity:
                raise ValueError("optimizer_worker_context_mismatch")
            from tracker.gear.evaluation import validate_request_context
            from tracker.gear.support import project_catalog

            projected = project_catalog(catalog, request.support_policy)
            validate_request_context(request, snapshot, projected.items, content)
            allowed = {
                "local_refinement",
                "targeted_head_refinement",
                "_complete_frontiers",
                "_running_frontier",
                "_fixed_reporting",
                "_factored_evaluation",
                "_compact_states",
                "_native_search",
            }
            from tracker.gear.execution_profile import validate_worker_options

            validate_worker_options(options, allowed)
            if not branches or any(branch.potions.mode != "fixed" for branch in branches):
                raise ValueError("Desktop potion workers require fixed potion branches")
            if self._executor is None:
                self._build()
            self._stopped.clear()
            jobs = [
                job_payload(snapshot, branch, price_records, now, self._identity)
                for branch in branches
            ]
            # _execute_branch always requests complete archives before global merging.
            selected = {
                key: value for key, value in options.items() if key != "_complete_frontiers"
            }
            return self._dispatch(jobs, selected, cancelled, progress)
        finally:
            if self._stopped is not None and not self._closed:
                self._stopped.clear()
            self._run_lock.release()

    def run(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        catalog: EquipmentCatalog,
        content: Content,
        price_records: Mapping[int, PriceRecord],
        now: datetime,
        *,
        progress: Any = None,
        **options: Any,
    ) -> list[tuple[str, dict[str, Any]]]:
        cancelled = options.pop("cancelled", None)
        if self._closed or self._identity is None:
            raise ValueError(_UNAVAILABLE)
        if cancelled is not None and cancelled():
            raise ValueError("optimization_cancelled")
        if not self._run_lock.acquire(blocking=False):
            raise ValueError("optimizer_busy: another desktop worker job is running")
        try:
            return self._run(
                snapshot,
                request,
                catalog,
                content,
                price_records,
                now,
                options,
                cancelled,
                progress,
            )
        finally:
            if self._stopped is not None and not self._closed:
                self._stopped.clear()
            self._run_lock.release()

    def _run(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest,
        catalog: EquipmentCatalog,
        content: Content,
        prices: Mapping[int, PriceRecord],
        now: datetime,
        options: dict[str, Any],
        cancelled: Any,
        progress: Any = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        if self._closed:
            raise ValueError(_UNAVAILABLE)
        if context_payload(content, catalog)[1] != self._identity:
            raise ValueError("optimizer_worker_context_mismatch")
        from tracker.gear.execution_profile import validate_worker_options

        validate_worker_options(
            options,
            {
                "local_refinement",
                "targeted_head_refinement",
                "_fixed_reporting",
                "_factored_evaluation",
                "_compact_states",
                "_native_search",
            },
        )
        if not has_auto(request):
            raise ValueError("Desktop workers require Auto")
        if self._executor is None:
            self._build()  # A broken pool is recreated only for a fresh request.
        self._stopped.clear()
        branches = list(branch_requests(request))
        assert self._identity is not None
        jobs = [
            job_payload(snapshot, concrete, prices, now, self._identity) for _, concrete in branches
        ]
        selected = {**options, "_running_frontier": needs_running_cost_frontier(request)}
        results = self._dispatch(jobs, selected, cancelled, progress)
        return [
            (discipline, result) for (discipline, _), result in zip(branches, results, strict=True)
        ]
