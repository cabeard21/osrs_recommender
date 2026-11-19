"""Offline desktop baselines: python -m tools.benchmark_gear_desktop --help.

Private inputs and full responses belong in ignored .tmp directories. Memory and
profile instrumentation must run separately from latency measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import tracemalloc
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.gear_search_quality_fixture import load_case
from tools.profile_gear_frontiers import load_profile_case
from tracker.gear.objective_store import materialize_result_archives
from tracker.gear.objectives import BONUSES
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, optimize
from tracker.gear.parallel_payload import context_payload, decode_context, decode_job, job_payload
from tracker.gear.potions import PotionPolicy
from tracker.gear.prayers import PrayerPolicy
from tracker.gear.priorities import ROLL_METRICS
from tracker.gear.vector_publish import FrontierPoints

CASES = (
    "single_melee",
    "single_ranged",
    "single_magic",
    "multi",
    "auto",
    "potions",
    "defence_roll",
    "ranged_diagnostic",
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def without_observations(value: Any, path: tuple[str, ...] = ()) -> Any:
    """Retain logical search work and nested results, including Auto branches.

    Refinement full-cache growth measures report materialization, not assignments;
    lazy reporting deliberately changes it. Raw benchmark reports retain it.
    """
    if isinstance(value, dict):
        return {
            key: without_observations(row, (*path, key))
            for key, row in value.items()
            if key not in {"timings_seconds", "elapsed_seconds", "progress"}
            and not (
                key in {"duration_seconds", "performance_cache_misses"}
                and path[-1:] == ("local_refinement",)
                and "search" in path
            )
        }
    if isinstance(value, (tuple, list, FrontierPoints)):
        return [without_observations(row, path) for row in value]
    return value


def result_digest(result: dict[str, Any]) -> str:
    return _hash(without_observations(result))


def frozen_inputs(case: Any) -> dict[str, Any]:
    context, identity = context_payload(case.content, case.catalog)
    return {
        "context": context,
        "context_id": identity,
        "job": job_payload(case.snapshot, case.request, case.prices, case.at, identity),
    }


def case_provenance(case: Any, **extra: Any) -> dict[str, Any]:
    return {
        **extra,
        "snapshot_id": case.snapshot.fingerprint,
        "catalog_revision": case.catalog.revision,
        "catalog_items": len(case.catalog.items),
        "evaluated_at": case.at.isoformat(),
        "inputs_sha256": _hash(frozen_inputs(case)),
    }


def cost_objective_case(case: Any, provenance: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """Describe the effective diagnostic request, including the legacy scalar it replaces."""
    request = case.request.model_dump()
    descriptors = [*(request.get("objectives") or ()), {"kind": "gp_per_damage"}]
    priority = case.request.secondary_priority
    if priority in BONUSES or priority == "accuracy":
        descriptors.append({"kind": priority})
    elif priority in ROLL_METRICS:
        styles, aggregation = ROLL_METRICS[priority]
        descriptors.append({"kind": "defence_roll", "styles": styles, "aggregation": aggregation})
    cost_request = OptimizationRequest.model_validate(
        {**request, "secondary_priority": "default", "objectives": descriptors}
    )
    variant = replace(case, request=cost_request)
    metadata = {
        **provenance,
        "source_secondary_priority": case.request.secondary_priority,
        "diagnostic_objectives": [obj.id for obj in cost_request.objectives or ()],
    }
    return variant, case_provenance(variant, **metadata)


def load_benchmark_case(name: str) -> tuple[Any, dict[str, Any]]:
    if name not in CASES:
        raise ValueError(f"Unknown benchmark case: {name}")
    fixture = "joint_four" if name == "multi" else "melee_1m"
    case = load_case(fixture)
    if name != "multi":
        style = (
            "magic" if name == "single_magic" else "slash" if name == "single_melee" else "ranged"
        )
        options = CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "light", "standard", "heavy", "magic"),
            stances=("accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"),
            spells=("fire_strike", "fire_bolt", "fire_blast", "fire_wave"),
        )
        role = case.request.roles[0].model_copy(
            update={
                "style": style,
                "stance": "rapid" if style == "ranged" else "accurate",
                "combat_options": options,
                "allowed_disciplines": ("melee", "ranged", "magic") if name == "auto" else None,
                "prayers": PrayerPolicy(mode="optimize", allowed_ids=("steel_skin", "eagle_eye")),
            }
        )
        request = case.request.model_copy(
            update={
                "roles": (role,),
                "secondary_priority": "ranged_defence_roll"
                if name == "defence_roll"
                else "balanced_defence",
                "max_dps_loss_pct": 100.0,
                "potions": PotionPolicy(mode="optimize", allowed_ids=("ranging", "divine_ranging"))
                if name == "potions"
                else PotionPolicy(mode="fixed", selected_ids=("divine_ranging",))
                if style == "ranged"
                else PotionPolicy(),
            }
        )
        case = replace(
            case, name=name, request=OptimizationRequest.model_validate(request.model_dump())
        )
    provenance = case_provenance(
        case,
        account_source=f"fixture:{fixture}",
        original_account_replayed=False,
        optimization_mode="thorough" if name == "defence_roll" else "fast",
        diagnostic=name == "ranged_diagnostic",
    )

    return (
        cost_objective_case(case, provenance) if name == "ranged_diagnostic" else (case, provenance)
    )


def environment() -> dict[str, Any]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    return {
        "revision": revision,
        "dirty": bool(dirty),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def benchmark(
    case: Any,
    provenance: dict[str, Any],
    output: Path,
    *,
    repeats: int = 5,
    warmups: int = 1,
    runner: Any = optimize,
    workers: int = 0,
    ranged_cache: int | None = None,
    memory: bool = False,
) -> dict[str, Any]:
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups nonnegative")
    if workers and ranged_cache is not None:
        raise ValueError("Ranged experiment requires serial execution")
    output.mkdir(parents=True, exist_ok=True)
    options = {"local_refinement": provenance.get("optimization_mode") == "thorough"}
    if provenance.get("diagnostic"):
        options = {**options, "_complete_frontiers": True}
    args = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    pool = None
    if workers:
        from tracker.gear.auto import optimize_auto
        from tracker.gear.parallel import AutoProcessPool

        pool = AutoProcessPool(workers)
        if case.request.potions.mode == "optimize":
            options = {**options, "potion_branch_runner": pool.run_potions}
        elif case.request.roles[0].allowed_disciplines:
            runner = optimize_auto
            options = {**options, "branch_runner": pool.run}
    runs = []
    expected = None
    memory_report = None
    try:
        if pool is not None:
            pool.start(case.content, case.catalog)
        for index in range(warmups + repeats):
            started = perf_counter()
            from tracker.gear.ranged_numerics import ranged_experiment

            with ranged_experiment(ranged_cache) if ranged_cache is not None else nullcontext():
                result = runner(*args, **options)
            seconds = perf_counter() - started
            result = materialize_result_archives(result)
            digest = result_digest(result)
            if expected is not None and expected != digest:
                raise ValueError(f"Result parity failed on iteration {index}")
            expected = digest
            if index >= warmups:
                number = index - warmups + 1
                (output / f"run-{number}.json").write_text(_json(result), encoding="utf-8")
                runs.append(
                    {
                        "wall_seconds": seconds,
                        "result_digest": digest,
                        "search": result.get("search", {}),
                    }
                )
        if memory:
            tracemalloc.start()
            try:
                with ranged_experiment(ranged_cache) if ranged_cache is not None else nullcontext():
                    result = runner(*args, **options)
                _, peak = tracemalloc.get_traced_memory()
                result = materialize_result_archives(result)
                if result_digest(result) != expected:
                    raise ValueError("Result parity failed during memory pass")
                memory_report = {
                    "kind": "parent_python_tracemalloc",
                    "peak_bytes": peak,
                    "includes_workers": False,
                    "is_process_rss": False,
                    "separate_from_latency_runs": True,
                }
            finally:
                tracemalloc.stop()
    finally:
        if pool is not None:
            pool.close()
    durations = [row["wall_seconds"] for row in runs]
    report = {
        "provenance": provenance,
        "environment": environment(),
        "execution": "workers" if workers else "serial",
        "workers": workers,
        "warmups": warmups,
        "repeats": repeats,
        "diagnostic": bool(provenance.get("diagnostic")),
        "runs": runs,
        "timing": {
            "median_seconds": statistics.median(durations),
            "minimum_seconds": min(durations),
            "maximum_seconds": max(durations),
        },
        "memory_instrumented": memory,
        "memory": memory_report,
        "ranged_cache": ranged_cache,
    }
    archived = {**frozen_inputs(case), "benchmark": provenance}
    (output / "inputs.json").write_text(_json(archived), encoding="utf-8")
    (output / "report.json").write_text(_json(report), encoding="utf-8")
    return report


def load_frozen_case(path: Path) -> tuple[Any, dict[str, Any]]:
    """Restore JSON dates without changing the worker IPC contract."""
    from tools.gear_retention_oracle import Case

    data = json.loads(path.read_text(encoding="utf-8"))
    content, catalog = decode_context(data["context"], data["context_id"])
    job = {
        **data["job"],
        "prices": {
            key: {
                field: datetime.fromisoformat(value)
                if field.endswith("_at") and isinstance(value, str)
                else value
                for field, value in row.items()
            }
            for key, row in data["job"]["prices"].items()
        },
    }
    snapshot, request, prices, at = decode_job(job, data["context_id"])
    case = Case("frozen", snapshot, request, catalog, content, prices, at)
    provenance = case_provenance(
        case,
        **{
            **data.get("benchmark", data.get("provenance", {"optimization_mode": "fast"})),
            "account_source": "frozen",
        },
    )
    return case, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", choices=CASES)
    source.add_argument("--dump", type=Path)
    source.add_argument("--frozen", type=Path, help="Replay inputs.json from a previous benchmark")
    parser.add_argument(
        "--snapshot", type=Path, help="Private complete snapshot paired with --dump"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--workers", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--ranged-cache", type=int, choices=(0, 4096, 16384, 65536))
    parser.add_argument(
        "--memory", action="store_true", help="Separate parent Python allocation pass; not RSS"
    )
    parser.add_argument("--thorough", action="store_true")
    parser.add_argument(
        "--diagnostic", action="store_true", help="Force complete/running frontiers"
    )
    args = parser.parse_args()
    if args.snapshot and not args.dump:
        parser.error("--snapshot requires --dump")
    if args.case:
        case, provenance = load_benchmark_case(args.case)
    elif args.dump:
        if args.snapshot is None:
            parser.error("--dump requires --snapshot; use --case for substitute fixtures")
        case, provenance = load_profile_case(args.dump, snapshot=args.snapshot)
        provenance = case_provenance(case, **provenance)
    else:
        case, provenance = load_frozen_case(args.frozen)
    provenance = {
        **provenance,
        "diagnostic": args.diagnostic or provenance.get("diagnostic", False),
    }
    if args.thorough:
        provenance = {**provenance, "optimization_mode": "thorough"}
    report = benchmark(
        case,
        provenance,
        args.output,
        repeats=args.repeats,
        warmups=args.warmups,
        workers=args.workers,
        ranged_cache=args.ranged_cache,
        memory=args.memory,
    )
    print(json.dumps({"timing": report["timing"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
