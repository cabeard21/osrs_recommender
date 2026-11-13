import pytest

from tools.accept_compact_states import memory_decision, timing_decision


def test_five_percent_is_separate_from_mad():
    outcome = timing_decision([90, 100, 110], [106, 106, 106])
    assert not outcome["no_material_regression"]
    assert not outcome["convincing_gain"]


def test_exact_boundary_and_convincing_gain():
    assert timing_decision([100] * 3, [105] * 3)["no_material_regression"]
    assert not timing_decision([100] * 3, [105] * 3)["inconclusive"]
    assert timing_decision([100] * 3, [90] * 3)["convincing_gain"]
    assert not timing_decision([100] * 3, [100] * 3)["convincing_gain"]


@pytest.mark.parametrize("values", [[1, 2], [1, 2, float("nan")], [1, 2, True], [0, 1, 2]])
def test_invalid_samples(values):
    with pytest.raises(ValueError):
        timing_decision(values, [1, 2, 3])


def test_memory_requires_three_and_respects_ceiling():
    assert memory_decision([100] * 3, [105] * 3)["accepted"]
    assert not memory_decision([100] * 3, [105] * 3, ceiling=104)["accepted"]
    assert not memory_decision([100] * 3, [106] * 3)["accepted"]


def test_compare_keeps_warmups_and_three_alternating_pairs(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    report = tool.compare(None, {}, tmp_path, 1, timing=True)
    assert len(report["observations"]) == 8
    assert [r["mode"] for r in report["observations"][2:]] == [
        "reference",
        "candidate",
        "candidate",
        "reference",
        "reference",
        "candidate",
    ]
    tool.validate_report(report, tmp_path, timing=True)
    report["pairs"][0]["reference"] += 1
    with pytest.raises(ValueError):
        tool.validate_report(report, tmp_path, timing=True)


def test_report_rejects_modified_raw_result(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    report = tool.compare(None, {}, tmp_path, 1, timing=False)
    (tmp_path / "pair-1-reference.json").write_text('{"score": 2}')
    with pytest.raises(ValueError):
        tool.validate_report(report, tmp_path, timing=False)


def test_selection_validates_all_evidence(tmp_path, monkeypatch):
    import json

    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool, "PARITY", (("multi", 1),))
    monkeypatch.setattr(tool, "TIMING", (("multi", 1),))
    monkeypatch.setattr(tool, "MEMORY", (("multi", 1),))
    monkeypatch.setattr(tool, "source_hashes", lambda: {})
    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    tool._write(tmp_path / "manifest.json", {"policy": tool.POLICY, "source_hashes": {}})
    meta = {"inputs_sha256": "inputs", "case_name": "multi"}
    monkeypatch.setattr(tool, "expected_inputs", lambda *args: "inputs")
    tool.compare(None, meta, tmp_path / "parity/multi-1", 1, timing=False)
    clocks = iter([0, 100, 100, 190, 200, 300, 300, 390, 400, 490, 490, 590, 600, 700, 700, 790])
    monkeypatch.setattr(tool, "perf_counter", lambda: next(clocks))
    tool.compare(None, meta, tmp_path / "timing/multi-1", 1, timing=True)
    rows = []
    for index in range(3):
        for mode in tool.MODES:
            directory = tmp_path / "memory/multi-1" / f"{mode}-{index + 1}"
            directory.mkdir(parents=True)
            row = {
                "measurement_id": f"{mode}-{index}",
                "case_name": "multi",
                "workers": 1,
                "mode": mode,
                "complete": True,
                "failures": 0,
                "samples": 5,
                "sampled_peak_rss_bytes": 100,
                "result_digest": tool.result_digest({"score": 1}),
                "provenance": meta,
                "manifest_sha256": tool.evidence_binding(tmp_path),
                "pid": 100 + index,
                "includes_descendants": True,
            }
            tool._write(directory / "report.json", row)
            tool._write(directory / "result.json", {"score": 1})
            rows.append(row)
    tool._write(tmp_path / "memory.json", rows)
    assert tool.select(tmp_path)["adopt"]
    report_path = tmp_path / "timing/multi-1/report.json"
    report = json.loads(report_path.read_text())
    report["observations"].reverse()
    tool._write(report_path, report)
    with pytest.raises(ValueError):
        tool.select(tmp_path)


def test_bind_rejects_drift(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    frozen = tmp_path / "input.json"
    frozen.write_text("{}")
    monkeypatch.setattr(tool, "source_hashes", lambda: {"file": "one"})
    tool.bind(tmp_path / "out", frozen)
    tool.bind(tmp_path / "out", frozen)
    frozen.write_text('{"changed":true}')
    with pytest.raises(ValueError):
        tool.bind(tmp_path / "out", frozen)


def test_derived_multi_auto_variants():
    from tools import accept_compact_states as tool
    from tools.benchmark_gear_desktop import load_benchmark_case

    case, metadata = load_benchmark_case("single_ranged")
    for name in ("multi_auto", "multi_auto_mixed", "multi_auto_fixed"):
        derived, meta = tool.derive_case(case, metadata, name)
        assert len(derived.request.roles) == 2
        assert derived.request.roles[0].allowed_disciplines == ("melee", "ranged", "magic")
        assert bool(derived.request.roles[1].allowed_disciplines) == (
            name not in ("multi_auto_mixed", "multi_auto_fixed")
        )
        assert meta["case_name"] == name


@pytest.mark.parametrize(
    "phase", ["parity", "timing", "profile", "memory", "select", "memory-child"]
)
def test_cli_phases(tmp_path, monkeypatch, phase):
    import sys

    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool, "bind", lambda *args: {})
    monkeypatch.setattr(tool, "load_frozen_case", lambda *args: (None, {}))
    monkeypatch.setattr(tool, "derive_case", lambda *args: (None, {}))
    monkeypatch.setattr(tool, "PARITY", (("multi", 1),))
    monkeypatch.setattr(tool, "TIMING", (("multi", 1),))
    monkeypatch.setattr(tool, "MEMORY", (("multi", 1),))
    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    monkeypatch.setattr(tool, "select", lambda *args, **kwargs: {"adopt": True})
    monkeypatch.setattr(tool, "memory_child", lambda *args: None)

    def fake_subprocess(command, **kwargs):
        directory = tool.Path(command[command.index("--output") + 1])
        directory.mkdir(parents=True)
        tool._write(directory / "report.json", {})

    monkeypatch.setattr(tool.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(tool, "environment", lambda: {})
    monkeypatch.setattr(
        sys,
        "argv",
        ["accept", phase, "--frozen", "unused", "--output", str(tmp_path), "--only", "multi"],
    )
    tool.main()


def test_service_and_run_paths(monkeypatch):
    from types import SimpleNamespace

    from tools import accept_compact_states as tool
    from tracker.gear import optimizer
    from tracker.gear import service as services

    calls = []

    class FakeService:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

        def optimize(self, *args, **kwargs):
            return {"score": 1}

    monkeypatch.setattr(services, "GearService", FakeService)
    monkeypatch.setattr(optimizer, "optimize", lambda *args, **kwargs: {"diagnostic": kwargs})
    case = SimpleNamespace(
        content=None, catalog=None, snapshot=None, request=None, prices=None, at=None
    )
    svc = tool.service(case, True, None)
    assert calls[0]["factored_evaluation"] and calls[0]["compact_states"]
    assert tool.run(case, {}, True, svc) == {"score": 1}
    assert tool.run(case, {"diagnostic": True}, True, svc)["diagnostic"]["_compact_states"]


def test_memory_child_records_fresh_process(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool, "load_frozen_case", lambda *args: (None, {}))
    monkeypatch.setattr(tool, "derive_case", lambda *args: (None, {}))
    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})

    @contextmanager
    def memory():
        from types import SimpleNamespace

        yield SimpleNamespace(report=lambda: {"complete": True, "samples": 2})

    monkeypatch.setattr(tool, "measure_process_tree", memory)
    tool.memory_child(tmp_path / "frozen", tmp_path, "multi", 1, "candidate")
    assert (tmp_path / "result.json").exists()
    assert "measurement_id" in (tmp_path / "report.json").read_text()


