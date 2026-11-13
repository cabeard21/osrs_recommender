import json

import pytest

from tools import accept_compact_states as tool
from tools import compact_state_reference as reference


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    frozen = tmp_path / "inputs.json"
    frozen.write_text("{}")
    normalizer = reference.NORMALIZER
    hashes = {str(normalizer): reference.file_hash(normalizer)}
    target = root / "source-snapshot" / normalizer
    target.parent.mkdir(parents=True)
    target.write_bytes(normalizer.read_bytes())
    manifest = {
        "policy": tool.POLICY,
        "source_hashes": hashes,
        "frozen_path": str(frozen),
        "frozen_sha256": reference.file_hash(frozen),
    }
    tool._write(root / "manifest.json", manifest)
    monkeypatch.setattr(tool, "source_hashes", lambda: hashes)
    monkeypatch.setattr(tool, "PARITY", (("multi", 1),))
    meta = {"case_name": "multi", "inputs_sha256": "scenario"}
    monkeypatch.setattr(tool, "derive_case", lambda *args: (None, meta))
    monkeypatch.setattr(reference, "load_frozen_case", lambda *args: (None, {}))
    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    tool.compare(None, meta, root / "parity/multi-1", 1, timing=False)
    return root, frozen, meta


def test_cohort_seals_sources_inputs_all_raw_results_without_edits(cohort):
    root, frozen, _ = cohort
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    record = reference.reference_cohort(root, frozen)
    reference.verify_reference(record)
    assert reference.golden(record, "multi", 1, "scenario") == tool.result_digest({"score": 1})
    assert record["reference_source_hashes"]
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "fault", ["raw", "missing", "snapshot", "wrong_case", "input", "normalizer"]
)
def test_reference_rejects_changed_evidence(cohort, monkeypatch, fault, tmp_path):
    root, frozen, _ = cohort
    record = reference.reference_cohort(root, frozen)
    raw = root / "parity/multi-1/pair-1-reference.json"
    if fault == "raw":
        raw.write_text('{"score":2}')
    elif fault == "missing":
        raw.unlink()
    elif fault == "snapshot":
        (root / "source-snapshot" / reference.NORMALIZER).write_text("changed")
    elif fault == "wrong_case":
        path = root / "parity/multi-1/report.json"
        report = json.loads(path.read_text())
        report["workers"] = 3
        tool._write(path, report)
    elif fault == "input":
        frozen.write_text('{"different":true}')
    else:
        altered = tmp_path / "normalizer.py"
        altered.write_text("changed")
        monkeypatch.setattr(reference, "NORMALIZER", altered)
    with pytest.raises((ValueError, FileNotFoundError)):
        reference.reference_cohort(root, frozen)
    if fault != "input":
        with pytest.raises((ValueError, FileNotFoundError)):
            reference.verify_reference(record)


def test_v2_manifest_separates_source_cohorts_and_checks_candidate(cohort, tmp_path, monkeypatch):
    root, frozen, meta = cohort
    output = tmp_path / "candidate"
    manifest = tool.bind(output, frozen, root)
    assert manifest["policy"] == tool.ORACLE_POLICY
    assert manifest["reference_cohort"]["reference_source_hashes"]
    report = tool.compare(None, meta, output / "parity/multi-1", 1, timing=False)
    assert len(report["observations"]) == 1
    assert report["policy"] == tool.ORACLE_POLICY
    tool.validate_report(report, output / "parity/multi-1", timing=False)
    monkeypatch.setattr(tool, "source_hashes", lambda: {"different": "source"})
    with pytest.raises(ValueError, match="Source changed"):
        tool.evidence_binding(output)


def test_v2_wrong_request_and_worker_fail_closed(cohort, tmp_path):
    root, frozen, meta = cohort
    output = tmp_path / "candidate"
    tool.bind(output, frozen, root)
    with pytest.raises(ValueError, match="identity"):
        tool.oracle_context(output, {**meta, "inputs_sha256": "different"}, 1)
    with pytest.raises(KeyError):
        tool.oracle_context(output, meta, 3)


