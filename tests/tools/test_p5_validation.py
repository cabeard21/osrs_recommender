"""Independent guards against misleading qualification measurements."""

from contextlib import contextmanager

import pytest

from tools import p5_experiment as p5


def test_twofold_boundary_variability_is_inconclusive():
    report = p5.timing_gate([100] * 3, [49, 50, 51], native=True)
    assert report["ratio"] == 0.5
    assert report["target_inconclusive"]
    assert report["inconclusive"]
    assert not report["accepted"]
    assert p5.timing_gate([100] * 3, [50] * 3, native=True)["accepted"]


def test_control_uses_nonregression_not_twofold_target():
    assert p5.timing_gate([100] * 3, [104] * 3, native=True, control=True)["accepted"]
    assert not p5.timing_gate([100] * 3, [106] * 3, native=True, control=True)["accepted"]
    assert not p5.timing_gate([100] * 3, [104, 105, 106], native=True, control=True)["accepted"]


@pytest.mark.parametrize("field", ["python", "packages", "environment"])
def test_binding_rechecks_build_but_not_observational_environment(tmp_path, monkeypatch, field):
    frozen = tmp_path / "input.json"
    frozen.write_text("{}")
    monkeypatch.setattr(p5, "source_hashes", lambda: {})
    build = {"python": "3.12", "packages": {"Cython": "3.2"}, "environment": {"dirty": False}}
    monkeypatch.setattr(p5, "build_environment", lambda: build)
    evidence = tmp_path / "evidence"
    p5.bind(evidence, frozen, {})
    build[field] = "changed"
    if field == "environment":
        p5.verify_binding(evidence)
    else:
        with pytest.raises(ValueError, match="Build environment"):
            p5.verify_binding(evidence)


@pytest.mark.parametrize(
    "options",
    [
        ["--force-cost"],
        ["--native", "--reference-workers", "3", "--candidate-workers", "6"],
        ["--require-native"],
    ],
)
def test_cli_rejects_confounded_or_ignored_experiment_options(tmp_path, monkeypatch, options):
    monkeypatch.setattr(
        p5.sys,
        "argv",
        ["p5", "timing", "--frozen", "input.json", "--output", str(tmp_path), *options],
    )
    with pytest.raises(SystemExit) as result:
        p5.main()
    assert result.value.code == 2
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize(
    "options,specs",
    [
        ({}, {"reference": p5.RunSpec(3, False), "candidate": p5.RunSpec(6, True)}),
        (
            {"require_native": True},
            {"reference": p5.RunSpec(3, False), "candidate": p5.RunSpec(3, False)},
        ),
        (
            {"force_cost": True},
            {"reference": p5.RunSpec(1, False), "candidate": p5.RunSpec(1, True)},
        ),
    ],
)
def test_direct_comparison_rejects_invalid_experiment_options(tmp_path, options, specs):
    with pytest.raises(ValueError):
        p5.compare(None, {}, tmp_path, specs, pairs=1, **options)


def test_comparison_keeps_only_one_mode_pool_alive_and_warms_each_observation(
    tmp_path, monkeypatch
):
    active, opened, invocations = [], [], []
    clock = {"now": 0}

    @contextmanager
    def sessions(case, specs):
        assert not active
        assert len(specs) == 1
        mode = next(iter(specs))
        active.append(mode)
        opened.append(mode)
        clock["now"] += 1000  # Startup must stay outside request timing.
        try:
            yield {mode: mode}
        finally:
            active.clear()

    def execute(case, meta, spec, service, **kwargs):
        assert active == [service]
        invocations.append(service)
        clock["now"] += 100 if spec.workers == 3 else 80
        return {"score": 1}, {}

    monkeypatch.setattr(p5, "verify_binding", lambda _: "binding")
    monkeypatch.setattr(p5, "sessions", sessions)
    monkeypatch.setattr(p5, "execute", execute)
    monkeypatch.setattr(p5, "perf_counter", lambda: clock["now"])
    report = p5.compare(
        None,
        {},
        tmp_path,
        {"reference": p5.RunSpec(3, False), "candidate": p5.RunSpec(6, False)},
        pairs=3,
    )
    assert opened == ["reference", "candidate", "candidate", "reference", "reference", "candidate"]
    assert invocations == [mode for mode in opened for _ in range(2)]
    assert not active
    assert all(pair == {"reference": 100, "candidate": 80} for pair in report["pairs"])
    assert report["decision"]["accepted"]
    p5.validate_report(tmp_path)
