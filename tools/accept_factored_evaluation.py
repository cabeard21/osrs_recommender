"""Reproduce complete P1 acceptance on frozen inputs through desktop execution.

Latency and fresh-process memory are separate runs. This tool never changes
desktop defaults; private inputs and complete results belong under ignored .tmp.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path
from time import perf_counter
from typing import Any

from tools import accept_fixed_reporting as fixed
from tools.accept_gear_desktop_profiles import _write, cohort_hash
from tools.accept_gear_desktop_profiles import derive_case as profile_case
from tools.benchmark_gear_desktop import (
    case_provenance,
    environment,
    frozen_inputs,
    load_frozen_case,
    result_digest,
)
from tools.compare_gear_desktop import decision
from tools.gear_process_memory import measure_process_tree
from tracker.gear.optimizer import optimize

EXTRA_CASES = (("configured_melee", 1), ("configured_magic", 1), ("configured_diagnostic", 1))
REQUIRED = (*fixed.REQUIRED, *EXTRA_CASES)
MODES = ("reference", "candidate")
MEMORY_CASES = (
    ("configured_ranged", 1),
    ("configured_magic", 1),
    ("configured_auto", 3),
    ("configured_potions", 3),
    ("multi", 1),
)
PARALLEL_CASES = ("configured_auto", "configured_potions")
GAIN_CASES = {
    (name, 1)
    for name in (
        "fixed_ranged",
        "fixed_melee",
        "fixed_magic",
        "fixed_diagnostic",
        "configured_ranged",
        "configured_melee",
        "configured_magic",
        "configured_diagnostic",
    )
}


def derive_case(case: Any, provenance: dict[str, Any], name: str) -> tuple[Any, dict[str, Any]]:
    if name in dict(fixed.REQUIRED):
        return fixed.derive_case(case, provenance, name)
    if name not in dict(EXTRA_CASES):
        raise ValueError("Unknown factored-evaluation acceptance case")
    case, metadata = profile_case(case, provenance, name.removeprefix("configured_"))
    return case, case_provenance(case, **{**metadata, "case_name": name})


def factored_service(case: Any, enabled: bool, pool: Any = None) -> Any:
    from tracker.gear.service import GearService

    service = GearService(
        case.content,
        optimization_profile="combined",
        fixed_reporting=True,
        factored_evaluation=enabled,
        auto_pool=pool,
    )
    service._equipment = case.catalog
    return service


def _check_ambient() -> None:
    from tracker.gear.compact_costs import active as costs_active
    from tracker.gear.fixed_reporting import active as fixed_active
    from tracker.gear.lazy_reporting import active as lazy_active
    from tracker.gear.prepared_combat import active as prepared_active
    from tracker.gear.ranged_numerics import active as ranged_active
    from tracker.gear.ranged_score_finalization import active as finalization_active
    from tracker.gear.variant_reporting import active as variants_active

    if any(
        active()
        for active in (
            fixed_active,
            lazy_active,
            ranged_active,
            finalization_active,
            prepared_active,
            costs_active,
            variants_active,
        )
    ):
        raise ValueError("Ambient experiments must be disabled")


def _pool(resources: ExitStack, case: Any, workers: int) -> Any:
    if workers == 1:
        return None
    from tracker.gear.parallel import AutoProcessPool

    pool = AutoProcessPool(workers)
    resources.callback(pool.close)
    pool.start(case.content, case.catalog)
    return pool


def _run(case: Any, provenance: dict[str, Any], enabled: bool, service: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "local_refinement": provenance.get("optimization_mode") == "thorough"
    }
    if provenance.get("diagnostic"):
        return optimize(
            case.snapshot,
            case.request,
            case.catalog,
            case.content,
            case.prices,
            case.at,
            _execution_profile="combined",
            _fixed_reporting=True,
            _factored_evaluation=enabled,
            _complete_frontiers=True,
            _running_frontier=True,
            **options,
        )
    return service.optimize(
        case.snapshot, case.request, price_records=case.prices, now=case.at, **options
    )


def compare(
    case: Any,
    provenance: dict[str, Any],
    output: Path,
    *,
    workers: int = 1,
    pairs: int = 5,
    warmups: int = 1,
    service_factory: Any = None,
) -> dict[str, Any]:
    """Alternate AB/BA pairs, checking complete logical output on every run."""
    if (
        type(workers) is not int
        or workers not in (1, 3)
        or type(pairs) is not int
        or pairs < 5
        or type(warmups) is not int
        or warmups < 0
    ):
        raise ValueError("Invalid factored-evaluation acceptance configuration")
    _check_ambient()
    diagnostic = bool(provenance.get("diagnostic"))
    if diagnostic and workers != 1:
        raise ValueError("Forced diagnostic runs are direct serial only")
    provenance = case_provenance(case, **{**provenance, "cohort_sha256": cohort_hash(case)})
    output.mkdir(parents=True, exist_ok=True)
    runs, pairs_data = [], []
    expected = None
    with ExitStack() as resources:
        pool = _pool(resources, case, workers) if service_factory is None else None
        services = (
            {
                mode: service_factory(mode == "candidate")
                if service_factory
                else factored_service(case, mode == "candidate", pool)
                for mode in MODES
            }
            if not diagnostic
            else dict.fromkeys(MODES)
        )

        def execute(mode: str, label: str) -> dict[str, Any]:
            nonlocal expected
            start = perf_counter()
            result = _run(case, provenance, mode == "candidate", services[mode])
            elapsed = perf_counter() - start
            digest = result_digest(result)
            row = {
                "profile": mode,
                "wall_seconds": elapsed,
                "result_digest": digest,
                "search": result.get("search", {}),
            }
            _write(output / f"{label}.json", result)
            _write(output / f"{label}-measurement.json", row)
            if expected is not None and expected != digest:
                raise ValueError(f"Complete result parity failed: {label}")
            expected = digest
            return row

        for index in range(warmups):
            for mode in MODES:
                execute(mode, f"warmup-{index + 1}-{mode}")
        for index in range(pairs):
            order = MODES if index % 2 == 0 else tuple(reversed(MODES))
            measured = {}
            for mode in order:
                row = execute(mode, f"pair-{index + 1}-{mode}")
                runs.append({"pair": index + 1, **row})
                measured[mode] = row["wall_seconds"]
            pairs_data.append({"pair": index + 1, "order": list(order), **measured})
    outcome = decision([p["reference"] for p in pairs_data], [p["candidate"] for p in pairs_data])
    outcome["no_material_regression"] = (
        outcome["cached_median_seconds"]
        <= outcome["original_median_seconds"] + outcome["original_mad_seconds"]
    )
    report = {
        "provenance": provenance,
        "environment": environment(),
        "reference": "reference",
        "candidate": "candidate",
        "fixed_reporting": dict.fromkeys(MODES, True),
        "factored_evaluation": {"reference": False, "candidate": True},
        "workers": workers,
        "execution": "direct_diagnostic" if diagnostic else "service",
        "warmups_per_mode": warmups,
        "runs": runs,
        "pairs": pairs_data,
        "decision": outcome,
        "memory_instrumented": False,
    }
    _write(output / "inputs.json", {**frozen_inputs(case), "benchmark": provenance})
    _write(output / "report.json", report)
    return report


def timing_decision(row: dict[str, Any]) -> dict[str, Any] | None:
    """Reuse the strict pair validator after verifying this experiment's identity."""
    flags = row.get("factored_evaluation")
    fixed_flags = row.get("fixed_reporting")
    if (
        not isinstance(flags, dict)
        or set(flags) != set(MODES)
        or flags.get("reference") is not False
        or flags.get("candidate") is not True
        or not isinstance(fixed_flags, dict)
        or set(fixed_flags) != set(MODES)
        or any(fixed_flags.get(mode) is not True for mode in MODES)
    ):
        return None
    return fixed.timing_decision({**row, "fixed_reporting": flags})


