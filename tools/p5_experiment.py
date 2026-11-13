"""Offline P5 screens and decisions; historical P1/P3 evidence is unchanged.

Examples: python -m tools.p5_experiment --help. All inputs/results stay in .tmp.
Timing uses warm services; memory uses separate fresh process trees.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import statistics
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from time import perf_counter
from typing import Any

from tools.accept_compact_states import derive_case, timing_decision
from tools.accept_gear_desktop_profiles import _write
from tools.benchmark_gear_desktop import environment, load_frozen_case, result_digest
from tools.gear_process_memory import measure_process_tree, windows_tree_rss

POLICY = "p5-pilot-v1"
MEMORY_CEILING = 4 * 1024**3
MIN_AVAILABLE = 6 * 1024**3
MODES = ("reference", "candidate")


@dataclass(frozen=True)
class RunSpec:
    workers: int
    native: bool

    def __post_init__(self) -> None:
        if type(self.workers) is not int or not 1 <= self.workers <= 6:
            raise ValueError("Workers must be integers from one through six")
        if type(self.native) is not bool:
            raise ValueError("Native must be boolean")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid(values: list[float], counts: tuple[int, ...] = (3, 5)) -> None:
    if len(values) not in counts or any(
        type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values
    ):
        raise ValueError("Expected positive finite measurements")


def timing_gate(
    reference: list[float], candidate: list[float], *, native: bool, control: bool = False
) -> dict:
    _valid(reference)
    _valid(candidate, (len(reference),))
    outcome = timing_decision(reference, candidate)
    ratio = outcome["candidate_median"] / outcome["reference_median"]
    threshold = 1.05 if control else 0.5 if native else 1.0
    residuals = [b - threshold * a for a, b in zip(reference, candidate, strict=True)]
    residual_median = statistics.median(residuals)
    residual_mad = statistics.median([abs(r - residual_median) for r in residuals])
    uncertain = residual_mad > 0 and abs(residual_median) <= residual_mad
    return {
        **outcome,
        "ratio": ratio,
        "speedup": 1 / ratio,
        "target_ratio": threshold,
        "target_inconclusive": uncertain,
        "inconclusive": uncertain or (not control and outcome["gain_inconclusive"]),
        "accepted": (control or outcome["convincing_gain"])
        and ratio <= threshold
        and not uncertain,
    }


def memory_gate(
    reference: list[float], candidate: list[float], *, native: bool, ceiling: int
) -> dict:
    _valid(reference, (3,))
    _valid(candidate, (3,))
    ref, cand = statistics.median(reference), statistics.median(candidate)
    return {
        "reference_median": ref,
        "candidate_median": cand,
        "ratio": cand / ref,
        "ceiling": ceiling,
        "accepted": max(candidate) <= ceiling and (not native or cand <= 1.05 * ref),
    }


def native_target_executed(diagnostics: dict) -> bool:
    native = diagnostics.get("native_requests")
    fallback = diagnostics.get("fallback_requests")
    return type(native) is int and native > 0 and type(fallback) is int and fallback == 0


def source_hashes() -> dict[str, str]:
    paths = [
        *Path("tracker/gear").rglob("*.py"),
        *Path("tracker/gear").rglob("*.pyx"),
        *Path("tracker/gear").rglob("*.pxd"),
        *Path("tracker/gear").rglob("*.pyd"),
        Path("tracker/gear_desktop.py"),
        Path("pyproject.toml"),
        *Path("tools").glob("*.py"),
    ]
    return {p.as_posix(): _hash(p) for p in sorted(set(paths))}


def build_environment() -> dict:
    versions: dict[str, str | None] = {}
    for package in ("Cython", "setuptools", "pydantic", "pydantic-settings"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    native_build = Path(".tmp/native-build/last-build.json")
    return {
        "python": sys.version,
        "packages": versions,
        "environment": environment(),
        "native_build": json.loads(native_build.read_text()) if native_build.exists() else None,
    }


def bind(root: Path, frozen: Path, settings: dict) -> str:
    manifest = {
        "policy": POLICY,
        "frozen_path": str(frozen.resolve()),
        "frozen_sha256": _hash(frozen),
        "source_hashes": source_hashes(),
        "build": build_environment(),
        "settings": settings,
    }
    path = root / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("Source/input/settings changed: use a new evidence directory")
    root.mkdir(parents=True, exist_ok=True)
    _write(path, manifest)
    return _hash(path)


def verify_binding(root: Path) -> str:
    for directory in (root, *root.parents):
        path = directory / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text())
            if manifest["policy"] != POLICY:
                raise ValueError("Wrong experiment policy")
            if _hash(Path(manifest["frozen_path"])) != manifest["frozen_sha256"]:
                raise ValueError("Input changed")
            if source_hashes() != manifest["source_hashes"]:
                raise ValueError("Source changed during measurement")
            build = build_environment()
            if any(
                build.get(k) != manifest["build"].get(k)
                for k in ("python", "packages", "native_build")
            ):
                raise ValueError("Build environment changed during measurement")
            return _hash(path)
    raise ValueError("Missing evidence manifest")


def available_memory() -> int:
    class Memory(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "page",
                "free_page",
                "virtual",
                "free_virtual",
                "extended",
            )
        ]

    if sys.platform != "win32":
        raise OSError("This desktop experiment requires Windows")
    value = Memory()
    value.length = ctypes.sizeof(Memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise OSError("Cannot read available physical memory")
    return value.available


@contextmanager
def sessions(case: Any, specs: dict[str, RunSpec]) -> Iterator[dict[str, Any]]:
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.service import GearService

    with ExitStack() as stack:
        pools, services = {}, {}
        for mode, spec in specs.items():
            if spec.workers > 1 and spec.workers not in pools:
                pool = AutoProcessPool(spec.workers)
                stack.callback(pool.close)
                pool.start(case.content, case.catalog)
                pools[spec.workers] = pool
            native_options: dict[str, Any] = {"native_search": True} if spec.native else {}
            service = GearService(
                case.content,
                optimization_profile="combined",
                fixed_reporting=True,
                factored_evaluation=True,
                compact_states=True,
                auto_pool=pools.get(spec.workers),
                **native_options,
            )
            service._equipment = case.catalog
            services[mode] = service
        yield services


def execute(
    case: Any,
    meta: dict,
    spec: RunSpec,
    service: Any,
    *,
    archives: bool = False,
    force_cost: bool = False,
    cancelled: Any = None,
) -> tuple[dict, dict]:
    if archives:
        from tracker.gear.optimizer import optimize

        context: Any
        native_options: dict[str, Any] = {"_native_search": True} if spec.native else {}
        if spec.native:
            from tracker.gear.native import capture

            context = capture()
        else:
            context = nullcontext()
        with context as collector:
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
                _running_frontier=force_cost,
                cancelled=cancelled,
                **native_options,
                local_refinement=meta.get("optimization_mode") == "thorough",
            )
        diagnostics = collector.snapshot() if collector else {}
    else:
        result = service.optimize(
            case.snapshot,
            case.request,
            price_records=case.prices,
            now=case.at,
            cancelled=cancelled,
            local_refinement=meta.get("optimization_mode") == "thorough",
        )
        diagnostics = getattr(service, "native_diagnostics", {}) if spec.native else {}
    return result, diagnostics


def compare(
    case: Any,
    meta: dict,
    output: Path,
    specs: dict[str, RunSpec],
    *,
    pairs: int,
    extend: bool = False,
    archives: bool = False,
    force_cost: bool = False,
    require_native: bool = False,
    control: bool = False,
) -> dict:
    if pairs not in (1, 3):
        raise ValueError("Use one screen pair or three qualification pairs")
    if specs["candidate"].native and specs["candidate"].workers != specs["reference"].workers:
        raise ValueError("Native comparisons require equal worker counts")
    if require_native and not specs["candidate"].native:
        raise ValueError("Native execution requirement needs a native candidate")
    if force_cost and not archives:
        raise ValueError("Forced-cost diagnostics require complete archives")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Observation directory must be empty")
    binding = verify_binding(output)
    output.mkdir(parents=True, exist_ok=True)
    expected = None
    observations: list[dict[str, Any]] = []
    pair_rows: list[dict[str, float]] = []

    def observe(mode: str, label: str, service: Any) -> float:
        nonlocal expected
        if verify_binding(output) != binding:
            raise ValueError("Manifest changed")
        started = perf_counter()
        result, diagnostics = execute(
            case, meta, specs[mode], service, archives=archives, force_cost=force_cost
        )
        elapsed = perf_counter() - started
        if verify_binding(output) != binding:
            raise ValueError("Manifest changed")
        _write(output / f"{label}-{mode}.json", result)
        digest = result_digest(result)
        observations.append(
            {
                "mode": mode,
                "label": label,
                "wall_seconds": elapsed,
                "result_digest": digest,
                "native": diagnostics,
            }
        )
        _write(output / "observations.json", observations)
        print(f"{label}/{mode}: {elapsed:.3f}s", flush=True)
        if expected is not None and digest != expected:
            raise ValueError("Complete result parity failed")
        if require_native and specs[mode].native and not native_target_executed(diagnostics):
            raise ValueError("Native target fell back or executed no native request")
        expected = digest
        return elapsed

    count = pairs
    while len(pair_rows) < count:
        index = len(pair_rows)
        order = MODES if index % 2 == 0 else MODES[::-1]
        pair = {}
        for mode in order:
            with sessions(case, {mode: specs[mode]}) as services:
                if pairs == 3:
                    observe(mode, f"warmup-pair-{index + 1}", services[mode])
                pair[mode] = observe(mode, f"pair-{index + 1}", services[mode])
        pair_rows.append(pair)
        if len(pair_rows) == 3 and extend:
            decision = timing_gate(
                [p["reference"] for p in pair_rows],
                [p["candidate"] for p in pair_rows],
                native=specs["candidate"].native,
                control=control,
            )
            if decision["inconclusive"]:
                count = 5
    decision = (
        timing_gate(
            [p["reference"] for p in pair_rows],
            [p["candidate"] for p in pair_rows],
            native=specs["candidate"].native,
            control=control,
        )
        if pairs == 3
        else {"accepted": False, "screen_only": True}
    )
    report = {
        "policy": POLICY,
        "manifest_sha256": binding,
        "provenance": meta,
        "specs": {k: asdict(v) for k, v in specs.items()},
        "pairs": pair_rows,
        "observations": observations,
        "result_digest": expected,
        "decision": decision,
        "extension_predeclared": extend,
        "archives": archives,
        "force_cost": force_cost,
        "require_native": require_native,
        "control": control,
        "pool_lifetime": "one_mode_per_observation_with_untimed_warmup",
    }
    _write(output / "report.json", report)
    return report


def validate_report(output: Path) -> dict:
    report = json.loads((output / "report.json").read_text())
    if report["policy"] != POLICY or report["manifest_sha256"] != verify_binding(output):
        raise ValueError("Evidence binding mismatch")
    manifest = next(
        (p / "manifest.json" for p in (output, *output.parents) if (p / "manifest.json").exists()),
        None,
    )
    if manifest is not None:
        settings = json.loads(manifest.read_text())["settings"]
        if (
            report["specs"] != settings["specs"]
            or report["provenance"]["case_name"] != settings["case"]
        ):
            raise ValueError("Report differs from bound configuration")
        for field in ("require_native", "force_cost", "control"):
            if report[field] != settings[field]:
                raise ValueError("Report differs from bound configuration")
        if report["extension_predeclared"] != settings["extend"]:
            raise ValueError("Report differs from bound configuration")
        if report["archives"] != (settings["phase"] == "parity") or (len(report["pairs"]) >= 3) != (
            settings["phase"] == "timing"
        ):
            raise ValueError("Report differs from bound phase")
    observations, pairs = report["observations"], report["pairs"]
    if len(pairs) not in (1, 3, 5):
        raise ValueError("Invalid pair count")
    expected_order = [
        (label, mode)
        for i in range(len(pairs))
        for mode in (MODES if i % 2 == 0 else MODES[::-1])
        for label in (
            [f"warmup-pair-{i + 1}", f"pair-{i + 1}"] if len(pairs) >= 3 else [f"pair-{i + 1}"]
        )
    ]
    if [(r["label"], r["mode"]) for r in observations] != expected_order:
        raise ValueError("Observation order mismatch")
    if observations != json.loads((output / "observations.json").read_text()):
        raise ValueError("Observation file mismatch")
    for row in observations:
        raw = json.loads((output / f"{row['label']}-{row['mode']}.json").read_text())
        if (
            result_digest(raw) != row["result_digest"]
            or row["result_digest"] != report["result_digest"]
        ):
            raise ValueError("Raw result parity mismatch")
        _valid([row["wall_seconds"]], (1,))
        if not row["label"].startswith("warmup"):
            index = int(row["label"].split("-")[1]) - 1
            if pairs[index][row["mode"]] != row["wall_seconds"]:
                raise ValueError("Timing differs from observation")
        if (
            report["require_native"]
            and report["specs"][row["mode"]]["native"]
            and not native_target_executed(row["native"])
        ):
            raise ValueError("Native target fallback")
    if len(pairs) >= 3:
        decision = timing_gate(
            [p["reference"] for p in pairs],
            [p["candidate"] for p in pairs],
            native=report["specs"]["candidate"]["native"],
            control=report["control"],
        )
        if decision != report["decision"]:
            raise ValueError("Decision differs from observations")
        if len(pairs) == 5:
            first = timing_gate(
                [p["reference"] for p in pairs[:3]],
                [p["candidate"] for p in pairs[:3]],
                native=report["specs"]["candidate"]["native"],
                control=report["control"],
            )
            if not report["extension_predeclared"] or not first["inconclusive"]:
                raise ValueError("Unjustified timing extension")
    elif report["decision"] != {"accepted": False, "screen_only": True}:
        raise ValueError("Screen decision cannot qualify a gain")
    return report


def memory_child(frozen: Path, output: Path, case_name: str, spec: RunSpec) -> dict:
    binding = verify_binding(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Memory evidence already exists")
    case, meta = load_frozen_case(frozen)
    case, meta = derive_case(case, meta, case_name)
    output.mkdir(parents=True, exist_ok=True)
    exceeded = Event()

    def sample(pid: int) -> int:
        rss = windows_tree_rss(pid)
        if rss > MEMORY_CEILING:
            exceeded.set()
        return rss

    # Stop sampling before pool teardown, so an exiting worker cannot invalidate
    # an otherwise complete sample. Startup and both requests remain included.
    with ExitStack() as resources, measure_process_tree(sampler=sample) as stats:
        services = resources.enter_context(sessions(case, {"candidate": spec}))
        warmup, _ = execute(case, meta, spec, services["candidate"], cancelled=exceeded.is_set)
        result, diagnostics = execute(
            case, meta, spec, services["candidate"], cancelled=exceeded.is_set
        )
    if verify_binding(output) != binding:
        raise ValueError("Manifest changed during memory run")
    _write(output / "result.json", result)
    _write(output / "warmup.json", warmup)
    if result_digest(warmup) != result_digest(result):
        raise ValueError("Memory warmup/result parity mismatch")
    report = {
        **stats.report(),
        "policy": POLICY,
        "manifest_sha256": binding,
        "pid": os.getpid(),
        "measurement_id": str(uuid.uuid4()),
        "provenance": meta,
        "spec": asdict(spec),
        "result_digest": result_digest(result),
        "native": diagnostics,
        "warmup_digest": result_digest(warmup),
    }
    _write(output / "report.json", report)
    return report


def summarize_memory(root: Path) -> dict:
    binding = verify_binding(root)
    manifest = json.loads((root / "manifest.json").read_text())
    settings = manifest["settings"]
    samples: dict[str, list[float]] = {mode: [] for mode in MODES}
    seen, expected = set(), None
    for index in range(3):
        for mode in MODES:
            directory = root / f"{mode}-{index + 1}"
            row = json.loads((directory / "report.json").read_text())
            raw = json.loads((directory / "result.json").read_text())
            warmup = json.loads((directory / "warmup.json").read_text())
            digest = result_digest(raw)
            if (
                row["manifest_sha256"] != binding
                or row["policy"] != POLICY
                or row["spec"] != settings["specs"][mode]
                or row["provenance"]["case_name"] != settings["case"]
                or not row["complete"]
                or row["failures"] != 0
                or row["samples"] <= 0
                or row["includes_descendants"] is not True
                or type(row["pid"]) is not int
                or row["pid"] <= 0
                or row["measurement_id"] in seen
            ):
                raise ValueError("Invalid memory observation")
            identity = (row["provenance"]["inputs_sha256"], digest)
            if (
                digest != row["result_digest"]
                or digest != result_digest(warmup)
                or digest != row["warmup_digest"]
                or (expected is not None and expected != identity)
            ):
                raise ValueError("Memory result parity mismatch")
            if (
                settings["require_native"]
                and row["spec"]["native"]
                and not native_target_executed(row["native"])
            ):
                raise ValueError("Memory native target fallback")
            expected = identity
            seen.add(row["measurement_id"])
            samples[mode].append(row["sampled_peak_rss_bytes"])
    decision = memory_gate(
        samples["reference"],
        samples["candidate"],
        native=settings["specs"]["candidate"]["native"],
        ceiling=settings["memory_ceiling"],
    )
    report = {
        "policy": POLICY,
        "manifest_sha256": binding,
        "samples": samples,
        "decision": decision,
    }
    _write(root / "summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=("screen", "timing", "parity", "memory", "memory-child", "validate", "preflight"),
    )
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", default="multi")
    parser.add_argument("--reference-workers", type=int, default=1)
    parser.add_argument("--candidate-workers", type=int, default=1)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--extend", action="store_true")
    parser.add_argument("--force-cost", action="store_true")
    parser.add_argument("--control", action="store_true")
    args = parser.parse_args()
    if args.require_native and not args.native:
        parser.error("--require-native requires --native")
    if (
        args.native
        and args.phase != "memory-child"
        and args.reference_workers != args.candidate_workers
    ):
        parser.error("Native comparisons require equal worker counts")
    if args.force_cost and args.phase != "parity":
        parser.error("--force-cost is only supported by parity")
    if args.phase == "preflight":
        free = available_memory()
        print(
            json.dumps(
                {
                    "available_bytes": free,
                    "required_bytes": MIN_AVAILABLE,
                    "logical_cpus": os.cpu_count(),
                    "ready": free >= MIN_AVAILABLE,
                }
            )
        )
        if free < MIN_AVAILABLE:
            raise SystemExit(2)
        return
    specs = {
        "reference": RunSpec(args.reference_workers, False),
        "candidate": RunSpec(args.candidate_workers, args.native),
    }
    if args.phase == "validate":
        print(json.dumps(validate_report(args.output)["decision"], indent=2))
        return
    if args.phase == "memory-child":
        memory_child(args.frozen, args.output, args.case, specs["candidate"])
        return
    if max(spec.workers for spec in specs.values()) > 1 and available_memory() < MIN_AVAILABLE:
        raise ValueError("Measurement blocked: less than 6 GiB physical memory available")
    bind(
        args.output,
        args.frozen,
        {
            "phase": args.phase,
            "case": args.case,
            "specs": {k: asdict(v) for k, v in specs.items()},
            "extend": args.extend,
            "require_native": args.require_native,
            "force_cost": args.force_cost,
            "memory_ceiling": MEMORY_CEILING,
            "control": args.control,
        },
    )
    if args.phase == "memory":
        for index in range(3):
            for mode, spec in specs.items():
                command = [
                    sys.executable,
                    "-m",
                    "tools.p5_experiment",
                    "memory-child",
                    "--frozen",
                    str(args.frozen),
                    "--output",
                    str(args.output / f"{mode}-{index + 1}"),
                    "--case",
                    args.case,
                    "--candidate-workers",
                    str(spec.workers),
                ]
                subprocess.run([*command, *(["--native"] if spec.native else [])], check=True)
        print(json.dumps(summarize_memory(args.output)["decision"], indent=2))
        return
    case, meta = load_frozen_case(args.frozen)
    case, meta = derive_case(case, meta, args.case)
    report = compare(
        case,
        meta,
        args.output / "runs",
        specs,
        pairs=3 if args.phase == "timing" else 1,
        extend=args.extend,
        archives=args.phase == "parity",
        force_cost=args.force_cost,
        require_native=args.require_native,
        control=args.control,
    )
    print(json.dumps(report["decision"], indent=2))


if __name__ == "__main__":
    main()
