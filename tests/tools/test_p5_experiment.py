import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import p5_experiment as p5


def test_native_gate_is_twofold_not_merely_convincing():
    assert p5.timing_gate([100] * 3, [50] * 3, native=True)["accepted"]
    assert not p5.timing_gate([100] * 3, [51] * 3, native=True)["accepted"]
    assert p5.timing_gate([100] * 3, [90] * 3, native=False)["accepted"]
    assert not p5.timing_gate([100] * 3, [100] * 3, native=False)["accepted"]


def test_worker_memory_uses_absolute_ceiling_native_also_relative():
    assert p5.memory_gate([100] * 3, [150] * 3, native=False, ceiling=150)["accepted"]
    assert not p5.memory_gate([100] * 3, [150] * 3, native=True, ceiling=200)["accepted"]
    assert not p5.memory_gate([100] * 3, [99, 99, 201], native=False, ceiling=200)["accepted"]


@pytest.mark.parametrize("values", [[1, 2], [0, 1, 2], [True, 1, 2], [1, 2, float("nan")]])
def test_invalid_measurements_fail_closed(values):
    with pytest.raises(ValueError):
        p5.timing_gate(values, [1] * 3, native=True)


def test_run_spec_validation():
    for workers in (0, 7, True, 1.0):
        with pytest.raises(ValueError):
            p5.RunSpec(workers, False)
    with pytest.raises(ValueError):
        p5.RunSpec(1, 1)


def test_evidence_binding_detects_changes(tmp_path, monkeypatch):
    frozen = tmp_path / "frozen.json"
    frozen.write_text("{}")
    monkeypatch.setattr(p5, "source_hashes", lambda: {"source": "one"})
    monkeypatch.setattr(p5, "build_environment", lambda: {"python": "test"})
    settings = {"case": "multi"}
    root = tmp_path / "evidence"
    binding = p5.bind(root, frozen, settings)
    assert p5.verify_binding(root) == binding
    frozen.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="Input changed"):
        p5.verify_binding(root)


def test_compare_retains_order_and_checks_raw_outputs(comparison):
    report, tmp_path = comparison()
    assert report["decision"]["accepted"]
    assert [r["mode"] for r in report["observations"]] == [
        "reference",
        "reference",
        "candidate",
        "candidate",
        "candidate",
        "candidate",
        "reference",
        "reference",
        "reference",
        "reference",
        "candidate",
        "candidate",
    ]
    p5.validate_report(tmp_path)
    row = tmp_path / "pair-1-candidate.json"
    row.write_text(json.dumps({"score": 2}))
    with pytest.raises(ValueError, match="parity"):
        p5.validate_report(tmp_path)


def test_native_target_fallback_is_rejected():
    assert p5.native_target_executed({"native_requests": 1, "fallback_requests": 0})
    assert not p5.native_target_executed({"native_requests": 0, "fallback_requests": 0})
    assert not p5.native_target_executed({"native_requests": 1, "fallback_requests": 1})