def select_adoption(
    reports: list[dict[str, Any]],
    memory_reports: list[dict[str, Any]],
    worker_parity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require parity, all-case nonregression, at least one substantive gain and memory."""
    reasons: list[str] = []
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    identities: dict[str, tuple[str, str]] = {}
    cohorts: set[str] = set()
    gain = False
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("provenance"), dict):
            reasons.append("Malformed timing report or provenance")
            continue
        p = report["provenance"]
        name, workers = p.get("case_name"), report.get("workers")
        if not isinstance(name, str) or type(workers) is not int:
            reasons.append("Malformed timing configuration")
            continue
        key = (name, workers)
        if key not in REQUIRED or key in indexed:
            reasons.append(f"Unexpected/duplicated timing configuration: {key}")
            continue
        indexed[key] = report
        cohort = p.get("cohort_sha256")
        if not isinstance(cohort, str) or not cohort:
            reasons.append("Frozen cohort missing or malformed")
        else:
            cohorts.add(cohort)
        identity, outcome = p.get("inputs_sha256"), timing_decision(report)
        if not isinstance(identity, str) or not identity or outcome is None:
            reasons.append(f"Missing/malformed timing identity or pairs: {key}")
            continue
        digest = report["runs"][0]["result_digest"]
        if name in identities and identities[name] != (identity, digest):
            reasons.append(f"Serial/worker input or result mismatch: {name}")
        identities[name] = (identity, digest)
        if not outcome["no_material_regression"]:
            reasons.append(f"Timing regression: {key}")
        gain |= key in GAIN_CASES and outcome["repeatable_gain"]
    if len(cohorts) != 1:
        reasons.append("Frozen cohort missing or inconsistent")
    if not gain:
        reasons.append("No substantive case established a repeatable gain")
    reasons.extend(f"Missing configuration: {key}" for key in REQUIRED if key not in indexed)
    _validate_memory(memory_reports, identities, reasons)
    _validate_worker_parity(worker_parity or [], identities, reasons)
    return {"adopt": not reasons, "reasons": reasons}


def _validate_worker_parity(
    rows: list[dict[str, Any]],
    identities: dict[str, tuple[str, str]],
    reasons: list[str],
) -> None:
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            reasons.append("Malformed worker parity observation")
            continue
        name, mode = row.get("case_name"), row.get("mode")
        if not isinstance(name, str) or not isinstance(mode, str):
            reasons.append("Malformed worker parity identity")
            continue
        key = (name, mode)
        if name not in PARALLEL_CASES or mode not in MODES or key in indexed:
            reasons.append(f"Unexpected/duplicated worker parity observation: {key}")
            continue
        indexed[key] = row
        expected = identities.get(name)
        if (
            row.get("fixed_reporting") is not True
            or row.get("factored_evaluation") is not (mode == "candidate")
            or row.get("passed") is not True
            or type(row.get("serial_workers")) is not int
            or row["serial_workers"] != 1
            or type(row.get("workers")) is not int
            or row["workers"] != 3
            or expected != (row.get("inputs_sha256"), row.get("serial_digest"))
            or row.get("serial_digest") != row.get("worker_digest")
        ):
            reasons.append(f"Incomplete/mismatched worker parity: {key}")
    reasons.extend(
        f"Missing worker parity: {name}/{mode}"
        for name in PARALLEL_CASES
        for mode in MODES
        if (name, mode) not in indexed
    )


def compare_workers(
    case: Any,
    provenance: dict[str, Any],
    output: Path,
    *,
    service_factory: Any = None,
) -> list[dict[str, Any]]:
    """Compare serial and three-worker results separately from latency/memory runs."""
    if provenance.get("case_name") not in PARALLEL_CASES or provenance.get("diagnostic"):
        raise ValueError("Worker parity requires a configured Auto or potion case")
    _check_ambient()
    provenance = case_provenance(case, **{**provenance, "cohort_sha256": cohort_hash(case)})
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    expected = None
    with ExitStack() as resources:
        pool = _pool(resources, case, 3) if service_factory is None else None
        for mode in MODES:
            digests = {}
            for workers in (1, 3):
                service = (
                    service_factory(mode == "candidate", workers)
                    if service_factory
                    else factored_service(case, mode == "candidate", pool if workers == 3 else None)
                )
                result = _run(case, provenance, mode == "candidate", service)
                digest = result_digest(result)
                if expected is not None and expected != digest:
                    raise ValueError(f"Complete serial/worker parity failed: {mode}/{workers}")
                expected = digest
                digests[workers] = digest
                _write(output / f"{mode}-{workers}.json", result)
            rows.append(
                {
                    "case_name": provenance["case_name"],
                    "mode": mode,
                    "serial_workers": 1,
                    "workers": 3,
                    "fixed_reporting": True,
                    "factored_evaluation": mode == "candidate",
                    "inputs_sha256": provenance["inputs_sha256"],
                    "serial_digest": digests[1],
                    "worker_digest": digests[3],
                    "passed": True,
                }
            )
    _write(output / "worker-parity.json", rows)
    _write(output / "inputs.json", {**frozen_inputs(case), "benchmark": provenance})
    return rows


def _validate_memory(
    rows: list[dict[str, Any]], identities: dict[str, tuple[str, str]], reasons: list[str]
) -> None:
    if any(not isinstance(row, dict) for row in rows):
        reasons.append("Malformed memory observation")
    rows = [row for row in rows if isinstance(row, dict)]
    ids = [row.get("measurement_id") for row in rows]
    if not all(isinstance(value, str) and value for value in ids) or len(set(ids)) != len(ids):
        reasons.append("Missing/duplicated fresh-process measurement identifiers")
    for row in rows:
        if (
            type(row.get("workers")) is not int
            or (row.get("case_name"), row.get("workers")) not in MEMORY_CASES
            or row.get("mode") not in MODES
        ):
            reasons.append("Unexpected memory configuration")
    for name, workers in MEMORY_CASES:
        peaks = {}
        for mode in MODES:
            selected = [
                r
                for r in rows
                if r.get("case_name") == name
                and r.get("workers") == workers
                and r.get("mode") == mode
            ]
            valid = [
                r
                for r in selected
                if r.get("fresh_process") is True
                and fixed._positive_integer(r.get("pid"))
                and r.get("complete") is True
                and type(r.get("failures")) is int
                and r["failures"] == 0
                and fixed._positive_integer(r.get("samples"))
                and fixed._positive_integer(r.get("sampled_peak_rss_bytes"))
                and r.get("fixed_reporting") is True
                and r.get("factored_evaluation") is (mode == "candidate")
                and identities.get(name) == (r.get("inputs_sha256"), r.get("result_digest"))
            ]
            if (
                len(valid) != len(selected)
                or len(valid) < 3
                or len({r["pid"] for r in valid}) != len(valid)
            ):
                reasons.append(f"Missing/incomplete fresh-process memory: {name}/{workers}/{mode}")
            else:
                peaks[mode] = [r["sampled_peak_rss_bytes"] for r in valid]
        if len(peaks) == 2 and statistics.median(peaks["candidate"]) > max(peaks["reference"]):
            reasons.append(f"Memory regression: {name}/{workers}")


def memory_once(
    case: Any,
    provenance: dict[str, Any],
    output: Path,
    *,
    mode: str,
    workers: int = 1,
    interval: float = 0.02,
) -> dict[str, Any]:
    """Sample one invocation; the external launcher, not this function, certifies freshness."""
    if mode not in MODES or type(workers) is not int or workers not in (1, 3):
        raise ValueError("Invalid memory configuration")
    if provenance.get("diagnostic") and workers != 1:
        raise ValueError("Forced diagnostic runs are direct serial only")
    _check_ambient()
    provenance = case_provenance(case, **{**provenance, "cohort_sha256": cohort_hash(case)})
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as resources:
        pool = _pool(resources, case, workers)
        service = (
            None
            if provenance.get("diagnostic")
            else factored_service(case, mode == "candidate", pool)
        )
        with measure_process_tree(interval=interval) as stats:
            result = _run(case, provenance, mode == "candidate", service)
        row = {
            **stats.report(),
            "case_name": provenance["case_name"],
            "workers": workers,
            "mode": mode,
            "factored_evaluation": mode == "candidate",
            "fixed_reporting": True,
            "fresh_process": False,
            "pid": os.getpid(),
            "measurement_id": uuid.uuid4().hex,
            "inputs_sha256": provenance["inputs_sha256"],
            "result_digest": result_digest(result),
        }
    _write(output / "memory.json", row)
    _write(output / "result.json", result)
    _write(output / "inputs.json", {**frozen_inputs(case), "benchmark": provenance})
    return row


def measure_memory(
    frozen: Path | str,
    output: Path,
    *,
    case_name: str,
    mode: str,
    workers: int = 1,
    interval: float = 0.02,
) -> dict[str, Any]:
    """Run a single memory observation in a newly launched Python interpreter."""
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "tools.accept_factored_evaluation",
        "--frozen",
        str(frozen),
        "--output",
        str(output),
        "--case",
        case_name,
        "--workers",
        str(workers),
        "--memory-mode",
        mode,
        "--memory-child",
        "--sample-interval",
        str(interval),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    row = json.loads((output / "memory.json").read_text(encoding="utf-8"))
    row = {**row, "fresh_process": True}
    _write(output / "memory.json", row)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(dict(REQUIRED)), default="fixed_ranged")
    parser.add_argument("--workers", type=int, choices=(1, 3), default=1)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--memory-mode", choices=MODES)
    operation.add_argument("--worker-parity", action="store_true")
    parser.add_argument("--memory-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sample-interval", type=float, default=0.02)
    args = parser.parse_args()
    if (args.case, args.workers) not in REQUIRED:
        parser.error("Case/worker configuration is outside the acceptance matrix")
    if args.memory_child and not args.memory_mode:
        parser.error("Memory child requires a memory mode")
    if args.worker_parity:
        case, provenance = load_frozen_case(args.frozen)
        case, provenance = derive_case(case, provenance, args.case)
        print(json.dumps(compare_workers(case, provenance, args.output), indent=2))
        return
    if args.memory_mode and not args.memory_child:
        report = measure_memory(
            args.frozen,
            args.output,
            case_name=args.case,
            mode=args.memory_mode,
            workers=args.workers,
            interval=args.sample_interval,
        )
    else:
        case, provenance = load_frozen_case(args.frozen)
        case, provenance = derive_case(case, provenance, args.case)
        report = (
            memory_once(
                case,
                provenance,
                args.output,
                mode=args.memory_mode,
                workers=args.workers,
                interval=args.sample_interval,
            )
            if args.memory_mode
            else compare(
                case,
                provenance,
                args.output,
                workers=args.workers,
                pairs=args.pairs,
                warmups=args.warmups,
            )
        )
    print(json.dumps(report.get("decision", report), indent=2))


if __name__ == "__main__":
    main()
