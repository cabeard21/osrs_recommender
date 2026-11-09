"""Observe ranged numerical dependencies; never substitute scoring results.

Use --fixture for portable data or --dump with --snapshot for private data.
Detailed results belong in ignored .tmp directories.
"""

from __future__ import annotations

import argparse
import json
import tracemalloc
from collections import OrderedDict
from pathlib import Path
from time import perf_counter


def summarize_accesses(accesses, capacities=(4096, 16384, 65536)):
    """Check equal-key equivalence and simulate bounded chronological LRU reuse."""
    known = {}
    caches = {size: OrderedDict() for size in capacities}
    if any(size <= 0 for size in capacities):
        raise ValueError("Cache capacities must be positive")
    counts = {
        str(size): {"hits": 0, "misses": 0, "evictions": 0, "entries": 0} for size in capacities
    }
    calls = 0
    for key, result in accesses:
        calls += 1
        if key in known and known[key] != result:
            raise ValueError("Equal dependency keys produced different numerical results")
        known[key] = result
        for size, cache in caches.items():
            row = counts[str(size)]
            if key in cache:
                row["hits"] += 1
                cache.move_to_end(key)
            else:
                row["misses"] += 1
                if len(cache) == size:
                    cache.popitem(last=False)
                    row["evictions"] += 1
                cache[key] = None
            row["entries"] = len(cache)
    return {"calls": calls, "distinct_keys": len(known), "capacities": counts}


def main():
    from tools.gear_search_quality_fixture import load_case
    from tools.profile_gear_frontiers import load_profile_case
    from tracker.gear.optimizer import optimize
    from tracker.gear.ranged_numerics import ranged_experiment

    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture")
    source.add_argument("--case", choices=("single_ranged", "ranged_diagnostic"))
    source.add_argument("--snapshot", type=Path)
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force-frontiers", action="store_true")
    args = parser.parse_args()
    if args.dump and not args.snapshot:
        parser.error("--dump requires --snapshot")
    if args.snapshot:
        if not args.dump:
            parser.error("--snapshot requires --dump")
        case, provenance = load_profile_case(args.dump, snapshot=args.snapshot)
    elif args.case:
        from tools.benchmark_gear_desktop import load_benchmark_case

        case, provenance = load_benchmark_case(args.case)
    else:
        case = load_case(args.fixture)
        provenance = {"account_source": f"fixture:{args.fixture}", "optimization_mode": "fast"}
    from tools.benchmark_gear_desktop import result_digest

    inputs = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    options = {"local_refinement": provenance["optimization_mode"] == "thorough"}
    if args.force_frontiers or provenance.get("diagnostic"):
        options.update(_complete_frontiers=True, _running_frontier=True)
    reference = optimize(*inputs, **options)
    tracemalloc.start()
    started = perf_counter()
    try:
        with ranged_experiment(observe=True) as experiment:
            observed = optimize(*inputs, **options)
        elapsed = perf_counter() - started
        summary = summarize_accesses(experiment.accesses)
        if not summary["calls"]:
            raise ValueError("No ranged accesses; use --case single_ranged")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if result_digest(reference) != result_digest(observed):
        raise ValueError("Observation changed complete optimizer results")
    report = {
        "provenance": provenance,
        "force_frontiers": bool(options.get("_complete_frontiers")),
        "key_construction_seconds": experiment.key_seconds,
        "solution_digest": result_digest(reference),
        "reuse": summary,
        "instrumented_seconds": elapsed,
        "instrumented_python_peak_bytes": peak,
        "memory_scope": "includes observation trace and LRU simulation; not process RSS",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