def test_frozen_multi_derivation_is_not_simplified():
    from tools.benchmark_gear_desktop import load_benchmark_case

    case, meta = load_benchmark_case("single_ranged")
    derived, metadata = p5.derive_case(case, meta, "multi")
    assert [r.style for r in derived.request.roles] == ["ranged", "slash"]
    assert all(r.combat_options is not None for r in derived.request.roles)
    assert metadata["case_name"] == "multi"


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    """Produce genuine on-disk evidence with deterministic measured durations."""
    monkeypatch.setattr(p5, "verify_binding", lambda _: "binding")
    clock = {"now": 0}
    config = {"pairs": 3, "uncertain": False}
    calls = dict.fromkeys(p5.MODES, 0)

    @contextmanager
    def sessions(*args):
        clock["now"] += 1
        yield dict.fromkeys(p5.MODES)

    def execute(case, meta, spec, *args, **kwargs):
        mode = "candidate" if spec.native else "reference"
        index = calls[mode] // (2 if config["pairs"] == 3 else 1)
        calls[mode] += 1
        if config["uncertain"]:
            duration = ([99, 89, 99, 40, 40] if spec.native else [100, 150, 90, 100, 100])[index]
        else:
            duration = 40 if spec.native else 100
        clock["now"] += duration
        return (
            {"score": 1, "search": {"explored_nodes": 12}},
            {"native_requests": 1, "fallback_requests": 0},
        )

    monkeypatch.setattr(p5, "sessions", sessions)
    monkeypatch.setattr(p5, "execute", execute)
    monkeypatch.setattr(p5, "perf_counter", lambda: clock["now"])

    def create(*, pairs=3, extend=False, require_native=True, uncertain=False):
        config.update(pairs=pairs, uncertain=uncertain)
        specs = {"reference": p5.RunSpec(1, False), "candidate": p5.RunSpec(1, True)}
        report = p5.compare(
            None,
            {"case_name": "multi", "inputs_sha256": "frozen"},
            tmp_path,
            specs,
            pairs=pairs,
            extend=extend,
            require_native=require_native,
        )
        return report, tmp_path

    return create


def test_screen_cannot_be_accepted(comparison):
    report, path = comparison(pairs=1)
    assert report["decision"] == {"accepted": False, "screen_only": True}
    assert len(report["observations"]) == 2
    assert p5.validate_report(path) == report


def test_screen_decision_cannot_be_promoted_to_qualification(comparison):
    report, path = comparison(pairs=1)
    report["decision"]["accepted"] = True
    p5._write(path / "report.json", report)
    with pytest.raises(ValueError, match=r"[Ss]creen|[Dd]ecision"):
        p5.validate_report(path)


def test_extension_is_only_used_for_inconclusive_initial_pairs(comparison):
    report, path = comparison(extend=True, uncertain=True)
    assert len(report["pairs"]) == 5
    assert len(report["observations"]) == 20
    assert p5.validate_report(path) == report
    report["extension_predeclared"] = False
    p5._write(path / "report.json", report)
    with pytest.raises(ValueError, match="extension"):
        p5.validate_report(path)


def test_clear_outcome_does_not_extend(comparison):
    report, _ = comparison(extend=True)
    assert len(report["pairs"]) == 3


@pytest.mark.parametrize(
    "change, message",
    [
        ("policy", "binding"),
        ("binding", "binding"),
        ("pair_count", "pair count"),
        ("order", "order"),
        ("observations", "file mismatch"),
        ("timing", "Timing"),
        ("decision", "Decision"),
        ("native_fallback", "fallback"),
    ],
)
def test_report_tampering_is_rejected(comparison, change, message):
    report, path = comparison()
    if change == "policy":
        report["policy"] = "unrelated-policy"
    elif change == "binding":
        report["manifest_sha256"] = "different"
    elif change == "pair_count":
        report["pairs"].pop()
    elif change == "order":
        report["observations"].reverse()
    elif change == "observations":
        p5._write(path / "observations.json", [])
    elif change == "timing":
        report["pairs"][0]["candidate"] += 1
    elif change == "decision":
        report["decision"]["accepted"] = False
    elif change == "native_fallback":
        row = next(row for row in report["observations"] if row["mode"] == "candidate")
        row["native"]["fallback_requests"] = 1
        p5._write(path / "observations.json", report["observations"])
    p5._write(path / "report.json", report)
    with pytest.raises(ValueError, match=message):
        p5.validate_report(path)


