"""Correctness-only native adoption on frozen desktop inputs.

Run --phase archives for complete unsampled archives, and --phase service for
public-service and serial/six-worker parity. Each engine runs once, without
warmups, timing decisions, memory sampling, or available-RAM requirements.
Private inputs and raw outputs belong under the ignored .tmp directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from tools.accept_compact_states import PARITY, derive_case
from tools.accept_gear_desktop_profiles import _write
from tools.benchmark_gear_desktop import load_frozen_case, result_digest
from tools.native_effect_cases import EFFECT_CASES, derive_effect_case
from tools.p5_experiment import (
    RunSpec,
    build_environment,
    execute,
    native_target_executed,
    source_hashes,
)

POLICY = "native-adoption-correctness-v1"
SERVICE_CASES = tuple(dict.fromkeys((name, 6 if n == 3 else n) for name, n in PARITY))
ARCHIVE_CASES = tuple(dict.fromkeys((name, 1) for name, _ in SERVICE_CASES))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(root: Path, frozen: Path) -> str:
    """Bind incremental case runs to the same source, binaries and frozen inputs."""
    manifest = {
        "policy": POLICY,
        "frozen_path": str(frozen.resolve()),
        "frozen_sha256": _hash(frozen),
        "source_hashes": source_hashes(),
        "build": build_environment(),
    }
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("Source/input/build changed: use a new evidence directory")
    _write(path, manifest)
    return _hash(path)


def verify_binding(directory: Path) -> str:
    for root in (directory, *directory.parents):
        path = root / "manifest.json"
        if not path.is_file():
            continue
        manifest = json.loads(path.read_text())
        if manifest.get("policy") != POLICY:
            raise ValueError("Wrong adoption evidence policy")
        if _hash(Path(manifest["frozen_path"])) != manifest["frozen_sha256"]:
            raise ValueError("Frozen input changed")
        if source_hashes() != manifest["source_hashes"]:
            raise ValueError("Source/binary changed")
        if build_environment() != manifest["build"]:
            raise ValueError("Build environment changed")
        return _hash(path)
    raise ValueError("Missing adoption evidence manifest")


@contextmanager
def session(case: Any, spec: RunSpec) -> Iterator[Any]:
    """One observation owns its service and, if needed, its whole process pool."""
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.service import GearService

    if spec.native:
        from tracker.gear.native.readiness import require_native

        require_native()
    with ExitStack() as stack:
        pool = None
        if spec.workers > 1:
            pool = AutoProcessPool(spec.workers)
            stack.callback(pool.close)
            pool.start(case.content, case.catalog, native_required=spec.native)
        service = GearService(
            case.content,
            optimization_profile="combined",
            fixed_reporting=True,
            factored_evaluation=True,
            compact_states=True,
            native_search=spec.native,
            auto_pool=pool,
        )
        service._equipment = case.catalog
        yield service


def _specifications(phase: str, workers: int) -> tuple[tuple[str, RunSpec], ...]:
    if phase not in ("archives", "service"):
        raise ValueError("Invalid correctness phase")
    if workers not in (1, 6) or (phase == "archives" and workers != 1):
        raise ValueError("Invalid correctness workers")
    specs = (("reference", RunSpec(workers, False)), ("candidate", RunSpec(workers, True)))
    return (*specs, ("candidate_serial", RunSpec(1, True))) if workers == 6 else specs


def required_native_executed(diagnostics: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Effect cohorts must execute stages and every affected discipline."""
    if not native_target_executed(diagnostics):
        return False
    if not metadata.get("effect_case"):
        return True
    events = diagnostics.get("events", [])
    stages = {
        (
            style,
            "cost" if row.get("cost") else "secondary" if row.get("frontier") else "dps",
            bool(row.get("metric")),
        )
        for row in events
        if row.get("event") == "stage" and row.get("attempts", 0) > 0
        for style in row.get("roles", ())
    }
    return all(
        (style, lane, metric) in stages
        for style in metadata.get("required_effect_styles", ())
        for lane, metric in (
            ("dps", False),
            ("secondary", False),
            ("secondary", True),
            ("cost", False),
            ("cost", True),
        )
    )


