"""Frozen OFF-result oracle integrity for P3 staged-v2 acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tools.benchmark_gear_desktop import load_frozen_case, result_digest

NORMALIZER = Path("tools/benchmark_gear_desktop.py")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_valid(root: Path, manifest: dict[str, Any]) -> None:
    base = (root / "source-snapshot").resolve()
    for name, expected in manifest["source_hashes"].items():
        path = (base / name).resolve()
        if not path.is_relative_to(base) or file_hash(path) != expected:
            raise ValueError("Archived source snapshot mismatch")
    recorded = manifest["source_hashes"].get(str(NORMALIZER))
    if recorded != file_hash(NORMALIZER):
        raise ValueError("Reference normalization changed; new reviewed reference cohort required")


def reference_cohort(root: Path, frozen: Path) -> dict[str, Any]:
    """Validate and seal all reference raw outputs without modifying old evidence."""
    from tools.accept_compact_states import PARITY, POLICY, derive_case, validate_report

    root = root.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["policy"] != POLICY or file_hash(frozen) != manifest["frozen_sha256"]:
        raise ValueError("Reference policy or frozen input mismatch")
    snapshot_valid(root, manifest)
    binding = file_hash(manifest_path)
    case, meta = load_frozen_case(frozen)
    rows = {}
    files = {"manifest.json": binding}
    for name, digest in manifest["source_hashes"].items():
        files[str(Path("source-snapshot") / name)] = digest
    for name, workers in PARITY:
        directory = root / "parity" / f"{name}-{workers}"
        report = json.loads((directory / "report.json").read_text())
        _, expected = derive_case(case, meta, name)
        if (
            report["policy"] != POLICY
            or report["workers"] != workers
            or report["provenance"]["case_name"] != name
            or report["provenance"]["inputs_sha256"] != expected["inputs_sha256"]
            or report["manifest_sha256"] != binding
        ):
            raise ValueError("Reference case/provenance/source mismatch")
        validate_report(report, directory, timing=False)
        raw_path = directory / "pair-1-reference.json"
        digest = result_digest(json.loads(raw_path.read_text()))
        rows[f"{name}-{workers}"] = {
            "case_name": name,
            "workers": workers,
            "inputs_sha256": expected["inputs_sha256"],
            "result_digest": digest,
            "raw_sha256": file_hash(raw_path),
        }
        for path in (
            raw_path,
            directory / "report.json",
            directory / "observations.json",
            directory / "pair-1-candidate.json",
        ):
            files[str(path.relative_to(root))] = file_hash(path)
    return {
        "root": str(root),
        "reference_manifest_sha256": binding,
        "reference_source_hashes": manifest["source_hashes"],
        "frozen_sha256": manifest["frozen_sha256"],
        "normalizer_sha256": file_hash(NORMALIZER),
        "files": files,
        "cases": rows,
    }


def verify_reference(cohort: dict[str, Any]) -> None:
    """Detect any changed source, provenance or raw bytes after cohort sealing."""
    root = Path(cohort["root"]).resolve()
    if file_hash(NORMALIZER) != cohort["normalizer_sha256"]:
        raise ValueError("Reference normalizer mismatch")
    for name, digest in cohort["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or file_hash(path) != digest:
            raise ValueError("Reference cohort tampered or incomplete")


def golden(cohort: dict[str, Any], name: str, workers: int, inputs: str) -> str:
    row = cohort["cases"][f"{name}-{workers}"]
    if row["case_name"] != name or row["workers"] != workers or row["inputs_sha256"] != inputs:
        raise ValueError("Reference case or input identity mismatch")
    return str(row["result_digest"])
