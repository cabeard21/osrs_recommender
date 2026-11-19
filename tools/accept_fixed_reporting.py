"""Controlled acceptance of fixed-option reporting through combined GearService.

This tool never changes desktop defaults. Keep private inputs/results ignored.
"""

from __future__ import annotations

import argparse
import json
import statistics
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.accept_gear_desktop_profiles import (
    _validated_timing as _profile_timing,
)
from tools.accept_gear_desktop_profiles import (
    _write,
    cohort_hash,
)
from tools.accept_gear_desktop_profiles import (
    derive_case as _derive,
)
from tools.benchmark_gear_desktop import (
    case_provenance,
    environment,
    frozen_inputs,
    load_frozen_case,
    result_digest,
)
from tools.compare_gear_desktop import decision
from tracker.gear.objective_store import materialize_result_archives
from tracker.gear.optimizer import OptimizationRequest, optimize
from tracker.gear.prayers import PrayerPolicy

REQUIRED = (
    ("fixed_ranged", 1),
    ("fixed_melee", 1),
    ("fixed_magic", 1),
    ("fixed_defence_roll", 1),
    ("fixed_thorough", 1),
    ("fixed_diagnostic", 1),
    ("auto_control", 1),
    ("auto_control", 3),
    ("fixed_potions", 1),
    ("fixed_potions", 3),
    ("multi", 1),
    ("configured_ranged", 1),
    ("configured_auto", 3),
    ("configured_potions", 3),
)
MODES = ("reference", "candidate")
MEMORY_CASES = (("fixed_ranged", 1), ("auto_control", 3), ("fixed_potions", 3))


def derive_case(case: Any, provenance: dict[str, Any], name: str) -> tuple[Any, dict[str, Any]]:
    if name not in dict(REQUIRED):
        raise ValueError("Unknown fixed-reporting acceptance case")
    variant = (
        "auto"
        if name == "auto_control"
        else name.removeprefix("fixed_").removeprefix("configured_")
    )
    case, metadata = _derive(case, provenance, variant)
    if name.startswith("fixed_") or name == "auto_control":
        role = case.request.roles[0].model_copy(
            update={
                "combat_options": case.request.roles[0].combat_options
                if variant == "auto"
                else None,
                "prayers": PrayerPolicy(),
            }
        )
        request = OptimizationRequest.model_validate(
            case.request.model_copy(update={"roles": (role,)}).model_dump()
        )
        case = replace(case, name=name, request=request)
    return case, case_provenance(
        case,
        **{
            **metadata,
            "case_name": name,
            "cohort_sha256": cohort_hash(case),
            "fixed_option_path": name.startswith("fixed_") and variant != "auto",
        },
    )


