"""Frozen 119-item objective scaling checks, isolated per measured run.

Run latency and --memory separately. Results stay in ignored .tmp paths; the
fixture is a redacted substitute account, never a replay of a live account.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.benchmark_gear_desktop import case_provenance, environment, without_observations
from tools.gear_process_memory import measure_process_tree
from tools.gear_search_quality_fixture import load_case
from tracker.gear.native import capture
from tracker.gear.objectives import STYLES, canonical_objectives, objective_policy
from tracker.gear.optimizer import OptimizationRequest, optimize

COUNTS = (1, 3, 8, 62)


def objective_set(count: int) -> tuple[Any, ...]:
    if count not in COUNTS:
        raise ValueError("Objective count must be one of 1, 3, 8, or 62")
    if count <= 3:
        values = [
            {"kind": "defence_roll", "styles": [style], "aggregation": "minimum"}
            for style in ("slash", "ranged", "magic")[:count]
        ]
    elif count == 8:
        values = [
            {"kind": "defence_roll", "styles": [style], "aggregation": "minimum"}
            for style in STYLES
        ] + [{"kind": kind} for kind in ("prayer_bonus", "melee_strength_bonus", "accuracy")]
    else:
        values = [
            {"kind": "defence_roll", "styles": styles, "aggregation": aggregation}
            for size in range(1, 6)
            for styles in combinations(STYLES, size)
            for aggregation in ("minimum", "mean")
        ] + [
            {"kind": kind}
            for kind in (
                "prayer_bonus",
                "melee_strength_bonus",
                "ranged_strength_bonus",
                "magic_damage_bonus",
                "accuracy",
            )
        ]
    result = canonical_objectives(values)
    if len(result) != count:
        raise ValueError("Canonical objective count changed")
    return result


def benchmark_case(count: int) -> Any:
    case = load_case("melee_1m")
    if len(case.catalog.items) != 119:
        raise ValueError("Expected the frozen 119-item catalog")
    request = OptimizationRequest.model_validate(
        {
            **case.request.model_dump(mode="json"),
            "secondary_priority": "default",
            "objectives": [value.model_dump(mode="json") for value in objective_set(count)],
            "max_dps_loss_pct": 100,
        }
    )
    return replace(case, request=request)


def _hash(value: Any) -> str:
    encoded = json.dumps(without_observations(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    files = {
        *root.glob("tracker/gear/vector_*.py"),
        *root.glob("tracker/gear/native/*.py"),
        *root.glob("tracker/gear/native/*.pyx"),
        *root.glob("tracker/gear/native/*.pxd"),
        root / "tracker/gear/native/_build.json",
        *(
            root / "tracker/gear" / name
            for name in (
                "optimizer.py",
                "objectives.py",
                "auto.py",
                "potion_search.py",
                "running_frontier.py",
            )
        ),
    }
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file()
    }


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for group in result.get("objective_frontiers", []):
        digest = hashlib.sha256()
        count = 0
        for point in group["points"]:
            digest.update(_hash(point["solution"]).encode())
            count += 1
        groups.append(
            {"swap_limit": group["swap_limit"], "count": count, "sha256": digest.hexdigest()}
        )
    values = {
        "selected": _hash(result.get("selected_solution")),
        "unrestricted": _hash(result.get("unrestricted")),
        "curve": [_hash(row.get("solution")) for row in result["curve"]],
        "groups": groups,
    }
    return {**values, "full_solution_digest": _hash(values)}


def _close_result(result: dict[str, Any] | None) -> None:
    if result is None:
        return
    seen = set()
    for detail in [result, *result.get("discipline_results", [])]:
        for group in detail.get("objective_frontiers", []):
            points = group["points"]
            if id(points) not in seen:
                seen.add(id(points))
                close = getattr(points, "close", None)
                if close is not None:
                    close()


def run(count: int, *, native: bool, memory: bool, timeout: float) -> dict[str, Any]:
    case = benchmark_case(count)
    result = None
    stats = None
    evidence = None
    measurement: dict[str, Any] = {
        "objective_count": count,
        "native": native,
        "memory_instrumented": memory,
        "cancel_after_seconds": timeout,
        "provenance": case_provenance(case, account_source="redacted frozen substitute fixture"),
        "objective_policy": objective_policy(case.request.objectives),
        "source_hashes_before": source_hashes(),
    }
    started = perf_counter()
    try:
        with capture() as evidence, measure_process_tree() if memory else nullcontext() as stats:
            result = optimize(
                case.snapshot,
                case.request,
                case.catalog,
                case.content,
                case.prices,
                case.at,
                _execution_profile="combined",
                _fixed_reporting=True,
                _factored_evaluation=True,
                _compact_states=True,
                _complete_frontiers=True,
                _native_search=native,
                cancelled=lambda: perf_counter() - started >= timeout,
            )
            measurement["search_seconds"] = perf_counter() - started
            measurement["status"] = "complete"
            measurement["result"] = result_summary(result)
            measurement["search"] = result["search"]
            measurement["native_evidence"] = evidence.snapshot()
            if native and evidence.snapshot()["fallback_requests"]:
                measurement["status"] = "native_fallback"
    except ValueError as exc:
        measurement["status"] = "cancelled" if str(exc) == "optimization_cancelled" else "failed"
        measurement["error"] = str(exc)
    finally:
        measurement["elapsed_seconds"] = perf_counter() - started
        if evidence is not None:
            measurement["native_evidence"] = evidence.snapshot()
        measurement["source_hashes_after"] = source_hashes()
        measurement["sources_stable"] = (
            measurement["source_hashes_before"] == measurement["source_hashes_after"]
        )
        _close_result(result)
        if stats is not None:
            measurement["memory"] = stats.report()
    return measurement


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", choices=COUNTS, default=list(COUNTS))
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", type=int, choices=COUNTS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker is not None:
        value = run(
            args.worker, native=args.native, memory=args.memory, timeout=args.timeout_seconds
        )
        args.output.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return
    rows = []
    report = {"environment": environment(), "runs": rows}
    for count in args.counts:
        path = args.output.with_name(f"{args.output.stem}-{count}{args.output.suffix}")
        command = [
            sys.executable,
            "-m",
            "tools.benchmark_objectives",
            "--worker",
            str(count),
            "--output",
            str(path),
            "--timeout-seconds",
            str(args.timeout_seconds),
            *(["--native"] if args.native else []),
            *(["--memory"] if args.memory else []),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=args.timeout_seconds + 30
            )
            row = (
                json.loads(path.read_text())
                if completed.returncode == 0
                else {
                    "objective_count": count,
                    "status": "failed",
                    "stderr": completed.stderr[-4000:],
                }
            )
        except subprocess.TimeoutExpired:
            row = {
                "objective_count": count,
                "status": "hard_timeout",
                "timeout_seconds": args.timeout_seconds + 30,
            }
        rows.append(row)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    key: row.get(key)
                    for key in ("objective_count", "status", "search_seconds", "elapsed_seconds")
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
