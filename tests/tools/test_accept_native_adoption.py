"""Correctness-only native adoption evidence is complete and independently checked."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tools import accept_native_adoption as adoption


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    calls = []
    live = []
    behavior = {"different": False, "fallback": False, "native": True}
    monkeypatch.setattr(adoption, "verify_binding", lambda _: "binding")

    @contextmanager
    def session(case, spec):
        assert not live, "process pools must never coexist"
        live.append(spec)
        calls.append(("start", spec.workers, spec.native))
        try:
            yield None
        finally:
            calls.append(("close", spec.workers, spec.native))
            live.clear()

    def execute(case, meta, spec, service, **kwargs):
        calls.append(("execute", spec.workers, spec.native, kwargs))
        result = {
            "selected": {"score": 2 if spec.native and behavior["different"] else 1},
            "archives": [{"id": "complete", "score": 1}],
            "timings_seconds": {"total": 10 if spec.native else 20},
        }
        evidence = {
            "native_requests": int(behavior["native"]),
            "fallback_requests": int(behavior["fallback"]),
        }
        return result, evidence if spec.native else {}

    monkeypatch.setattr(adoption, "session", session)
    monkeypatch.setattr(adoption, "execute", execute)

    def run(phase="archives", workers=1):
        return adoption.compare(
            SimpleNamespace(),
            {"case_name": "multi"},
            tmp_path,
            phase=phase,
            workers=workers,
        )

    return run, tmp_path, calls, behavior


def test_archives_are_one_complete_request_per_engine_without_warmup(comparison):
    run, directory, calls, _ = comparison
    report = run()
    assert report["accepted"] is True
    executions = [row for row in calls if row[0] == "execute"]
    assert len(executions) == 2
    assert all(row[3] == {"archives": True, "force_cost": True} for row in executions)
    assert adoption.validate_report(directory) == report
    assert "timings_seconds" in json.loads((directory / "candidate.json").read_text())
    assert not {"speedup", "memory", "threshold", "pairs"} & report.keys()


def test_service_also_proves_native_serial_six_worker_parity(comparison):
    run, _, calls, _ = comparison
    report = run("service", 6)
    assert [(row["label"], row["workers"]) for row in report["observations"]] == [
        ("reference", 6),
        ("candidate", 6),
        ("candidate_serial", 1),
    ]
    executions = [row for row in calls if row[0] == "execute"]
    assert len(executions) == 3
    assert all(row[3] == {"archives": False, "force_cost": False} for row in executions)


@pytest.mark.parametrize("field", ["different", "fallback", "native"])
def test_failed_parity_or_native_coverage_is_rejected_and_retained(comparison, field):
    run, directory, _, behavior = comparison
    behavior[field] = field != "native"
    with pytest.raises(ValueError, match=r"parity|native execution"):
        run()
    assert (directory / "candidate.json").exists()
    assert json.loads((directory / "report.json").read_text())["accepted"] is False


def test_raw_output_tampering_is_rejected(comparison):
    run, directory, _, _ = comparison
    run()
    (directory / "candidate.json").write_text('{"different":true}')
    with pytest.raises(ValueError, match="Raw output"):
        adoption.validate_report(directory)


def test_truncated_report_is_rejected(comparison):
    run, directory, _, _ = comparison
    report = run("service", 6)
    report["observations"].pop()
    (directory / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="observations"):
        adoption.validate_report(directory)


def test_completed_outputs_are_never_overwritten(comparison):
    run, _, _, _ = comparison
    run()
    with pytest.raises(ValueError, match="already contains"):
        run()


def test_cohort_maps_three_workers_to_six_and_deduplicates_archives():
    assert all(workers in (1, 6) for _, workers in adoption.SERVICE_CASES)
    assert ("multi_auto", 6) in adoption.SERVICE_CASES
    assert len(adoption.ARCHIVE_CASES) == len(set(adoption.ARCHIVE_CASES))
    assert ("fixed_magic", 1) in adoption.ARCHIVE_CASES


def test_binding_detects_source_input_and_binary_changes(tmp_path, monkeypatch):
    state = {"source": "first", "build": "first"}
    frozen = tmp_path / "input.json"
    frozen.write_text("{}")
    monkeypatch.setattr(adoption, "source_hashes", lambda: {"source": state["source"]})
    monkeypatch.setattr(adoption, "build_environment", lambda: {"build": state["build"]})
    directory = tmp_path / "evidence"
    adoption.bind(directory, frozen)
    first = adoption.verify_binding(directory)
    assert adoption.verify_binding(directory / "archives" / "multi-1") == first
    for key in ("source", "build"):
        state[key] = "changed"
        with pytest.raises(ValueError, match="changed"):
            adoption.verify_binding(directory)
        state[key] = "first"
    frozen.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="changed"):
        adoption.verify_binding(directory)


@pytest.mark.parametrize(
    "phase,workers", [("timing", 1), ("memory", 1), ("archives", 6), ("service", 3)]
)
def test_invalid_phase_or_worker_mode_is_rejected(comparison, phase, workers):
    run, _, _, _ = comparison
    with pytest.raises(ValueError, match=r"phase|workers"):
        run(phase, workers)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(adoption, "bind", lambda *args: calls.append(("bind", *args)))
    monkeypatch.setattr(adoption, "load_frozen_case", lambda _: ("base", {"frozen": True}))
    monkeypatch.setattr(
        adoption, "derive_case", lambda base, meta, name: (name, {"case_name": name})
    )

    def compare(case, meta, output, **kwargs):
        calls.append(("compare", case, output, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(adoption, "compare", compare)
    return tmp_path, calls


def test_cli_runs_selected_archive_once(cli, capsys):
    directory, calls = cli
    adoption.main(["--case", "fixed_magic", "--output", str(directory)])
    assert len(calls) == 2
    assert calls[1][1:] == (
        "fixed_magic",
        directory / "archives" / "fixed_magic-1",
        {"phase": "archives", "workers": 1},
    )
    assert json.loads(capsys.readouterr().out)["accepted"] is True


def test_cli_all_filters_parallel_service_cases(cli):
    directory, calls = cli
    adoption.main(["--all", "--phase", "service", "--workers", "6", "--output", str(directory)])
    requested = [row for row in calls if row[0] == "compare"]
    assert len(requested) == sum(n == 6 for _, n in adoption.SERVICE_CASES)
    assert all(row[3] == {"phase": "service", "workers": 6} for row in requested)


@pytest.mark.parametrize("direct", [False, True])
def test_cli_validates_retained_reports(tmp_path, monkeypatch, direct):
    directory = tmp_path if direct else tmp_path / "archives" / "multi-1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text("{}")
    calls = []
    monkeypatch.setattr(adoption, "validate_report", lambda path: calls.append(path))
    adoption.main(["--validate", "--output", str(tmp_path)])
    assert calls == [directory]


@pytest.mark.parametrize("args", [[], ["--all", "--workers", "6"], ["--validate"]])
def test_cli_rejects_missing_selection_or_reports(tmp_path, args):
    with pytest.raises(SystemExit) as exc:
        adoption.main([*args, "--output", str(tmp_path)])
    assert exc.value.code == 2


@pytest.mark.parametrize("native,workers", [(False, 1), (False, 6), (True, 1), (True, 6)])
def test_session_owns_readiness_pool_and_service(monkeypatch, native, workers):
    import sys

    from tracker.gear import parallel, service

    calls = []
    ready = SimpleNamespace(require_native=lambda: calls.append("native"))
    monkeypatch.setitem(sys.modules, "tracker.gear.native.readiness", ready)

    class Pool:
        def __init__(self, n):
            calls.append(("pool", n))

        def start(self, content, catalog, **kwargs):
            calls.append(("start", kwargs))

        def close(self):
            calls.append("close")

    def create(content, **kwargs):
        calls.append(("service", kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(parallel, "AutoProcessPool", Pool)
    monkeypatch.setattr(service, "GearService", create)
    case = SimpleNamespace(content="content", catalog="catalog")
    with adoption.session(case, adoption.RunSpec(workers, native)) as gear:
        assert gear._equipment == "catalog"
        if native:
            assert calls[0] == "native"
    assert ("native" in calls) is native
    assert ("close" in calls) is (workers == 6)
    if workers == 6:
        assert ("start", {"native_required": native}) in calls
    flags = next(row[1] for row in calls if isinstance(row, tuple) and row[0] == "service")
    assert flags["native_search"] is native
    assert flags["compact_states"] is True


def test_cli_effects_selects_declared_cases(cli, monkeypatch):
    directory, calls = cli
    monkeypatch.setattr(
        adoption, "derive_effect_case", lambda base, meta, name: (name, {"effect_case": name})
    )
    adoption.main(["--effects", "--output", str(directory)])
    requested = [row for row in calls if row[0] == "compare"]
    assert [row[1] for row in requested] == list(adoption.EFFECT_CASES)
    assert all(row[3] == {"phase": "archives", "workers": 1} for row in requested)


@pytest.mark.parametrize(
    "missing", ["magic", "ranged", "dps", "secondary", "cost", "metric", "attempts"]
)
def test_effect_evidence_requires_each_discipline_and_lane(missing):
    metadata = {"effect_case": "effect_auto", "required_effect_styles": ["magic", "ranged"]}
    events = [
        {
            "event": "stage",
            "roles": [style],
            "frontier": lane != "dps",
            "cost": lane == "cost",
            "metric": metric,
            "attempts": 1,
        }
        for style in ("magic", "ranged")
        for lane, metric in (
            ("dps", False),
            ("secondary", False),
            ("secondary", True),
            ("cost", False),
            ("cost", True),
        )
    ]
    diagnostics = {"native_requests": 2, "fallback_requests": 0, "events": events}
    assert adoption.required_native_executed(diagnostics, metadata)
    if missing in {"magic", "ranged"}:
        events[:] = [row for row in events if row["roles"] != [missing]]
    elif missing == "attempts":
        events[0]["attempts"] = 0
    elif missing == "metric":
        events[:] = [row for row in events if not row["metric"]]
    elif missing == "cost":
        events[:] = [row for row in events if not row["cost"]]
    elif missing == "secondary":
        events[:] = [row for row in events if not row["frontier"] or row["cost"]]
    else:
        events[:] = [row for row in events if row["frontier"]]
    assert not adoption.required_native_executed(diagnostics, metadata)