def fixed_service(case: Any, enabled: bool, pool: Any = None) -> Any:
    from tracker.gear.service import GearService

    service = GearService(
        case.content,
        optimization_profile="combined",
        fixed_reporting=enabled,
        auto_pool=pool,
    )
    service._equipment = case.catalog
    return service


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
    """Alternate profile order and demand parity including all logical work counters."""
    if workers not in (1, 3) or pairs < 5 or warmups < 0:
        raise ValueError("Invalid profile acceptance configuration")
    reference, candidate = "reference", "candidate"
    from tracker.gear.fixed_reporting import active as fixed_active
    from tracker.gear.lazy_reporting import active as lazy_active
    from tracker.gear.ranged_numerics import active as ranged_active

    if fixed_active() or lazy_active() or ranged_active():
        raise ValueError("Ambient experiments must be disabled")
    provenance = case_provenance(case, **{**provenance, "cohort_sha256": cohort_hash(case)})
    output.mkdir(parents=True, exist_ok=True)
    expected = None
    runs = []
    pair_rows = []
    diagnostic = bool(provenance.get("diagnostic"))
    if diagnostic and workers != 1:
        raise ValueError("Forced diagnostic runs are direct serial only")
    with ExitStack() as resources:
        pool = None
        if workers == 3 and service_factory is None:
            from tracker.gear.parallel import AutoProcessPool

            pool = AutoProcessPool(workers)
            resources.callback(pool.close)
            pool.start(case.content, case.catalog)
        services = {
            profile: service_factory(profile == "candidate")
            if service_factory
            else fixed_service(case, profile == "candidate", pool)
            for profile in (reference, candidate)
        }

        def execute(profile: str, label: str) -> dict[str, Any]:
            nonlocal expected
            start = perf_counter()
            if diagnostic:
                result = optimize(
                    case.snapshot,
                    case.request,
                    case.catalog,
                    case.content,
                    case.prices,
                    case.at,
                    _execution_profile="combined",
                    _fixed_reporting=profile == "candidate",
                    _complete_frontiers=True,
                    local_refinement=provenance.get("optimization_mode") == "thorough",
                )
            else:
                result = services[profile].optimize(
                    case.snapshot,
                    case.request,
                    price_records=case.prices,
                    now=case.at,
                    local_refinement=provenance.get("optimization_mode") == "thorough",
                )
            seconds = perf_counter() - start
            result = materialize_result_archives(result)
            digest = result_digest(result)
            if expected is not None and expected != digest:
                raise ValueError(f"Complete result parity failed: {label}")
            expected = digest
            row = {
                "profile": profile,
                "wall_seconds": seconds,
                "result_digest": digest,
                "search": result.get("search", {}),
            }
            _write(output / f"{label}.json", result)
            _write(output / f"{label}-measurement.json", row)
            return row

        for i in range(warmups):
            for profile in (reference, candidate):
                execute(profile, f"warmup-{i + 1}-{profile}")
        for i in range(pairs):
            order = (reference, candidate) if i % 2 == 0 else (candidate, reference)
            measured = {}
            for profile in order:
                row = execute(profile, f"pair-{i + 1}-{profile}")
                runs.append({"pair": i + 1, **row})
                measured[profile] = row["wall_seconds"]
            pair_rows.append({"pair": i + 1, "order": list(order), **measured})
    outcome = decision([r[reference] for r in pair_rows], [r[candidate] for r in pair_rows])
    outcome["no_material_regression"] = (
        outcome["cached_median_seconds"]
        <= outcome["original_median_seconds"] + outcome["original_mad_seconds"]
    )
    report = {
        "provenance": provenance,
        "environment": environment(),
        "reference": reference,
        "candidate": candidate,
        "fixed_reporting": {"reference": False, "candidate": True},
        "workers": workers,
        "execution": "direct_diagnostic" if diagnostic else "service",
        "runs": runs,
        "pairs": pair_rows,
        "decision": outcome,
        "memory_instrumented": False,
    }
    _write(output / "inputs.json", {**frozen_inputs(case), "benchmark": provenance})
    _write(output / "report.json", report)
    return report


def timing_decision(row: dict[str, Any]) -> dict[str, Any] | None:
    """Adapt internal labels to the existing strict paired-observation validator."""
    flags = row.get("fixed_reporting")
    if (
        row.get("reference") != "reference"
        or row.get("candidate") != "candidate"
        or not isinstance(flags, dict)
        or set(flags) != set(MODES)
        or flags.get("reference") is not False
        or flags.get("candidate") is not True
    ):
        return None
    mapping = {"reference": "baseline", "candidate": "combined"}
    try:
        pairs = row["pairs"]
        for index, pair in enumerate(pairs):
            expected = list(MODES if index % 2 == 0 else reversed(MODES))
            if (
                type(pair["pair"]) is not int
                or pair["pair"] != index + 1
                or pair["order"] != expected
            ):
                return None
        if any(
            type(run["pair"]) is not int or type(run["wall_seconds"]) not in (int, float)
            for run in row["runs"]
        ):
            return None
        adapted = {
            **row,
            "reference": "baseline",
            "candidate": "combined",
            "pairs": [
                {
                    **pair,
                    "order": [mapping[mode] for mode in pair["order"]],
                    "baseline": pair["reference"],
                    "combined": pair["candidate"],
                }
                for pair in pairs
            ],
            "runs": [{**run, "profile": mapping[run["profile"]]} for run in row["runs"]],
        }
        return _profile_timing(adapted)
    except (KeyError, TypeError, ValueError):
        return None


def _positive_integer(value: Any) -> bool:
    return type(value) is int and value > 0


