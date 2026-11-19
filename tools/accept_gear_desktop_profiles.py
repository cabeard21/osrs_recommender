"""Compare desktop profiles on frozen facts through the actual GearService.

Private inputs and detailed results belong in ignored .tmp directories. Timings
exclude startup and serialization; pool preparation is included in warm-up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from tools.benchmark_gear_desktop import (
    case_provenance,
    cost_objective_case,
    environment,
    frozen_inputs,
    load_frozen_case,
    result_digest,
)
from tools.compare_gear_desktop import decision
from tracker.gear.objective_store import materialize_result_archives
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, optimize
from tracker.gear.potions import PotionPolicy

CASES = (
    "ranged",
    "melee",
    "magic",
    "defence_roll",
    "auto",
    "potions",
    "thorough",
    "diagnostic",
    "multi",
)
PROFILES = ("baseline", "lazy", "combined")


def cohort_hash(case: Any) -> str:
    """Bind account/catalog/content/prices/time independently of request variants."""
    payload = frozen_inputs(case)
    payload = {
        **payload,
        "job": {key: value for key, value in payload["job"].items() if key != "request"},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, allow_nan=False).encode()
    ).hexdigest()


def _validated_timing(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate observations and recompute all timing decisions, ignoring claimed flags."""
    if row is None:
        return None
    try:
        reference, candidate = row["reference"], row["candidate"]
        if reference not in PROFILES or candidate not in PROFILES or reference == candidate:
            return None
        pairs, runs = row["pairs"], row["runs"]
        count = len(pairs)
        if count < 5 or len(runs) != 2 * count:
            return None
        if {pair["pair"] for pair in pairs} != set(range(1, count + 1)):
            return None
        digests = {run["result_digest"] for run in runs}
        if len(digests) != 1 or not all(isinstance(d, str) and d for d in digests):
            return None
        indexed = {(run["pair"], run["profile"]): run for run in runs}
        if len(indexed) != len(runs):
            return None
        for pair in pairs:
            if sorted(pair["order"]) != sorted((reference, candidate)):
                return None
            for profile in (reference, candidate):
                value = pair[profile]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    return None
                if indexed[(pair["pair"], profile)]["wall_seconds"] != value:
                    return None
        outcome = decision([pair[reference] for pair in pairs], [pair[candidate] for pair in pairs])
        outcome["no_material_regression"] = (
            outcome["cached_median_seconds"]
            <= outcome["original_median_seconds"] + outcome["original_mad_seconds"]
        )
        return outcome
    except (KeyError, TypeError, ValueError):
        return None


def derive_case(case: Any, provenance: dict[str, Any], name: str) -> tuple[Any, dict[str, Any]]:
    """Change only the named request settings, preserving observations and budgets."""
    if name not in CASES:
        raise ValueError("Unknown acceptance case")
    role = case.request.roles[0]
    updates: dict[str, Any] = {}
    if name in {"melee", "magic", "auto", "multi"}:
        options = CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "light", "standard", "heavy", "magic"),
            stances=("accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"),
            spells=("fire_strike", "fire_bolt", "fire_blast", "fire_wave"),
        )
        style = "slash" if name == "melee" else "magic" if name == "magic" else "ranged"
        role = role.model_copy(
            update={
                "style": style,
                "stance": "rapid" if style == "ranged" else "accurate",
                "combat_options": options,
                "allowed_disciplines": ("melee", "ranged", "magic") if name == "auto" else None,
            }
        )
        updates["roles"] = (role,)
        if name in {"melee", "magic", "multi"}:
            updates["potions"] = PotionPolicy()
        if name == "multi":
            melee = role.model_copy(
                update={"id": "accept_melee", "style": "slash", "stance": "accurate"}
            )
            updates.update(roles=(role, melee), base_role=role.id)
    if name == "defence_roll":
        updates["secondary_priority"] = "ranged_defence_roll"
    if name == "potions":
        updates["potions"] = PotionPolicy(
            mode="optimize", allowed_ids=("ranging", "divine_ranging")
        )
    request = OptimizationRequest.model_validate(
        case.request.model_copy(update=updates).model_dump()
    )
    case = replace(case, name=name, request=request)
    metadata = {
        **provenance,
        "case_name": name,
        "optimization_mode": "thorough" if name == "thorough" else "fast",
        "diagnostic": name == "diagnostic",
        "request_variant": True,
        "cohort_sha256": cohort_hash(case),
    }
    if name == "diagnostic":
        return cost_objective_case(case, metadata)
    return case, case_provenance(case, **metadata)


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )


def profile_service(case: Any, profile: str, pool: Any = None) -> Any:
    from tracker.gear.execution_profile import validate_profile
    from tracker.gear.service import GearService

    service = GearService(
        case.content, optimization_profile=validate_profile(profile), auto_pool=pool
    )
    service._equipment = case.catalog
    return service


def compare_profiles(
    case: Any,
    provenance: dict[str, Any],
    output: Path,
    *,
    candidate: str = "lazy",
    reference: str = "baseline",
    workers: int = 1,
    pairs: int = 5,
    warmups: int = 1,
    service_factory: Any = None,
) -> dict[str, Any]:
    """Alternate profile order and demand parity including all logical work counters."""
    if (
        candidate not in PROFILES
        or reference not in PROFILES
        or candidate == reference
        or workers not in (1, 3)
        or pairs < 5
        or warmups < 0
    ):
        raise ValueError("Invalid profile acceptance configuration")
    from tracker.gear.lazy_reporting import active as lazy_active
    from tracker.gear.ranged_numerics import active as ranged_active

    if lazy_active() or ranged_active():
        raise ValueError("Ambient experiments must be disabled")
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
            profile: service_factory(profile)
            if service_factory
            else profile_service(case, profile, pool)
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
                    _execution_profile=profile,
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