@pytest.mark.parametrize("reason", ["parity", "fallback", "manifest"])
def test_compare_stops_before_reporting_invalid_experiment(comparison, monkeypatch, reason):
    if reason == "parity":
        values = iter([({"score": 1}, {}), ({"score": 2}, {})])
        monkeypatch.setattr(p5, "execute", lambda *args, **kwargs: next(values))
    elif reason == "fallback":
        monkeypatch.setattr(p5, "execute", lambda *args, **kwargs: ({"score": 1}, {}))
    else:
        bindings = iter(["binding", "binding", "changed"])
        monkeypatch.setattr(p5, "verify_binding", lambda _: next(bindings))
    with pytest.raises(ValueError):
        comparison(pairs=1, require_native=reason != "parity")


def test_compare_rejects_overwriting_observations(tmp_path):
    (tmp_path / "old.json").write_text("{}")
    specs = {"reference": p5.RunSpec(1, False), "candidate": p5.RunSpec(1, True)}
    with pytest.raises(ValueError, match="empty"):
        p5.compare(None, {}, tmp_path, specs, pairs=1)
    with pytest.raises(ValueError, match="one screen pair"):
        p5.compare(None, {}, tmp_path, {}, pairs=2)


@pytest.mark.parametrize("change", ["settings", "source", "policy"])
def test_manifest_mismatch_is_rejected(tmp_path, monkeypatch, change):
    frozen = tmp_path / "frozen.json"
    frozen.write_text("{}")
    monkeypatch.setattr(p5, "source_hashes", lambda: {"one": "source"})
    monkeypatch.setattr(p5, "build_environment", lambda: {})
    evidence = tmp_path / "evidence"
    binding = p5.bind(evidence, frozen, {"case": "multi"})
    assert p5.bind(evidence, frozen, {"case": "multi"}) == binding
    if change == "settings":
        with pytest.raises(ValueError, match="changed"):
            p5.bind(evidence, frozen, {"case": "single"})
    elif change == "source":
        monkeypatch.setattr(p5, "source_hashes", lambda: {"one": "changed"})
        with pytest.raises(ValueError, match="Source changed"):
            p5.verify_binding(evidence / "runs")
    else:
        manifest_path = evidence / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["policy"] = "unknown"
        p5._write(manifest_path, manifest)
        with pytest.raises(ValueError, match="policy"):
            p5.verify_binding(evidence)


def test_missing_manifest_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Missing"):
        p5.verify_binding(tmp_path / "evidence")


def test_source_hashes_include_native_sources_and_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = [
        "tracker/gear/search.py",
        "tracker/gear/native/core.pyx",
        "tracker/gear/native/core.pxd",
        "tracker/gear/native/core.pyd",
        "tracker/gear_desktop.py",
        "pyproject.toml",
        "tools/p5_experiment.py",
    ]
    for value in [*paths, "tracker/gear/native/ignored.txt"]:
        path = tmp_path / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    hashes = p5.source_hashes()
    assert set(hashes) == set(paths)
    binary = tmp_path / "tracker/gear/native/core.pyd"
    binary.write_bytes(b"replacement")
    assert (
        p5.source_hashes()[binary.relative_to(tmp_path).as_posix()]
        != hashes[binary.relative_to(tmp_path).as_posix()]
    )


def test_build_environment_records_optional_dependency_absence(monkeypatch):
    def version(package):
        if package == "Cython":
            raise p5.importlib.metadata.PackageNotFoundError(package)
        return "1.0"

    monkeypatch.setattr(p5.importlib.metadata, "version", version)
    monkeypatch.setattr(p5, "environment", lambda: {"platform": "test"})
    report = p5.build_environment()
    assert report["packages"]["Cython"] is None
    assert report["packages"]["setuptools"] == "1.0"


@pytest.mark.parametrize("succeeds", [True, False])
def test_available_memory_uses_windows_available_bytes(monkeypatch, succeeds):
    def read(pointer):
        pointer._obj.available = 8 * 1024**3
        return succeeds

    monkeypatch.setattr(p5.sys, "platform", "win32")
    monkeypatch.setattr(
        p5.ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=read)),
    )
    if succeeds:
        assert p5.available_memory() == 8 * 1024**3
    else:
        with pytest.raises(OSError, match="physical memory"):
            p5.available_memory()