def test_timing_still_executes_both_modes_against_golden(cohort, tmp_path, monkeypatch):
    root, frozen, meta = cohort
    output = tmp_path / "candidate"
    tool.bind(output, frozen, root)
    calls = []
    monkeypatch.setattr(
        tool, "run", lambda case, metadata, enabled, svc: calls.append(enabled) or {"score": 1}
    )
    report = tool.compare(None, meta, output / "timing/multi-1", 1, timing=True)
    assert calls == [False, True, False, True, True, False, False, True]
    tool.validate_report(report, output / "timing/multi-1", timing=True)
    assert report["reference_cohort_sha256"]


def test_historical_v1_selection_uses_archived_sources_without_mutation(cohort, monkeypatch):
    root, _, _ = cohort
    monkeypatch.setattr(tool, "TIMING", ())
    monkeypatch.setattr(tool, "MEMORY", ())
    monkeypatch.setattr(tool, "expected_inputs", lambda *args: "scenario")
    monkeypatch.setattr(tool, "source_hashes", lambda: {"new": "revision"})
    tool._write(root / "memory.json", [])
    result = tool.select(root, historical=True)
    assert result["policy"] == tool.POLICY
    assert not result["adopt"]  # No qualified timing gain in this intentionally partial fixture.
    assert not (root / "selection.json").exists()


def test_v2_selection_requires_new_timing_and_memory_bound_to_reference(
    cohort, tmp_path, monkeypatch
):
    root, frozen, meta = cohort
    output = tmp_path / "candidate"
    tool.bind(output, frozen, root)
    monkeypatch.setattr(tool, "TIMING", (("multi", 1),))
    monkeypatch.setattr(tool, "MEMORY", (("multi", 1),))
    monkeypatch.setattr(tool, "expected_inputs", lambda *args: "scenario")
    tool.compare(None, meta, output / "parity/multi-1", 1, timing=False)
    clocks = iter([0, 100, 100, 190, 200, 300, 300, 390, 400, 490, 490, 590, 600, 700, 700, 790])
    monkeypatch.setattr(tool, "perf_counter", lambda: next(clocks))
    timing = tool.compare(None, meta, output / "timing/multi-1", 1, timing=True)
    rows = []
    for index in range(3):
        for mode in tool.MODES:
            directory = output / "memory/multi-1" / f"{mode}-{index + 1}"
            directory.mkdir(parents=True)
            row = {
                "policy": tool.ORACLE_POLICY,
                "manifest_sha256": tool.evidence_binding(output),
                "reference_cohort_sha256": timing["reference_cohort_sha256"],
                "measurement_id": f"{mode}-{index}",
                "case_name": "multi",
                "workers": 1,
                "mode": mode,
                "complete": True,
                "failures": 0,
                "samples": 5,
                "pid": 100 + index,
                "includes_descendants": True,
                "sampled_peak_rss_bytes": 100,
                "result_digest": tool.result_digest({"score": 1}),
                "provenance": meta,
            }
            tool._write(directory / "report.json", row)
            tool._write(directory / "result.json", {"score": 1})
            rows.append(row)
    tool._write(output / "memory.json", rows)
    assert tool.select(output)["adopt"]
    timing["policy"] = tool.POLICY
    tool._write(output / "timing/multi-1/report.json", timing)
    with pytest.raises(ValueError, match="reference cohort"):
        tool.select(output)


def test_historical_rejects_exact_input_byte_change(cohort, monkeypatch):
    root, frozen, _ = cohort
    frozen.write_text("{ }")
    with pytest.raises(ValueError, match="Historical frozen input"):
        tool.select(root, historical=True)


def test_historical_flag_cannot_execute_memory_child(tmp_path, monkeypatch):
    import sys

    called = []
    monkeypatch.setattr(tool, "memory_child", lambda *args: called.append(True))
    monkeypatch.setattr(
        sys,
        "argv",
        ["accept", "memory-child", "--frozen", "unused", "--output", str(tmp_path), "--historical"],
    )
    with pytest.raises(SystemExit):
        tool.main()
    assert not called


def test_v2_historical_revalidates_reference_bytes(cohort, tmp_path):
    root, frozen, _ = cohort
    output = tmp_path / "candidate"
    tool.bind(output, frozen, root)
    snapshot = output / "source-snapshot" / reference.NORMALIZER
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(reference.NORMALIZER.read_bytes())
    (root / "parity/multi-1/pair-1-reference.json").write_text('{"score":2}')
    with pytest.raises(ValueError, match="tampered"):
        tool.select(output, historical=True)