def test_extension_retains_all_initial_pairs_and_requires_predeclaration(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    elapsed = [100, 100, 90, 99, 99, 100, 110, 99, 99, 100, 100, 99]
    clocks = []
    start = 0
    for duration in elapsed:
        clocks.extend([start, start + duration])
        start += duration + 1
    clock = iter(clocks)
    monkeypatch.setattr(tool, "perf_counter", lambda: next(clock))
    report = tool.compare(None, {"case_name": "multi"}, tmp_path, 1, timing=True, extend=True)
    assert len(report["pairs"]) == 5
    assert len(report["observations"]) == 12
    tool.validate_report(report, tmp_path, timing=True)
    report["extension_predeclared"] = False
    with pytest.raises(ValueError):
        tool.validate_report(report, tmp_path, timing=True)


def test_existing_evidence_cannot_be_overwritten(tmp_path):
    from tools import accept_compact_states as tool

    (tmp_path / "observation.json").write_text("{}")
    with pytest.raises(ValueError, match="already contains"):
        tool.compare(None, {}, tmp_path, 1, timing=True)


def test_cli_unknown_case_rejected(tmp_path, monkeypatch):
    import sys

    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool, "bind", lambda *args: {})
    monkeypatch.setattr(tool, "load_frozen_case", lambda *args: (None, {}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["accept", "timing", "--frozen", "unused", "--output", str(tmp_path), "--only", "unknown"],
    )
    with pytest.raises(SystemExit):
        tool.main()


def test_small_control_gain_does_not_require_convincing_improvement():
    result = timing_decision([98, 100, 102], [99.5, 99.5, 99.5])
    assert result["gain_inconclusive"]
    assert not result["tolerance_inconclusive"]
    assert result["no_material_regression"]


def test_v2_candidate_parity_runs_only_candidate_against_golden(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    seen = []
    monkeypatch.setattr(tool, "service", lambda case, enabled, pool: seen.append(enabled))
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 1})
    monkeypatch.setattr(
        tool,
        "oracle_context",
        lambda *args: (tool.ORACLE_POLICY, tool.result_digest({"score": 1}), "cohort"),
    )
    report = tool.compare(None, {}, tmp_path, 1, timing=False)
    assert seen == [True]
    assert report["reference_cohort_sha256"] == "cohort"
    assert [(r["label"], r["mode"]) for r in report["observations"]] == [("pair-1", "candidate")]
    tool.validate_report(report, tmp_path, timing=False)


def test_v2_rejects_candidate_that_differs_from_reference(tmp_path, monkeypatch):
    from tools import accept_compact_states as tool

    monkeypatch.setattr(tool.p1, "_pool", lambda *args: None)
    monkeypatch.setattr(tool, "service", lambda *args: None)
    monkeypatch.setattr(tool, "run", lambda *args: {"score": 2})
    monkeypatch.setattr(
        tool,
        "oracle_context",
        lambda *args: (tool.ORACLE_POLICY, tool.result_digest({"score": 1}), "cohort"),
    )
    with pytest.raises(ValueError, match="parity failed"):
        tool.compare(None, {}, tmp_path, 1, timing=False)