def select_default(
    reports: list[dict[str, Any]], memory_reports: list[dict[str, Any]]
) -> dict[str, Any]:
    """Fail closed unless the complete scenario, parity, timing and memory gates pass.

    Memory rows identify case_name/workers/profile, a unique fresh-process pid,
    complete/samples/failures, sampled_peak_rss_bytes, and result_digest.
    """
    required = [(case, 1) for case in CASES] + [("auto", 3), ("potions", 3)]
    profiles = {}

    def find(reference: str, candidate: str, case: str, workers: int) -> dict[str, Any] | None:
        matches = [
            row
            for row in reports
            if row.get("reference") == reference
            and row.get("candidate") == candidate
            and row.get("workers") == workers
            and row.get("provenance", {}).get("case_name") == case
        ]
        return matches[0] if len(matches) == 1 else None

    def parity(row: dict[str, Any] | None) -> bool:
        return _validated_timing(row) is not None

    binding_errors = []
    cohorts = {row.get("provenance", {}).get("cohort_sha256") for row in reports}
    if len(cohorts) != 1 or not all(isinstance(value, str) and value for value in cohorts):
        binding_errors.append("Input cohort missing or inconsistent")
    identities: dict[str, tuple[str, str]] = {}
    for observation in reports:
        provenance = observation.get("provenance", {})
        case = provenance.get("case_name")
        inputs = provenance.get("inputs_sha256")
        if not isinstance(inputs, str) or not inputs:
            binding_errors.append("Case input hash missing")
            continue
        if parity(observation):
            identity = (inputs, observation["runs"][0]["result_digest"])
            if case in identities and identities[case] != identity:
                binding_errors.append(f"Case input/result mismatch: {case}")
            identities[case] = identity
    ids = [row.get("measurement_id") for row in memory_reports]
    if not all(isinstance(value, str) and value for value in ids) or len(set(ids)) != len(ids):
        binding_errors.append("Fresh-process measurement identity missing or duplicated")

    def memory(
        case: str, workers: int, profile: str, digest: str, inputs_hash: str
    ) -> list[int] | None:
        rows = [
            row
            for row in memory_reports
            if row.get("case_name") == case
            and row.get("workers") == workers
            and row.get("profile") == profile
        ]
        valid = [
            row
            for row in rows
            if row.get("fresh_process") is True
            and isinstance(row.get("pid"), int)
            and row["pid"] > 0
            and row.get("complete") is True
            and row.get("failures") == 0
            and row.get("samples", 0) > 0
            and isinstance(row.get("sampled_peak_rss_bytes"), int)
            and row["sampled_peak_rss_bytes"] > 0
            and row.get("result_digest") == digest
            and row.get("inputs_sha256") == inputs_hash
        ]
        if (
            len(valid) != len(rows)
            or len({row["pid"] for row in valid}) != len(valid)
            or len(valid) < 3
        ):
            return None
        return [row["sampled_peak_rss_bytes"] for row in valid]

    for candidate in ("lazy", "combined"):
        reasons = list(binding_errors)
        for case, workers in required:
            row = find("baseline", candidate, case, workers)
            if not parity(row):
                reasons.append(f"Missing/incomplete parity: {case}/{workers}")
            elif not (_validated_timing(row) or {}).get("no_material_regression", False):
                reasons.append(f"Timing regression: {case}/{workers}")
        primary = find("baseline", candidate, "ranged", 1)
        if not parity(primary) or not (_validated_timing(primary) or {}).get(
            "repeatable_gain", False
        ):
            reasons.append("Primary ranged timing gain not established")
        for case, workers in (("ranged", 1), ("auto", 3), ("potions", 3)):
            row = find("baseline", candidate, case, workers)
            if not parity(row):
                reasons.append(f"Memory reference unavailable: {case}/{workers}")
                continue
            assert row is not None
            digest = row["runs"][0]["result_digest"]
            baseline = memory(case, workers, "baseline", digest, row["provenance"]["inputs_sha256"])
            optimized = memory(case, workers, candidate, digest, row["provenance"]["inputs_sha256"])
            if baseline is None or optimized is None:
                reasons.append(f"Missing/incomplete fresh-process memory: {case}/{workers}")
            elif statistics.median(optimized) > max(baseline):
                reasons.append(f"Memory regression: {case}/{workers}")
        if candidate == "combined":
            incremental = find("lazy", "combined", "ranged", 1)
            if not parity(incremental) or not (_validated_timing(incremental) or {}).get(
                "repeatable_gain", False
            ):
                reasons.append("Incremental ranged gain over lazy not established")
        profiles[candidate] = {"passed": not reasons, "reasons": reasons}
    selected = next(
        (profile for profile in ("combined", "lazy") if profiles[profile]["passed"]), "baseline"
    )
    return {"selected_profile": selected, "profiles": profiles}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, default="ranged")
    parser.add_argument("--candidate", choices=("lazy", "combined"), default="lazy")
    parser.add_argument("--reference", choices=PROFILES, default="baseline")
    parser.add_argument("--workers", type=int, choices=(1, 3), default=1)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    case, provenance = load_frozen_case(args.frozen)
    case, provenance = derive_case(case, provenance, args.case)
    report = compare_profiles(
        case,
        provenance,
        args.output,
        candidate=args.candidate,
        reference=args.reference,
        workers=args.workers,
        pairs=args.pairs,
        warmups=args.warmups,
    )
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
