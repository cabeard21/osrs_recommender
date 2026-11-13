"""Native startup checks are deterministic and do not require a compiler."""

import json
from types import SimpleNamespace

import pytest

from tracker.gear.native import readiness


@pytest.fixture
def release(tmp_path, monkeypatch):
    for name in readiness.MODULES:
        (tmp_path / f"{name}{readiness.importlib.machinery.EXTENSION_SUFFIXES[0]}").write_bytes(
            b"binary"
        )
    (tmp_path / "packing.py").write_text("# frozen source\n")
    manifest = readiness.release_manifest(tmp_path, coverage=False)
    (tmp_path / readiness.MANIFEST).write_text(json.dumps(manifest))
    calls = []

    def load(name):
        calls.append(name)
        stem = name.rsplit(".", 1)[-1]
        return SimpleNamespace(
            __file__=str(tmp_path / f"{stem}{readiness.importlib.machinery.EXTENSION_SUFFIXES[0]}")
        )

    monkeypatch.setattr(readiness.importlib, "import_module", load)
    return tmp_path, calls


def test_complete_release_imports_both_modules(release):
    directory, calls = release
    result = readiness.require_native(directory)
    assert result["coverage"] is False
    assert calls == [f"tracker.gear.native.{name}" for name in readiness.MODULES]


@pytest.mark.parametrize(
    "fault", ["manifest", "json", "schema", "coverage", "runtime", "source", "binary", "missing"]
)
def test_invalid_release_rejected_before_import(release, fault):
    directory, calls = release
    path = directory / readiness.MANIFEST
    if fault == "manifest":
        path.unlink()
    elif fault == "json":
        path.write_text("{")
    elif fault in {"schema", "coverage", "runtime"}:
        manifest = json.loads(path.read_text())
        manifest[{"schema": "version", "coverage": "coverage", "runtime": "runtime"}[fault]] = None
        path.write_text(json.dumps(manifest))
    elif fault == "source":
        (directory / "packing.py").write_text("# changed\n")
    else:
        binary = next(directory.glob("_stages*"))
        if fault == "missing":
            binary.unlink()
        else:
            binary.write_bytes(b"changed")
    with pytest.raises(readiness.NativeReadinessError, match=r"tools\.build_gear_native"):
        readiness.require_native(directory)
    assert calls == []


def test_import_failure_is_actionable(release, monkeypatch):
    directory, _ = release

    def unavailable(name):
        raise ImportError("DLL load failed")

    monkeypatch.setattr(readiness.importlib, "import_module", unavailable)
    with pytest.raises(readiness.NativeReadinessError, match="DLL load failed"):
        readiness.require_native(directory)


def test_loaded_module_must_match_release_directory(release, monkeypatch):
    directory, _ = release
    monkeypatch.setattr(
        readiness.importlib, "import_module", lambda name: SimpleNamespace(__file__="elsewhere.pyd")
    )
    with pytest.raises(readiness.NativeReadinessError, match="differs from the release"):
        readiness.require_native(directory)


def test_missing_build_product_cannot_create_manifest(tmp_path):
    with pytest.raises(readiness.NativeReadinessError, match="Missing native binary"):
        readiness.release_manifest(tmp_path, coverage=False)
