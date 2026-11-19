"""P3 staged-v1 acceptance; historical P1 policies remain unchanged.

Run parity, timing, memory and select as separate phases. Never run timing while
profiling, sampling memory or running competing tests. Private inputs stay local.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import uuid
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

from tools import accept_factored_evaluation as p1
from tools.accept_gear_desktop_profiles import _write, cohort_hash
from tools.benchmark_gear_desktop import (
    case_provenance,
    environment,
    load_frozen_case,
    result_digest,
)
from tools.gear_process_memory import measure_process_tree
from tracker.gear.objective_store import materialize_result_archives

POLICY = "p3-staged-v1"
ORACLE_POLICY = "p3-staged-v2"
MODES = ("reference", "candidate")
TIMING = (
    ("fixed_melee", 1),
    ("fixed_magic", 1),
    ("configured_ranged", 1),
    ("multi", 1),
    ("configured_auto", 3),
    ("multi_auto", 3),
)
MEMORY = (("fixed_magic", 1), ("multi", 1), ("multi_auto", 3))
PARITY = (
    *p1.REQUIRED,
    ("multi_auto", 1),
    ("multi_auto", 3),
    ("multi_auto_mixed", 1),
    ("multi_auto_fixed", 1),
)


def _samples(values: list[float], sizes: tuple[int, ...]) -> None:
    if len(values) not in sizes or any(
        type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values
    ):
        raise ValueError("Invalid positive finite measurements")


def _mad(values: list[float]) -> float:
    median = statistics.median(values)
    return statistics.median([abs(v - median) for v in values])


def timing_decision(reference: list[float], candidate: list[float]) -> dict[str, Any]:
    _samples(reference, (3, 5))
    _samples(candidate, (len(reference),))
    ref, cand = statistics.median(reference), statistics.median(candidate)
    gains = [a - b for a, b in zip(reference, candidate, strict=True)]
    gain = statistics.median(gains)
    convincing = ref - cand > _mad(reference) and gain > _mad(gains)
    return {
        "reference_median": ref,
        "candidate_median": cand,
        "reference_mad": _mad(reference),
        "paired_gain_median": gain,
        "paired_gain_mad": _mad(gains),
        "convincing_gain": convincing,
        "no_material_regression": cand <= 1.05 * ref,
        "gain_inconclusive": 0 < ref - cand and not convincing,
        "tolerance_inconclusive": _mad(gains) > 0 and abs(cand - 1.05 * ref) <= _mad(gains),
        "inconclusive": (0 < ref - cand and not convincing)
        or (_mad(gains) > 0 and abs(cand - 1.05 * ref) <= _mad(gains)),
    }


def memory_decision(
    reference: list[float], candidate: list[float], *, ceiling: int | None = None
) -> dict[str, Any]:
    _samples(reference, (3,))
    _samples(candidate, (3,))
    ref, cand = statistics.median(reference), statistics.median(candidate)
    return {
        "reference_median": ref,
        "candidate_median": cand,
        "accepted": cand <= 1.05 * ref and (ceiling is None or max(candidate) <= ceiling),
    }


def derive_case(case: Any, metadata: dict[str, Any], name: str) -> tuple[Any, dict[str, Any]]:
    if not name.startswith("multi_auto"):
        return p1.derive_case(case, metadata, name)
    from tracker.gear.optimizer import OptimizationRequest

    base, meta = p1.derive_case(case, metadata, "multi")
    roles = tuple(
        role.model_copy(
            update={
                "allowed_disciplines": ("melee", "ranged", "magic")
                if index == 0 or name not in ("multi_auto_mixed", "multi_auto_fixed")
                else None,
                "combat_options": None
                if name == "multi_auto_fixed" and index == 1
                else role.combat_options,
            }
        )
        for index, role in enumerate(base.request.roles)
    )
    request = OptimizationRequest.model_validate(
        base.request.model_copy(update={"roles": roles}).model_dump()
    )
    result = replace(base, name=name, request=request)
    return result, case_provenance(
        result, **{**meta, "case_name": name, "cohort_sha256": cohort_hash(result)}
    )


def service(case: Any, enabled: bool, pool: Any) -> Any:
    from tracker.gear.service import GearService

    result = GearService(
        case.content,
        optimization_profile="combined",
        fixed_reporting=True,
        factored_evaluation=True,
        compact_states=enabled,
        auto_pool=pool,
    )
    result._equipment = case.catalog
    return result


def run(case: Any, metadata: dict[str, Any], enabled: bool, svc: Any) -> dict[str, Any]:
    if metadata.get("diagnostic"):
        from tracker.gear.optimizer import optimize

        return optimize(
            case.snapshot,
            case.request,
            case.catalog,
            case.content,
            case.prices,
            case.at,
            _execution_profile="combined",
            _fixed_reporting=True,
            _factored_evaluation=True,
            _compact_states=enabled,
            _complete_frontiers=True,
            local_refinement=metadata.get("optimization_mode") == "thorough",
        )
    return svc.optimize(
        case.snapshot,
        case.request,
        price_records=case.prices,
        now=case.at,
        local_refinement=metadata.get("optimization_mode") == "thorough",
    )


def source_hashes() -> dict[str, str]:
    paths = [
        *Path("tracker/gear").glob("*.py"),
        Path("tracker/gear_desktop.py"),
        Path(__file__),
        Path("tools/compact_state_reference.py"),
        Path("tools/benchmark_gear_desktop.py"),
        Path("tools/accept_factored_evaluation.py"),
        Path("tools/accept_fixed_reporting.py"),
        Path("tools/accept_gear_desktop_profiles.py"),
        Path("tools/gear_process_memory.py"),
    ]
    return {
        str(path.resolve().relative_to(Path.cwd())): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def bind(root: Path, frozen: Path, reference: Path | None = None) -> dict[str, Any]:
    manifest = {
        "policy": POLICY,
        "source_hashes": source_hashes(),
        "frozen_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
        "frozen_path": str(frozen.resolve()),
    }
    if reference is not None:
        from tools.compact_state_reference import reference_cohort

        manifest = {
            **manifest,
            "policy": ORACLE_POLICY,
            "reference_cohort": reference_cohort(reference, frozen),
        }
    path = root / "manifest.json"
    root.mkdir(parents=True, exist_ok=True)
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("Source/input changed: use a new evidence directory")
    _write(path, manifest)
    return manifest


def evidence_binding(directory: Path) -> str | None:
    for parent in (directory, *directory.parents):
        manifest_path = parent / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest["source_hashes"] != source_hashes():
                raise ValueError("Source changed during measurement")
            if (
                "frozen_path" in manifest
                and hashlib.sha256(Path(manifest["frozen_path"]).read_bytes()).hexdigest()
                != manifest["frozen_sha256"]
            ):
                raise ValueError("Input changed during measurement")
            if manifest["policy"] == ORACLE_POLICY:
                from tools.compact_state_reference import verify_reference

                verify_reference(manifest["reference_cohort"])
            return hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return None


def expected_inputs(root: Path, name: str) -> str:
    manifest = json.loads((root / "manifest.json").read_text())
    case, meta = load_frozen_case(Path(manifest["frozen_path"]))
    _, provenance = derive_case(case, meta, name)
    return provenance["inputs_sha256"]


def oracle_context(
    directory: Path, meta: dict[str, Any], workers: int
) -> tuple[str, str | None, str | None]:
    from tools.compact_state_reference import golden

    for parent in (directory, *directory.parents):
        path = parent / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text())
            if manifest["policy"] == ORACLE_POLICY:
                cohort = manifest["reference_cohort"]
                identity = hashlib.sha256(json.dumps(cohort, sort_keys=True).encode()).hexdigest()
                return (
                    ORACLE_POLICY,
                    golden(cohort, meta["case_name"], workers, meta["inputs_sha256"]),
                    identity,
                )
            break
    return POLICY, None, None


def compare(
    case: Any,
    meta: dict[str, Any],
    output: Path,
    workers: int,
    *,
    timing: bool,
    extend: bool = False,
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Evidence directory already contains observations; use a new revision")
    binding = evidence_binding(output)
    output.mkdir(parents=True, exist_ok=True)
    policy, expected, reference_identity = oracle_context(output, meta, workers)
    modes = ("candidate",) if policy == ORACLE_POLICY and not timing else MODES
    observations: list[dict[str, Any]] = []
    with ExitStack() as stack:
        pool = p1._pool(stack, case, workers)
        services = {mode: service(case, mode == "candidate", pool) for mode in modes}

        def execute(mode: str, label: str) -> float:
            nonlocal expected
            if evidence_binding(output) != binding:
                raise ValueError("Manifest changed during run")
            start = perf_counter()
            result = run(case, meta, mode == "candidate", services[mode])
            elapsed = perf_counter() - start
            result = materialize_result_archives(result)
            if evidence_binding(output) != binding:
                raise ValueError("Manifest changed during run")
            digest = result_digest(result)
            _write(output / f"{label}-{mode}.json", result)
            row = {"label": label, "mode": mode, "wall_seconds": elapsed, "result_digest": digest}
            observations.append(row)
            _write(output / "observations.json", observations)
            if expected is not None and digest != expected:
                raise ValueError(f"Complete parity failed: {output}/{label}/{mode}")
            expected = digest
            return elapsed

        if timing:
            for mode in MODES:
                execute(mode, "warmup")
        pairs: list[dict[str, float]] = []
        count = 3 if timing else 1
        while len(pairs) < count:
            index = len(pairs)
            order = modes if index % 2 == 0 else modes[::-1]
            pairs.append({mode: execute(mode, f"pair-{index + 1}") for mode in order})
            if timing and len(pairs) == 3 and extend:
                decision = timing_decision(
                    [p["reference"] for p in pairs], [p["candidate"] for p in pairs]
                )
                if decision["tolerance_inconclusive"] or (
                    meta.get("case_name") in ("multi", "multi_auto")
                    and decision["gain_inconclusive"]
                ):
                    count = 5
        outcome = (
            timing_decision([p["reference"] for p in pairs], [p["candidate"] for p in pairs])
            if timing
            else {}
        )
    report = {
        "policy": policy,
        "reference_cohort_sha256": reference_identity,
        "provenance": meta,
        "workers": workers,
        "pairs": pairs,
        "observations": observations,
        "result_digest": expected,
        "decision": outcome,
        "manifest_sha256": binding,
        "extension_predeclared": extend,
        "environment": environment(),
    }
    _write(output / "report.json", report)
    return report


def memory_child(frozen: Path, output: Path, name: str, workers: int, mode: str) -> None:
    binding = evidence_binding(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Memory evidence already exists")
    case, metadata = load_frozen_case(frozen)
    case, metadata = derive_case(case, metadata, name)
    policy, expected, reference_identity = oracle_context(output, metadata, workers)
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack, measure_process_tree() as memory:
        pool = p1._pool(stack, case, workers)
        result = run(case, metadata, mode == "candidate", service(case, mode == "candidate", pool))
    result = materialize_result_archives(result)
    if evidence_binding(output) != binding:
        raise ValueError("Manifest changed during memory run")
    _write(output / "result.json", result)
    if expected is not None and result_digest(result) != expected:
        raise ValueError("Memory output differs from frozen reference")
    _write(
        output / "report.json",
        {
            **memory.report(),
            "policy": policy,
            "reference_cohort_sha256": reference_identity,
            "case_name": name,
            "workers": workers,
            "mode": mode,
            "pid": os.getpid(),
            "measurement_id": str(uuid.uuid4()),
            "manifest_sha256": binding,
            "result_digest": result_digest(result),
            "provenance": metadata,
        },
    )


def validate_report(report: dict[str, Any], directory: Path, *, timing: bool) -> None:
    """Recompute parity from raw results and bind every timing to its observation."""
    if report["policy"] not in (POLICY, ORACLE_POLICY):
        raise ValueError("Wrong acceptance policy")
    pairs, observations = report["pairs"], report["observations"]
    count = len(pairs)
    if count not in ((3, 5) if timing else (1,)):
        raise ValueError("Wrong pair count")
    if count == 5:
        initial = timing_decision(
            [p["reference"] for p in pairs[:3]], [p["candidate"] for p in pairs[:3]]
        )
        if report["extension_predeclared"] is not True or not (
            initial["tolerance_inconclusive"]
            or (
                report["provenance"].get("case_name") in ("multi", "multi_auto")
                and initial["gain_inconclusive"]
            )
        ):
            raise ValueError("Undeclared or unnecessary extension")
    modes = ("candidate",) if report["policy"] == ORACLE_POLICY and not timing else MODES
    expected = [("warmup", mode) for mode in modes] if timing else []
    expected += [
        (f"pair-{i + 1}", mode)
        for i in range(count)
        for mode in (modes if i % 2 == 0 else modes[::-1])
    ]
    if [(row["label"], row["mode"]) for row in observations] != expected:
        raise ValueError("Missing, duplicated or reordered observations")
    if json.loads((directory / "observations.json").read_text()) != observations:
        raise ValueError("Observation file differs")
    for row in observations:
        raw = json.loads((directory / f"{row['label']}-{row['mode']}.json").read_text())
        if (
            result_digest(raw) != row["result_digest"]
            or row["result_digest"] != report["result_digest"]
        ):
            raise ValueError("Raw result parity mismatch")
        _samples([row["wall_seconds"]], (1,))
        if row["label"] != "warmup":
            index = int(row["label"].removeprefix("pair-")) - 1
            if pairs[index][row["mode"]] != row["wall_seconds"]:
                raise ValueError("Timing observation differs from pair")


def select(root: Path, *, historical: bool = False) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["policy"] not in (POLICY, ORACLE_POLICY):
        raise ValueError("Unknown acceptance policy")
    binding: str | None
    if historical:
        from tools.compact_state_reference import file_hash, snapshot_valid, verify_reference

        snapshot_valid(root, manifest)
        if file_hash(Path(manifest["frozen_path"])) != manifest["frozen_sha256"]:
            raise ValueError("Historical frozen input mismatch")
        if manifest["policy"] == ORACLE_POLICY:
            verify_reference(manifest["reference_cohort"])
        binding = file_hash(root / "manifest.json")
    else:
        binding = evidence_binding(root)
    reasons: list[str] = []
    identities: dict[str, tuple[str, str]] = {}
    for name, workers in PARITY:
        report = json.loads((root / "parity" / f"{name}-{workers}" / "report.json").read_text())
        if (
            report["workers"] != workers
            or report["provenance"].get("case_name") != name
            or report["provenance"]["inputs_sha256"] != expected_inputs(root, name)
            or report.get("manifest_sha256") != binding
        ):
            raise ValueError("Parity case or manifest mismatch")
        validate_report(report, root / "parity" / f"{name}-{workers}", timing=False)
        policy, expected, reference_identity = oracle_context(root, report["provenance"], workers)
        if report["policy"] != policy or (
            policy == ORACLE_POLICY
            and (
                report.get("reference_cohort_sha256") != reference_identity
                or report["result_digest"] != expected
            )
        ):
            raise ValueError("Frozen reference binding mismatch")
        observations = report["observations"]
        digests = {row["result_digest"] for row in observations}
        if len(digests) != 1 or {row["mode"] for row in observations} != (
            {"candidate"} if policy == ORACLE_POLICY else set(MODES)
        ):
            reasons.append(f"Parity: {name}/{workers}")
        identity = (report["provenance"]["inputs_sha256"], report["result_digest"])
        if name in identities and identities[name] != identity:
            reasons.append(f"Worker parity: {name}")
        identities[name] = identity
    gain = False
    for name, workers in TIMING:
        report = json.loads((root / "timing" / f"{name}-{workers}" / "report.json").read_text())
        if (
            report["workers"] != workers
            or report["provenance"].get("case_name") != name
            or report.get("manifest_sha256") != binding
        ):
            raise ValueError("Timing case or manifest mismatch")
        policy, expected, reference_identity = oracle_context(root, report["provenance"], workers)
        if report["policy"] != policy or (
            policy == ORACLE_POLICY and report.get("reference_cohort_sha256") != reference_identity
        ):
            raise ValueError("Timing reference cohort mismatch")
        validate_report(report, root / "timing" / f"{name}-{workers}", timing=True)
        if (report["provenance"]["inputs_sha256"], report["result_digest"]) != identities[name]:
            reasons.append(f"Timing input mismatch: {name}")
        pairs = report["pairs"]
        outcome = timing_decision([p["reference"] for p in pairs], [p["candidate"] for p in pairs])
        if outcome["tolerance_inconclusive"]:
            reasons.append(f"Unresolved timing variability: {name}/{workers}")
        if not outcome["no_material_regression"]:
            reasons.append(f"Timing regression: {name}/{workers}")
        if name in ("multi", "multi_auto") and outcome["convincing_gain"]:
            gain = True
        if any(row["result_digest"] != identities[name][1] for row in report["observations"]):
            reasons.append(f"Timing parity: {name}")
    if not gain:
        reasons.append("No convincing gain in intended Multi workload")
    memory = json.loads((root / "memory.json").read_text())
    if len(memory) != 6 * len(MEMORY):
        reasons.append("Wrong memory observation count")
    ids = [row["measurement_id"] for row in memory]
    if len(set(ids)) != len(ids):
        reasons.append("Duplicate memory measurement")
    for name, workers in MEMORY:
        samples = {}
        for mode in MODES:
            rows = [
                r
                for r in memory
                if (r["case_name"], r["workers"], r["mode"]) == (name, workers, mode)
            ]
            if any(
                not r["complete"]
                or r["failures"]
                or r["samples"] <= 0
                or r["result_digest"] != identities[name][1]
                for r in rows
            ):
                reasons.append(f"Memory integrity: {name}/{mode}")
            for index, row in enumerate(rows):
                if (
                    row.get("manifest_sha256") != binding
                    or row.get("includes_descendants") is not True
                    or type(row.get("pid")) is not int
                    or row["pid"] <= 0
                ):
                    reasons.append(f"Memory binding/process metadata mismatch: {name}/{mode}")
                policy, _, reference_identity = oracle_context(root, row["provenance"], workers)
                if policy == ORACLE_POLICY and (
                    row.get("policy") != policy
                    or row.get("reference_cohort_sha256") != reference_identity
                ):
                    reasons.append(f"Memory reference mismatch: {name}/{mode}")
                directory = root / "memory" / f"{name}-{workers}" / f"{mode}-{index + 1}"
                if json.loads((directory / "report.json").read_text()) != row:
                    reasons.append(f"Memory report mismatch: {name}/{mode}")
                raw = json.loads((directory / "result.json").read_text())
                if (row["provenance"]["inputs_sha256"], result_digest(raw)) != identities[name]:
                    reasons.append(f"Memory raw input/result mismatch: {name}/{mode}")
            samples[mode] = [r["sampled_peak_rss_bytes"] for r in rows]
        if not memory_decision(samples["reference"], samples["candidate"])["accepted"]:
            reasons.append(f"Memory regression: {name}")
    result = {"policy": manifest["policy"], "adopt": not reasons, "reasons": reasons}
    if not historical:
        _write(root / "selection.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("parity", "timing", "memory", "memory-child", "profile", "select")
    )
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only")
    parser.add_argument("--reference-cohort", type=Path)
    parser.add_argument(
        "--historical", action="store_true", help="Read-only archived-source selection audit"
    )
    parser.add_argument("--workers", type=int, choices=(1, 3), default=1)
    parser.add_argument("--mode", choices=MODES, default="reference")
    parser.add_argument(
        "--extend", action="store_true", help="Predeclare one three-to-five timing extension"
    )
    args = parser.parse_args()
    if args.historical and args.phase != "select":
        parser.error("--historical is only valid for select")
    if args.phase == "memory-child":
        memory_child(args.frozen, args.output, args.only, args.workers, args.mode)
        return
    if not args.historical:
        bind(args.output, args.frozen, args.reference_cohort)
    if args.phase == "select":
        print(json.dumps(select(args.output, historical=args.historical), indent=2))
        return
    case, metadata = load_frozen_case(args.frozen)
    configurations = (
        PARITY if args.phase == "parity" else MEMORY if args.phase == "memory" else TIMING
    )
    if args.only and args.only not in {name for name, _ in configurations}:
        parser.error("Unknown case for selected phase")
    memory_path = args.output / "memory.json"
    memory_rows = json.loads(memory_path.read_text()) if memory_path.exists() else []
    for name, workers in configurations:
        if args.only and name != args.only:
            continue
        print(f"{args.phase}: {name}/{workers}", flush=True)
        target = args.output / args.phase / f"{name}-{workers}"
        derived, meta = derive_case(case, metadata, name)
        if args.phase in ("parity", "timing"):
            compare(
                derived, meta, target, workers, timing=args.phase == "timing", extend=args.extend
            )
        elif args.phase == "profile":
            target.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                pool = p1._pool(stack, derived, workers)
                profiler = cProfile.Profile()
                result = profiler.runcall(
                    run,
                    derived,
                    meta,
                    args.mode == "candidate",
                    service(derived, args.mode == "candidate", pool),
                )
                profiler.dump_stats(str(target / "calls.prof"))
                _write(target / "result.json", result)
        else:
            for repeat in range(3):
                for mode in MODES:
                    child = target / f"{mode}-{repeat + 1}"
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "tools.accept_compact_states",
                            "memory-child",
                            "--frozen",
                            str(args.frozen),
                            "--output",
                            str(child),
                            "--only",
                            name,
                            "--workers",
                            str(workers),
                            "--mode",
                            mode,
                        ],
                        check=True,
                    )
                    memory_rows.append(json.loads((child / "report.json").read_text()))
                    _write(args.output / "memory.json", memory_rows)


if __name__ == "__main__":
    main()