def select_adoption(
    reports: list[dict[str, Any]],
    memory_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute gates; missing, ambiguous or malformed evidence prevents adoption."""
    reasons = []
    indexed = {}
    identities: dict[str, tuple[str, str]] = {}
    cohorts = set()
    for report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("provenance"), dict):
            reasons.append("Malformed timing report or provenance")
            continue
        provenance = report["provenance"]
        name, workers = provenance.get("case_name"), report.get("workers")
        if not isinstance(name, str) or type(workers) is not int:
            reasons.append("Malformed timing case or worker count")
            continue
        key = (name, workers)
        if key not in REQUIRED or key in indexed:
            reasons.append(f"Unexpected/duplicated timing configuration: {key}")
            continue
        indexed[key] = report
        cohort = provenance.get("cohort_sha256")
        if not isinstance(cohort, str) or not cohort:
            reasons.append("Frozen cohort missing or malformed")
        else:
            cohorts.add(cohort)
        identity = provenance.get("inputs_sha256")
        outcome = timing_decision(report)
        if not isinstance(identity, str) or not identity or outcome is None:
            reasons.append(f"Missing/malformed timing identity or pairs: {key}")
            continue
        digest = report["runs"][0]["result_digest"]
        if name in identities and identities[name] != (identity, digest):
            reasons.append(f"Serial/worker input or result mismatch: {name}")
        identities[name] = (identity, digest)
        if not outcome["no_material_regression"]:
            reasons.append(f"Timing regression: {key}")
        if key == ("fixed_ranged", 1) and not outcome["repeatable_gain"]:
            reasons.append("Primary ranged repeatable gain not established")
    if len(cohorts) != 1 or not all(isinstance(c, str) and c for c in cohorts):
        reasons.append("Frozen cohort missing or inconsistent")
    for key in REQUIRED:
        if key not in indexed:
            reasons.append(f"Missing configuration: {key}")
    if any(not isinstance(row, dict) for row in memory_reports):
        reasons.append("Malformed memory observation")
    memory_reports = [row for row in memory_reports if isinstance(row, dict)]
    ids = [row.get("measurement_id") for row in memory_reports]
    if not all(isinstance(value, str) and value for value in ids) or len(set(ids)) != len(ids):
        reasons.append("Missing/duplicated fresh-process measurement identifiers")
    for row in memory_reports:
        if (
            type(row.get("workers")) is not int
            or (row.get("case_name"), row.get("workers")) not in MEMORY_CASES
            or row.get("mode") not in MODES
        ):
            reasons.append("Unexpected memory configuration")
    for case, workers in MEMORY_CASES:
        peaks = {}
        for mode in MODES:
            rows = [
                r
                for r in memory_reports
                if r.get("case_name") == case
                and r.get("workers") == workers
                and r.get("mode") == mode
            ]
            identity = identities.get(case)
            valid = [
                r
                for r in rows
                if (
                    r.get("fresh_process") is True
                    and _positive_integer(r.get("pid"))
                    and r.get("complete") is True
                    and type(r.get("failures")) is int
                    and r["failures"] == 0
                    and _positive_integer(r.get("samples"))
                    and _positive_integer(r.get("sampled_peak_rss_bytes"))
                    and identity == (r.get("inputs_sha256"), r.get("result_digest"))
                )
            ]
            if (
                len(valid) != len(rows)
                or len(valid) < 3
                or len({r["pid"] for r in valid}) != len(valid)
            ):
                reasons.append(f"Missing/incomplete fresh-process memory: {case}/{workers}/{mode}")
            else:
                peaks[mode] = [r["sampled_peak_rss_bytes"] for r in valid]
        if len(peaks) == 2 and statistics.median(peaks["candidate"]) > max(peaks["reference"]):
            reasons.append(f"Memory regression: {case}/{workers}")
    return {"adopt": not reasons, "reasons": reasons}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(dict(REQUIRED)), default="fixed_ranged")
    parser.add_argument("--workers", type=int, choices=(1, 3), default=1)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if (args.case, args.workers) not in REQUIRED:
        parser.error("Case/worker configuration is outside the acceptance matrix")
    case, provenance = load_frozen_case(args.frozen)
    case, provenance = derive_case(case, provenance, args.case)
    report = compare(
        case, provenance, args.output, workers=args.workers, pairs=args.pairs, warmups=args.warmups
    )
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