def test_available_memory_rejects_other_platform(monkeypatch):
    monkeypatch.setattr(p5.sys, "platform", "linux")
    with pytest.raises(OSError, match="Windows"):
        p5.available_memory()


def test_sessions_share_equal_worker_pools_and_close_on_error(monkeypatch):
    from tracker.gear import parallel, service

    pools, services = [], []

    class Pool:
        def __init__(self, workers):
            self.workers, self.closed = workers, False
            pools.append(self)

        def start(self, content, catalog):
            assert (content, catalog) == ("content", "catalog")

        def close(self):
            self.closed = True

    def new_service(content, **kwargs):
        result = SimpleNamespace(options=kwargs)
        services.append(result)
        return result

    monkeypatch.setattr(parallel, "AutoProcessPool", Pool)
    monkeypatch.setattr(service, "GearService", new_service)
    case = SimpleNamespace(content="content", catalog="catalog")
    specs = {"reference": p5.RunSpec(4, False), "candidate": p5.RunSpec(4, True)}
    with pytest.raises(RuntimeError, match="test"), p5.sessions(case, specs) as active:
        assert len(pools) == 1
        assert active["reference"].options["auto_pool"] is pools[0]
        assert active["candidate"].options["native_search"] is True
        assert active["candidate"]._equipment == "catalog"
        raise RuntimeError("test")
    assert pools[0].closed
    with p5.sessions(case, {"reference": p5.RunSpec(1, False)}) as active:
        assert active["reference"].options["auto_pool"] is None
    assert len(pools) == 1


@pytest.mark.parametrize("native", [False, True])
def test_execute_service_preserves_mode_and_sidecar(native):
    seen = {}

    def optimize(snapshot, request, **kwargs):
        seen.update(kwargs)
        assert (snapshot, request) == ("snapshot", "request")
        return {"score": 1}

    case = SimpleNamespace(snapshot="snapshot", request="request", prices="prices", at="time")
    svc = SimpleNamespace(optimize=optimize, native_diagnostics={"native_requests": 1})
    result, evidence = p5.execute(
        case, {"optimization_mode": "thorough"}, p5.RunSpec(1, native), svc
    )
    assert result == {"score": 1}
    assert seen == {
        "price_records": "prices",
        "now": "time",
        "local_refinement": True,
        "cancelled": None,
    }
    assert evidence == ({"native_requests": 1} if native else {})


@pytest.mark.parametrize("native", [False, True])
def test_archive_execution_preserves_complete_and_forced_cost_flags(monkeypatch, native):
    from tracker.gear import optimizer

    seen = {}
    case = SimpleNamespace(
        snapshot="snapshot",
        request="request",
        prices="prices",
        at="time",
        catalog="catalog",
        content="content",
    )

    def optimize(*args, **kwargs):
        seen.update(kwargs)
        return {"archive": [1, 2, 3]}

    @contextmanager
    def capture():
        yield SimpleNamespace(snapshot=lambda: {"native_requests": 1, "fallback_requests": 0})

    monkeypatch.setattr(optimizer, "optimize", optimize)
    monkeypatch.setitem(p5.sys.modules, "tracker.gear.native", SimpleNamespace(capture=capture))
    result, evidence = p5.execute(
        case, {}, p5.RunSpec(1, native), None, archives=True, force_cost=True
    )
    assert result == {"archive": [1, 2, 3]}
    assert seen["_complete_frontiers"] is True
    assert seen["_running_frontier"] is True
    assert seen.get("_native_search", False) is native
    assert bool(evidence) is native


