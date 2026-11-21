"""Fail-fast validation of the explicitly provisioned native desktop release."""

from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import json
import platform
import sys
import sysconfig
from pathlib import Path
from typing import Any

MODULES = ("_scoring", "_stages", "_frontier")
MANIFEST = "_build.json"


class NativeReadinessError(RuntimeError):
    """Native was required but a compatible, complete release is unavailable."""


def source_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.suffix in {".py", ".pyx", ".pxd", ".pxi"}
    }


def runtime_identity() -> dict[str, str | None]:
    return {
        "cache_tag": sys.implementation.cache_tag,
        "platform": sysconfig.get_platform(),
        "machine": platform.machine(),
    }


def release_manifest(directory: Path, *, coverage: bool) -> dict[str, Any]:
    binaries = {}
    for name in MODULES:
        matches = [
            directory / f"{name}{suffix}" for suffix in importlib.machinery.EXTENSION_SUFFIXES
        ]
        binary = next((path for path in matches if path.is_file()), None)
        if binary is None:
            raise NativeReadinessError(f"Missing native binary: {name}")
        binaries[binary.name] = hashlib.sha256(binary.read_bytes()).hexdigest()
    return {
        "version": 1,
        "coverage": coverage,
        "runtime": runtime_identity(),
        "sources": source_hashes(directory),
        "binaries": binaries,
    }


def require_native(directory: Path | None = None) -> dict[str, Any]:
    """Validate release identity before importing either compiled module.

    No build or dependency installation is performed here.
    """
    directory = directory or Path(__file__).resolve().parent
    try:
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise ValueError("invalid release manifest")
        if manifest.get("coverage") is not False:
            raise ValueError("a coverage build cannot run as the desktop release")
        if manifest.get("runtime") != runtime_identity():
            raise ValueError("native build belongs to another Python runtime or platform")
        if manifest.get("sources") != source_hashes(directory):
            raise ValueError("native sources changed since the release build")
        current = release_manifest(directory, coverage=False)
        if manifest.get("binaries") != current["binaries"]:
            raise ValueError("native release binaries are missing or changed")
        for name in MODULES:
            module = importlib.import_module(f"tracker.gear.native.{name}")
            if not module.__file__:
                raise ValueError("native module has no binary path")
            binary = Path(module.__file__).resolve()
            if binary.parent != directory.resolve() or binary.name not in manifest["binaries"]:
                raise ValueError("loaded native module differs from the release manifest")
        return manifest
    except (ImportError, OSError, ValueError, TypeError, NativeReadinessError) as exc:
        raise NativeReadinessError(
            "native_extension_unavailable: "
            f"{exc}. Install optional tools with python -m pip install -e .[native-build], "
            "then run python -m tools.build_gear_native and restart desktop Gear."
        ) from exc
