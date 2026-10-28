"""Offline comparison of bounded refinement on frozen, redacted search fixtures.

Run ``python -m tools.benchmark_gear_search_quality`` from the repository root.
No database, account observations, catalog, routing or deployment is changed.
The two singles strategies are research controls, never application search paths.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import platform
import statistics
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.gear_retention_oracle import Case, tiny_cases
from tools.gear_search_quality_fixture import fixture_data, load_case
from tracker.gear.facts import equipment_fact
from tracker.gear.local_refinement import refine_completed
from tracker.gear.optimizer import SLOTS, _Search, _solution_key, optimize

ACCOUNT_CASES = ("owned_slash", "melee_1m", "melee_5m", "joint_four")
STRATEGIES = ("baseline", "single_pass", "iterated_singles", "local", "targeted")


def benchmark_case(name: str) -> Case:
    """Add diagnostic scenarios using the same frozen account facts and targets."""
    if name in ACCOUNT_CASES:
        return load_case(name)
    case = load_case("joint_four")
    melee, ranged = case.request.roles
    magic = melee.model_copy(update={"id": "magic", "style": "magic", "spell": "fire_bolt"})
    if name == "owned_ranged":
        roles = (ranged,)
    elif name == "owned_magic":
        roles = (magic,)
    elif name == "account_three":
        roles = (melee, ranged, magic)
    elif name == "account_four":
        roles = (melee, ranged, magic, melee.model_copy(update={"id": "melee_second"}))
    else:
        raise ValueError(f"Unknown benchmark case: {name}")
    request = case.request.model_copy(update={"roles": roles, "base_role": roles[0].id})
    return replace(case, name=name, request=request)


def _stable(value: Any) -> Any:
    """Timing is observational and cannot participate in deterministic equality."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k != "duration_seconds"}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(_stable(value), sort_keys=True).encode()).hexdigest()


def _seeds(winners: list[Any], unrestricted: Any) -> list[Any]:
    result = {}
    for solution in [winners[-1], unrestricted, *winners]:
        if solution is not None:
            key = json.dumps(solution["loadouts"], sort_keys=True)
            result.setdefault(key, solution)
    return list(result.values())


def _single_trials(search: _Search, seeds: list[Any]) -> Iterator[dict[str, dict[str, int]]]:
    for seed in seeds:
        original = {r: row["equipment"] for r, row in seed["loadouts"].items()}
        for role in search.request.roles:
            if role.style == "special":
                continue
            locks = set(search.request.locks) | set(role.locks)
            for slot in SLOTS:
                if slot in locks:
                    continue
                ids = sorted(i for i, item in search.eligible.items() if item.slot == slot)
                for item_id in [None, *ids]:
                    if original[role.id].get(slot) == item_id:
                        continue
                    equipment = {s: i for s, i in original[role.id].items() if s != slot}
                    if item_id is not None:
                        equipment = {**equipment, slot: item_id}
                    yield {**original, role.id: equipment}


def singles_control(case: Case, baseline: dict[str, Any], *, iterate: bool) -> dict[str, Any]:
    """Compare one-pass versus repeated exact singles under the same 2,000 cap."""
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    search = _Search(case.snapshot, case.request, case.catalog.items, facts, None)
    winners = [point["solution"] for point in baseline["curve"]]
    unrestricted = baseline["unrestricted"]
    seen: set[str] = set()
    attempts = valid = rounds = 0
    cache_before = len(search.performance_cache)
    started = perf_counter()
    exhausted = False
    while True:
        rounds += 1
        improved = False
        for assignments in _single_trials(search, _seeds(winners, unrestricted)):
            identity = json.dumps(assignments, sort_keys=True)
            if identity in seen:
                continue
            if attempts == 2000:
                exhausted = True
                break
            seen.add(identity)
            attempts += 1
            candidate = search.solution(assignments, None)
            if candidate is None:
                continue
            valid += 1
            if unrestricted is None or _solution_key(candidate) < _solution_key(unrestricted):
                unrestricted = candidate
                improved = True
            for limit in range(candidate["maximum_actions"], len(winners)):
                incumbent = winners[limit]
                if incumbent is None or _solution_key(candidate) < _solution_key(incumbent):
                    winners = [*winners[:limit], candidate, *winners[limit + 1 :]]
                    improved = True
        if exhausted or not iterate or not improved:
            break
    baseline_score = unrestricted["score"] if unrestricted else 0
    return {
        "selected_solution": winners[-1],
        "unrestricted": unrestricted,
        "curve": [
            {
                "swap_limit": point["swap_limit"],
                "status": "best_found" if solution else "no_feasible_solution_found",
                "solution": solution,
                "relative_performance": solution["score"] / baseline_score
                if solution and baseline_score
                else None,
            }
            for point, solution in zip(baseline["curve"], winners, strict=True)
        ],
        "search": {
            "explored_nodes": baseline["search"]["explored_nodes"],
            "research_singles": {
                "assignment_attempts": attempts,
                "valid_assignments": valid,
                "performance_cache_misses": len(search.performance_cache) - cache_before,
                "rounds": rounds,
                "duration_seconds": perf_counter() - started,
                "work_budget_exhausted": exhausted,
                "cache_note": "Separate research Search; baseline full-loadout cache not reused",
            },
        },
    }