def test_memory_child_writes_raw_output_and_process_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(p5, "verify_binding", lambda _: "binding")
    monkeypatch.setattr(p5, "load_frozen_case", lambda _: (None, {}))
    monkeypatch.setattr(p5, "derive_case", lambda *args: (None, {"case_name": "multi"}))
    monkeypatch.setattr(p5, "sessions", lambda *args: p5.nullcontext({"candidate": None}))
    monkeypatch.setattr(p5, "execute", lambda *args, **kwargs: ({"score": 1}, {}))
    monkeypatch.setattr(
        p5,
        "measure_process_tree",
        lambda **kwargs: p5.nullcontext(
            SimpleNamespace(report=lambda: {"complete": True, "sampled_peak_rss_bytes": 123})
        ),
    )
    report = p5.memory_child(Path("frozen.json"), tmp_path, "multi", p5.RunSpec(4, False))
    assert report["pid"] > 0
    assert report["manifest_sha256"] == "binding"
    assert report["spec"]["workers"] == 4
    assert report["result_digest"] == p5.result_digest({"score": 1})
    assert json.loads((tmp_path / "result.json").read_text()) == {"score": 1}
    with pytest.raises(ValueError, match="already exists"):
        p5.memory_child(Path("frozen.json"), tmp_path, "multi", p5.RunSpec(4, False))


@pytest.mark.parametrize("phase", ["screen", "timing", "parity", "memory-child", "validate"])
def test_cli_routes_preserve_selected_execution(monkeypatch, tmp_path, phase):
    seen = {}
    output = tmp_path / "evidence"
    monkeypatch.setattr(
        p5.sys,
        "argv",
        [
            "p5",
            phase,
            "--frozen",
            "input.json",
            "--output",
            str(output),
            "--case",
            "multi",
            "--reference-workers",
            "6",
            "--candidate-workers",
            "6",
            "--native",
            "--require-native",
            "--extend",
            *(["--force-cost"] if phase == "parity" else []),
        ],
    )
    monkeypatch.setattr(p5, "available_memory", lambda: p5.MIN_AVAILABLE)
    monkeypatch.setattr(p5, "bind", lambda *args: seen.update(binding=args))
    monkeypatch.setattr(p5, "load_frozen_case", lambda _: (None, {}))
    monkeypatch.setattr(p5, "derive_case", lambda *args: (None, {"case_name": "multi"}))
    monkeypatch.setattr(p5, "validate_report", lambda path: {"decision": {"accepted": True}})
    monkeypatch.setattr(p5, "memory_child", lambda *args: seen.update(memory=args))

    def compare(*args, **kwargs):
        seen.update(compare=args, options=kwargs)
        return {"decision": {"accepted": False}}

    monkeypatch.setattr(p5, "compare", compare)
    p5.main()
    if phase == "memory-child":
        assert seen["memory"][-1] == p5.RunSpec(6, True)
        assert "binding" not in seen
    elif phase == "validate":
        assert not seen
    else:
        assert seen["options"]["pairs"] == (3 if phase == "timing" else 1)
        assert seen["options"]["archives"] is (phase == "parity")
        assert seen["options"]["require_native"] is True
        assert seen["compare"][-1]["candidate"] == p5.RunSpec(6, True)