def compare(
    case: Any,
    meta: dict[str, Any],
    output: Path,
    *,
    phase: str,
    workers: int,
) -> dict[str, Any]:
    specs = _specifications(phase, workers)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Evidence directory already contains observations; use a new revision")
    binding = verify_binding(output)
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "policy": POLICY,
        "phase": phase,
        "workers": workers,
        "provenance": meta,
        "manifest_sha256": binding,
        "observations": [],
        "accepted": False,
    }
    for label, spec in specs:
        if verify_binding(output) != binding:
            raise ValueError("Evidence binding changed during request")
        with session(case, spec) as service:
            result, diagnostics = execute(
                case,
                meta,
                spec,
                service,
                archives=phase == "archives",
                force_cost=phase == "archives",
            )
        path = output / f"{label}.json"
        _write(path, result)
        report["observations"].append(
            {
                "label": label,
                "workers": spec.workers,
                "native_enabled": spec.native,
                "raw_sha256": _hash(path),
                "result_digest": result_digest(result),
                "native": diagnostics,
            }
        )
        _write(output / "report.json", report)
        if verify_binding(output) != binding:
            raise ValueError("Evidence binding changed during request")
        if spec.native and not required_native_executed(diagnostics, meta):
            raise ValueError(f"Required native execution did not occur: {label}")
        if report["observations"][0]["result_digest"] != result_digest(result):
            raise ValueError(f"Exact result parity failed: {label}")
    report = {**report, "accepted": True}
    _write(output / "report.json", report)
    return validate_report(output)


def validate_report(output: Path) -> dict[str, Any]:
    """Recompute raw digests and native coverage without trusting report verdicts."""
    report = json.loads((output / "report.json").read_text())
    if report.get("policy") != POLICY:
        raise ValueError("Wrong adoption report policy")
    if report.get("manifest_sha256") != verify_binding(output):
        raise ValueError("Evidence binding changed")
    specs = _specifications(report["phase"], report["workers"])
    rows = report["observations"]
    if len(rows) != len(specs):
        raise ValueError("Incomplete correctness observations")
    expected = None
    for row, (label, spec) in zip(rows, specs, strict=True):
        if (row["label"], row["workers"], row["native_enabled"]) != (
            label,
            spec.workers,
            spec.native,
        ):
            raise ValueError("Invalid correctness observations")
        path = output / f"{label}.json"
        if _hash(path) != row["raw_sha256"]:
            raise ValueError("Raw output changed")
        digest = result_digest(json.loads(path.read_text()))
        if digest != row["result_digest"] or (expected is not None and digest != expected):
            raise ValueError("Exact result parity failed")
        if spec.native and not required_native_executed(row["native"], report["provenance"]):
            raise ValueError("Required native execution did not occur")
        expected = digest
    if report.get("accepted") is not True:
        raise ValueError("Incomplete correctness verdict")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=Path(".tmp/desktop-controlled/inputs.json"))
    parser.add_argument("--output", type=Path, default=Path(".tmp/native-adoption"))
    parser.add_argument("--phase", choices=("archives", "service"), default="archives")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", choices=(*dict(ARCHIVE_CASES), *EFFECT_CASES))
    selection.add_argument("--all", action="store_true")
    selection.add_argument(
        "--effects", action="store_true", help="Run reviewed equipment-effect mechanism cases"
    )
    parser.add_argument("--workers", type=int, choices=(1, 6))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    if args.validate:
        paths = (
            [args.output]
            if (args.output / "report.json").is_file()
            else [path.parent for path in sorted(args.output.rglob("report.json"))]
        )
        if not paths:
            parser.error("No correctness reports found")
        for path in paths:
            validate_report(path)
        print(json.dumps({"accepted": True, "reports": len(paths)}))
        return
    if not (args.case or args.all or args.effects):
        parser.error("Choose --case, --all or --effects")
    effects = args.effects or args.case in EFFECT_CASES
    declared = (
        tuple(
            (name, n)
            for name in EFFECT_CASES
            for n in ((1,) if args.phase == "archives" else (1, 6))
        )
        if effects
        else ARCHIVE_CASES
        if args.phase == "archives"
        else SERVICE_CASES
    )
    selected = tuple(
        (name, n)
        for name, n in declared
        if (args.all or args.effects or name == args.case)
        and (args.workers is None or n == args.workers)
    )
    if not selected:
        parser.error("No declared cases match this phase and worker count")
    bind(args.output, args.frozen)
    base, provenance = load_frozen_case(args.frozen)
    for name, workers in selected:
        case, meta = (derive_effect_case if effects else derive_case)(base, provenance, name)
        directory = args.output / args.phase / f"{name}-{workers}"
        report = compare(case, meta, directory, phase=args.phase, workers=workers)
        print(
            json.dumps(
                {
                    "case": name,
                    "workers": workers,
                    "phase": args.phase,
                    "accepted": report["accepted"],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