def run(case: Case, strategy: str) -> dict[str, Any]:
    kwargs = {"local_refinement": True} if strategy == "local" else {}
    if strategy == "targeted":
        kwargs = {"targeted_head_refinement": True}
    result = optimize(
        case.snapshot, case.request, case.catalog, case.content, case.prices, case.at, **kwargs
    )
    if strategy in ("single_pass", "iterated_singles"):
        return singles_control(case, result, iterate=strategy == "iterated_singles")
    return result


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        *[
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ],
    ]


def _rss() -> tuple[int, int] | None:
    if platform.system() != "Windows":
        return None
    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(kernel.GetCurrentProcess()), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError()
    return counters.WorkingSetSize, counters.PeakWorkingSetSize


def memory_run(case: Case, strategy: str) -> dict[str, Any]:
    """Separate 10ms native Windows sampling; includes Python and loaded inputs."""
    samples = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.01):
            value = _rss()
            if value:
                samples.append(value[0])

    before = _rss()
    worker = threading.Thread(target=sample, daemon=True)
    worker.start()
    try:
        result = run(case, strategy)
    finally:
        stop.set()
        worker.join()
    after = _rss()
    return {
        "method": "Windows GetProcessMemoryInfo at 10ms, separate untimed run",
        "sampled_peak_rss_bytes": max(samples, default=after[0] if after else 0),
        "before_rss_bytes": before[0] if before else None,
        "process_lifetime_peak_bytes": after[1] if after else None,
        "result_hash": _digest(result),
    }


def cancellation_run(case: Case) -> dict[str, Any]:
    """Request cancellation immediately after trial 20 in a request-local Search."""
    baseline = run(case, "baseline")
    facts = {
        i: equipment_fact(case.snapshot, item, case.content, case.prices, case.at)
        for i, item in case.catalog.items.items()
    }
    search = _Search(case.snapshot, case.request, case.catalog.items, facts, None)
    original = search.solution
    calls = 0
    requested_at = None

    def solution(assignments: Any, limit: Any) -> Any:
        nonlocal calls, requested_at
        result = original(assignments, limit)
        calls += 1
        if calls == 20:
            requested_at = perf_counter()
        return result

    search.solution = solution  # type: ignore[method-assign]
    search.cancelled = lambda: requested_at is not None
    started = perf_counter()
    outcome = "completed"
    try:
        refine_completed(
            search,
            [point["solution"] for point in baseline["curve"]],
            baseline["unrestricted"],
            _solution_key,
        )
    except ValueError as error:
        outcome = str(error)
    finished = perf_counter()
    return {
        "method": "Request-local solution wrapper sets cancellation immediately after trial 20",
        "completed_trial_calls": calls,
        "outcome": outcome,
        "refinement_elapsed_seconds": finished - started,
        "seconds_after_cancel_request": finished - requested_at
        if requested_at is not None
        else None,
        "scope": "Direct helper cooperativeness; excludes baseline setup, HTTP and browser latency",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path(".tmp/search-quality-correction/benchmark.json")
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", nargs="*", default=list(ACCOUNT_CASES))
    parser.add_argument("--tiny", action="store_true", help="Also include finite oracle scenarios")
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--memory", action="store_true", help="Separate native Windows memory runs")
    parser.add_argument(
        "--cancellation", action="store_true", help="Measure direct helper cancellation"
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    cases = [benchmark_case(name) for name in args.cases]
    if args.tiny:
        cases.extend(tiny_cases())
    report: dict[str, Any] = {
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "fixture_provenance": fixture_data()["provenance"],
        "timing": "One warmup then serial measured runs; no network or live account reads",
        "cases": {},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        rows = {}
        for strategy in args.strategies:
            times = []
            responses = []
            for _ in range(args.repeats + 1):
                started = perf_counter()
                result = run(case, strategy)
                times.append(perf_counter() - started)
                responses.append(result)
            hashes = [_digest(response) for response in responses]
            row = {
                "warmup_seconds": times[0],
                "seconds": times[1:],
                "median_seconds": statistics.median(times[1:]),
                "deterministic": len(set(hashes)) == 1,
                "result_hashes": hashes,
                "selected_solution": result["selected_solution"],
                "search": result["search"],
            }
            helper = next(
                (
                    key
                    for key in ("local_refinement", "targeted_head_refinement", "research_singles")
                    if key in result["search"]
                ),
                None,
            )
            if helper is not None:
                durations = [
                    response["search"][helper]["duration_seconds"] for response in responses
                ]
                row["helper_warmup_seconds"] = durations[0]
                row["helper_seconds"] = durations[1:]
                row["helper_median_seconds"] = statistics.median(durations[1:])
            if args.memory:
                row["memory"] = memory_run(case, strategy)
            rows[strategy] = row
            report["cases"][case.name] = rows
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            score = result["selected_solution"]["score"] if result["selected_solution"] else None
            print(case.name, strategy, "score", score, "median", row["median_seconds"], flush=True)
        if args.cancellation:
            report["cases"][case.name]["cancellation"] = cancellation_run(case)
            args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