@pytest.mark.parametrize("available", [p5.MIN_AVAILABLE - 1, p5.MIN_AVAILABLE])
def test_cli_preflight_reports_memory_readiness(monkeypatch, tmp_path, capsys, available):
    monkeypatch.setattr(
        p5.sys,
        "argv",
        [
            "p5",
            "preflight",
            "--frozen",
            "input.json",
            "--output",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(p5, "available_memory", lambda: available)
    if available < p5.MIN_AVAILABLE:
        with pytest.raises(SystemExit) as result:
            p5.main()
        assert result.value.code == 2
    else:
        p5.main()
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is (available >= p5.MIN_AVAILABLE)


@pytest.mark.parametrize(
    "counts",
    [
        {"native_requests": True, "fallback_requests": 0},
        {"native_requests": 1, "fallback_requests": False},
        {"native_requests": 1.0, "fallback_requests": 0},
        {"native_requests": 1, "fallback_requests": -1},
    ],
)
def test_native_request_counters_are_strict_nonnegative_integers(counts):
    assert not p5.native_target_executed(counts)


@pytest.mark.parametrize(
    "field",
    [
        "specs",
        "case_name",
        "require_native",
        "force_cost",
        "extension",
        "archives",
        "phase",
        "control",
    ],
)
def test_report_cannot_change_bound_configuration(comparison, field):
    report, path = comparison()
    settings = {
        "specs": json.loads(json.dumps(report["specs"])),
        "case": "multi",
        "require_native": True,
        "force_cost": False,
        "extend": False,
        "phase": "timing",
        "control": False,
    }
    p5._write(path / "manifest.json", {"settings": settings})
    if field == "specs":
        report["specs"]["candidate"]["workers"] = 6
    elif field == "case_name":
        report["provenance"]["case_name"] = "fixed_melee"
    elif field == "extension":
        report["extension_predeclared"] = True
    elif field == "phase":
        settings["phase"] = "screen"
        p5._write(path / "manifest.json", {"settings": settings})
    else:
        report[field] = not report[field]
    p5._write(path / "report.json", report)
    with pytest.raises(ValueError, match=r"bound (configuration|phase)"):
        p5.validate_report(path)


@pytest.fixture
def memory_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(p5, "verify_binding", lambda _: "binding")
    specs = {
        "reference": {"workers": 3, "native": False},
        "candidate": {"workers": 6, "native": False},
    }
    settings = {
        "specs": specs,
        "case": "multi_auto",
        "require_native": False,
        "memory_ceiling": 200,
    }
    p5._write(tmp_path / "manifest.json", {"settings": settings})
    for index in range(3):
        for mode in p5.MODES:
            directory = tmp_path / f"{mode}-{index + 1}"
            directory.mkdir()
            p5._write(directory / "result.json", {"score": 1})
            p5._write(directory / "warmup.json", {"score": 1})
            p5._write(
                directory / "report.json",
                {
                    "manifest_sha256": "binding",
                    "policy": p5.POLICY,
                    "spec": specs[mode],
                    "provenance": {"case_name": "multi_auto", "inputs_sha256": "input"},
                    "complete": True,
                    "failures": 0,
                    "samples": 20,
                    "includes_descendants": True,
                    "pid": 100 + 2 * index + (mode == "candidate"),
                    "measurement_id": f"{mode}-{index}",
                    "result_digest": p5.result_digest({"score": 1}),
                    "warmup_digest": p5.result_digest({"score": 1}),
                    "sampled_peak_rss_bytes": 100 if mode == "reference" else 150,
                    "native": {},
                },
            )
    return tmp_path


def test_memory_summary_uses_all_fresh_process_observations(memory_evidence):
    report = p5.summarize_memory(memory_evidence)
    assert report["samples"] == {"reference": [100] * 3, "candidate": [150] * 3}
    assert report["decision"]["accepted"]
    assert json.loads((memory_evidence / "summary.json").read_text()) == report


@pytest.mark.parametrize(
    "change", ["binding", "sample", "duplicate", "spec", "parity", "input", "native", "warmup"]
)
def test_memory_summary_rejects_incomplete_or_mismatched_evidence(memory_evidence, change):
    path = memory_evidence / "candidate-3" / "report.json"
    report = json.loads(path.read_text())
    if change == "binding":
        report["manifest_sha256"] = "changed"
    elif change == "sample":
        report["failures"] = 1
    elif change == "duplicate":
        report["measurement_id"] = "reference-0"
    elif change == "spec":
        report["spec"]["workers"] = 4
    elif change == "parity":
        p5._write(path.parent / "result.json", {"score": 2})
    elif change == "input":
        report["provenance"]["inputs_sha256"] = "changed"
    elif change == "warmup":
        p5._write(path.parent / "warmup.json", {"score": 2})
    else:
        manifest_path = memory_evidence / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["settings"]["require_native"] = True
        manifest["settings"]["specs"]["candidate"]["native"] = True
        p5._write(manifest_path, manifest)
        for index in range(1, 4):
            candidate_path = memory_evidence / f"candidate-{index}" / "report.json"
            row = json.loads(candidate_path.read_text())
            row["spec"]["native"] = True
            p5._write(candidate_path, row)
        report["spec"]["native"] = True
    p5._write(path, report)
    with pytest.raises(ValueError):
        p5.summarize_memory(memory_evidence)


def test_memory_ceiling_triggers_optimizer_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(p5, "verify_binding", lambda _: "binding")
    monkeypatch.setattr(p5, "load_frozen_case", lambda _: (None, {}))
    monkeypatch.setattr(p5, "derive_case", lambda *args: (None, {}))
    monkeypatch.setattr(p5, "sessions", lambda *args: p5.nullcontext({"candidate": None}))
    monkeypatch.setattr(p5, "windows_tree_rss", lambda pid: p5.MEMORY_CEILING + 1)

    @contextmanager
    def measure(*, sampler):
        assert sampler(123) > p5.MEMORY_CEILING
        yield None

    def execute(*args, cancelled):
        assert cancelled()
        raise ValueError("optimization_cancelled")

    monkeypatch.setattr(p5, "measure_process_tree", measure)
    monkeypatch.setattr(p5, "execute", execute)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        p5.memory_child(Path("frozen.json"), tmp_path, "multi", p5.RunSpec(6, False))
    assert not (tmp_path / "report.json").exists()


def test_cli_memory_launches_six_separate_children(monkeypatch, tmp_path):
    monkeypatch.setattr(
        p5.sys,
        "argv",
        [
            "p5",
            "memory",
            "--frozen",
            "input.json",
            "--output",
            str(tmp_path),
            "--reference-workers",
            "6",
            "--candidate-workers",
            "6",
            "--native",
        ],
    )
    monkeypatch.setattr(p5, "available_memory", lambda: p5.MIN_AVAILABLE)
    monkeypatch.setattr(p5, "bind", lambda *args: None)
    monkeypatch.setattr(p5, "summarize_memory", lambda *args: {"decision": {"accepted": True}})
    calls = []
    monkeypatch.setattr(
        p5.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    p5.main()
    assert len(calls) == 6
    assert all(kwargs == {"check": True} for _, kwargs in calls)
    assert len({command[command.index("--output") + 1] for command, _ in calls}) == 6
    assert ["--native" in command for command, _ in calls] == [False, True] * 3


def test_cli_blocks_measurement_before_binding_when_memory_is_low(monkeypatch, tmp_path):
    monkeypatch.setattr(
        p5.sys,
        "argv",
        [
            "p5",
            "screen",
            "--frozen",
            "input.json",
            "--output",
            str(tmp_path),
            "--reference-workers",
            "3",
            "--candidate-workers",
            "6",
        ],
    )
    monkeypatch.setattr(p5, "available_memory", lambda: p5.MIN_AVAILABLE - 1)
    with pytest.raises(ValueError, match="blocked"):
        p5.main()
    assert not (tmp_path / "manifest.json").exists()


def test_serial_native_probe_does_not_apply_worker_scaling_preflight(monkeypatch, tmp_path):
    monkeypatch.setattr(
        p5.sys,
        "argv",
        ["p5", "screen", "--frozen", "input.json", "--output", str(tmp_path), "--native"],
    )
    monkeypatch.setattr(p5, "available_memory", lambda: 5 * 1024**3)

    def bind(*args):
        raise RuntimeError("serial binding reached")

    monkeypatch.setattr(p5, "bind", bind)
    with pytest.raises(RuntimeError, match="serial binding reached"):
        p5.main()
