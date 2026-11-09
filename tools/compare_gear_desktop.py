"""Interleaved original/experimental comparisons on complete frozen inputs.

Outputs can contain private account data; keep them in ignored .tmp directories.
Timing passes are serial and uninstrumented. No service cache is enabled.
"""

from __future__ import annotations

import argparse
import json
import statistics
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.benchmark_gear_desktop import (
    CASES,
    environment,
    frozen_inputs,
    load_benchmark_case,
    result_digest,
)
from tools.gear_retention_oracle import Case
from tracker.gear.fixed_reporting import active as fixed_reporting_active
from tracker.gear.fixed_reporting import fixed_reporting
from tracker.gear.lazy_reporting import active as lazy_reporting_active
from tracker.gear.optimizer import optimize
from tracker.gear.ranged_numerics import active as numerical_experiment_active
from tracker.gear.ranged_numerics import ranged_experiment
from tracker.gear.ranged_score_finalization import active as score_finalization_active
from tracker.gear.ranged_score_finalization import ranged_score_finalization


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def load_frozen(path: Path) -> tuple[Case, dict[str, Any]]:
    """Decode archived catalog/content/account/prices and retain execution settings."""
    from tools.benchmark_gear_desktop import load_frozen_case

    return load_frozen_case(path)


def _mad(values: list[float]) -> float:
    median = statistics.median(values)
    return statistics.median(abs(value - median) for value in values)


def decision(original: list[float], cached: list[float]) -> dict[str, Any]:
    """Require median gain to exceed baseline and paired observed variation."""
    if len(original) != len(cached) or not original:
        raise ValueError("Paired timings must be nonempty and equal length")
    deltas = [a - b for a, b in zip(original, cached, strict=True)]
    baseline = statistics.median(original)
    gain = baseline - statistics.median(cached)
    paired = statistics.median(deltas)
    baseline_mad, paired_mad = _mad(original), _mad(deltas)
    return {
        "original_median_seconds": baseline,
        "cached_median_seconds": statistics.median(cached),
        "median_gain_seconds": gain,
        "paired_median_gain_seconds": paired,
        "original_mad_seconds": baseline_mad,
        "paired_mad_seconds": paired_mad,
        "repeatable_gain": gain > baseline_mad and paired > paired_mad,
        "production_adoption": False,
        "adoption_note": "Timing alone does not establish memory or full-catalog acceptance.",
    }


def compare(
    case: Case,
    provenance: dict[str, Any],
    output: Path,
    *,
    pairs: int = 5,
    warmups: int = 1,
    capacity: int = 65536,
    runner: Any = optimize,
    experiment: str = "ranged-cache",
) -> dict[str, Any]:
    """Alternate AB/BA pairs; every invocation starts a fresh optional numerical cache."""
    if pairs < 5 or warmups < 0 or capacity <= 0:
        raise ValueError("pairs must be at least five, warmups nonnegative, capacity positive")
    if experiment not in {
        "ranged-cache",
        "lazy-reporting",
        "fixed-reporting",
        "ranged-score-finalization",
    }:
        raise ValueError("Unknown experiment")
    if score_finalization_active():
        raise ValueError("Finalization must be disabled before starting comparisons")
    if fixed_reporting_active():
        raise ValueError("Fixed reporting must be disabled before starting comparisons")
    if lazy_reporting_active():
        raise ValueError("Lazy reporting must be disabled before starting comparisons")
    if experiment != "ranged-cache" and numerical_experiment_active():
        raise ValueError("Numerical experiment must be disabled before starting comparisons")
    candidate = {
        "ranged-cache": "cached",
        "lazy-reporting": "lazy",
        "fixed-reporting": "fixed",
        "ranged-score-finalization": "finalized",
    }[experiment]
    output.mkdir(parents=True, exist_ok=True)
    options = {"local_refinement": provenance.get("optimization_mode") == "thorough"}
    if experiment in {"fixed-reporting", "ranged-score-finalization"}:
        options["_execution_profile"] = "combined"
    if experiment == "ranged-score-finalization":
        options["_fixed_reporting"] = True
    if provenance.get("diagnostic"):
        options.update(_complete_frontiers=True, _running_frontier=True)
    inputs = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    expected = None
    runs: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []

    def execute(mode: str, label: str) -> dict[str, Any]:
        nonlocal expected
        started = perf_counter()
        context: Any = nullcontext()
        if mode == "cached":
            context = ranged_experiment(capacity)
        elif mode == "lazy":
            from tracker.gear.lazy_reporting import lazy_reporting

            context = lazy_reporting()
        if mode == "fixed":
            context = fixed_reporting()
        elif mode == "finalized":
            context = ranged_score_finalization()
        with context as observation:
            result = runner(*inputs, **options)
        elapsed = perf_counter() - started
        digest = result_digest(result)
        if expected is not None and expected != digest:
            raise ValueError(f"Complete result parity failed for {label}")
        expected = digest
        _write(output / f"{label}.json", result)
        row = {
            "mode": mode,
            "wall_seconds": elapsed,
            "result_digest": digest,
            "search": result.get("search", {}),
        }
        if mode == "cached" and observation is not None:
            row["cache"] = observation.cache_info()._asdict()
        # Flush progress so interrupted comparisons retain completed run observations.
        _write(output / f"{label}-measurement.json", row)
        return row

    for index in range(warmups):
        for mode in ("original", candidate):
            execute(mode, f"warmup-{index + 1}-{mode}")
    for index in range(pairs):
        order = ("original", candidate) if index % 2 == 0 else (candidate, "original")
        rows = {}
        for mode in order:
            row = execute(mode, f"pair-{index + 1}-{mode}")
            runs.append({"pair": index + 1, **row})
            rows[mode] = row["wall_seconds"]
        paired.append(
            {
                "pair": index + 1,
                "order": list(order),
                **rows,
                "gain_seconds": rows["original"] - rows[candidate],
            }
        )
    outcome = decision([row["original"] for row in paired], [row[candidate] for row in paired])
    if candidate in {"lazy", "fixed", "finalized"}:
        outcome[f"{candidate}_median_seconds"] = outcome.pop("cached_median_seconds")
    report = {
        "provenance": provenance,
        "environment": environment(),
        "capacity": capacity if experiment == "ranged-cache" else None,
        "experiment": experiment,
        "execution": "serial_interleaved",
        "warmups_per_mode": warmups,
        "runs": runs,
        "pairs": paired,
        "decision": outcome,
        "memory_instrumented": False,
    }
    if experiment == "ranged-score-finalization":
        report["reference_implementation"] = "current_source_context_disabled"
    _write(output / "inputs.json", {**frozen_inputs(case), "benchmark": provenance})
    _write(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", choices=CASES)
    source.add_argument("--frozen", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--capacity", type=int, default=65536)
    parser.add_argument(
        "--experiment",
        choices=("ranged-cache", "lazy-reporting", "fixed-reporting", "ranged-score-finalization"),
        default="ranged-cache",
    )
    parser.add_argument("--thorough", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    case, provenance = load_benchmark_case(args.case) if args.case else load_frozen(args.frozen)
    provenance = {
        **provenance,
        "diagnostic": args.diagnostic or provenance.get("diagnostic", False),
    }
    if args.thorough:
        provenance = {**provenance, "optimization_mode": "thorough"}
    report = compare(
        case,
        provenance,
        args.output,
        pairs=args.pairs,
        warmups=args.warmups,
        capacity=args.capacity,
        experiment=args.experiment,
    )
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
