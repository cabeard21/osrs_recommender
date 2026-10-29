from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container.yml"
MAKEFILE = ROOT / "Makefile"


def _workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run_commands(job: dict[str, object]) -> tuple[str, ...]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return tuple(str(step["run"]) for step in steps if isinstance(step, dict) and "run" in step)


def test_makefile_exposes_fast_and_complete_lanes() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "test:" in makefile
    assert '-m "not browser and not llm_live"' in makefile
    assert "test-full:" in makefile
    assert '-m "not llm_live"' in makefile
    assert "test-ci: test-smoke" in makefile
    assert "test-smoke:" in makefile
    assert "test-cov:" in makefile
    assert "--cov=tracker.quest_cape" in makefile
    assert "--cov-fail-under=80" in makefile


def test_ci_runs_smoke_tests_with_optional_full_coverage() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    validate = jobs["validate"]
    checks = jobs["checks"]
    tests = jobs["tests"]
    coverage = jobs["coverage"]
    frontend = jobs["frontend"]
    smoke = jobs["container-smoke"]
    publish = jobs["publish"]
    assert isinstance(validate, dict)
    assert isinstance(checks, dict)
    assert isinstance(tests, dict)
    assert isinstance(coverage, dict)
    assert isinstance(frontend, dict)
    assert isinstance(smoke, dict)
    assert isinstance(publish, dict)

    assert "if" not in tests
    assert "make test-smoke PY=python" in _run_commands(tests)
    assert not any("playwright" in c or "test-cov" in c for c in _run_commands(tests))
    assert coverage["if"] == "github.event_name == 'workflow_dispatch' && inputs.full_tests"
    # BaseLoader preserves GitHub's `on` key rather than parsing it as a YAML 1.1 boolean.
    events = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)["on"]
    assert events["workflow_dispatch"]["inputs"]["full_tests"] == {
        "description": "Run the full Python and browser coverage suite",
        "type": "boolean",
        "default": "false",
    }

    coverage_commands = _run_commands(coverage)
    assert any(
        "playwright install --with-deps chromium" in command for command in coverage_commands
    )
    coverage_runs = [c for c in coverage_commands if c.startswith("make test-cov")]
    assert len(coverage_runs) == 2
    assert "-n 2 --dist=loadgroup --no-loadscope-reorder --durations=25" in coverage_runs[0]
    assert "not browser and not llm_live" in coverage_runs[0]
    assert "--cov-fail-under=0" in coverage_runs[0]
    assert "browser and not llm_live" in coverage_runs[1]
    assert "--cov-append" in coverage_runs[1]
    assert "--cov-fail-under=0" not in coverage_runs[1]
    assert all("--ignore" not in c and "--no-cov" not in c for c in coverage_runs)
    assert not any("npm" in c for c in coverage_commands)
    assert any("npm run build" in c and "npm test" in c for c in _run_commands(frontend))
    assert any("mypy tracker" in c for c in _run_commands(checks))

    assert "needs" not in checks
    assert "needs" not in tests
    assert "needs" not in coverage
    assert "needs" not in frontend
    assert "needs" not in smoke
    assert set(validate["needs"]) == {"checks", "tests", "coverage", "frontend"}
    assert validate["if"] == "always()"
    validation_gate = " ".join(_run_commands(validate))
    for job in validate["needs"]:
        assert f"test '${{{{ needs.{job}.result }}}}' = success" in validation_gate
    assert "test '${{ needs.coverage.result }}' = skipped" in validation_gate
    assert set(publish["needs"]) == {"validate", "container-smoke"}
    # A status function overrides implicit success(), which includes skipped ancestors.
    # Only the two immediate required gates may authorize image publication.
    assert publish["if"] == (
        "!cancelled() && github.event_name != 'pull_request' && "
        "needs.validate.result == 'success' && needs.container-smoke.result == 'success'"
    )


def test_container_builds_share_a_repository_scoped_gha_cache() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    for job_name in ("container-smoke", "publish"):
        job = jobs[job_name]
        assert isinstance(job, dict)
        build_step = next(
            step
            for step in job["steps"]
            if isinstance(step, dict) and step.get("uses") == "docker/build-push-action@v6"
        )
        inputs = build_step["with"]
        assert isinstance(inputs, dict)
        assert inputs["cache-from"] == "type=gha,scope=osrs-recommender"
        assert inputs["cache-to"] == "type=gha,scope=osrs-recommender,mode=max"


@pytest.mark.parametrize("job", ["checks", "tests", "frontend", "coverage"])
@pytest.mark.parametrize("result", ["success", "skipped", "failure", "cancelled"])
def test_publication_gate_requires_success_except_for_omitted_full_coverage(job, result):
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX shell unavailable; exercised by Linux CI")
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    validate = jobs["validate"]
    assert isinstance(validate, dict)
    command = " ".join(_run_commands(validate))
    for name in ("checks", "tests", "frontend", "coverage"):
        command = command.replace(
            "${{ needs." + name + ".result }}", result if name == job else "success"
        )
    outcome = subprocess.run([shell, "-c", command], capture_output=True, check=False)
    expected = result == "success" or (job == "coverage" and result == "skipped")
    assert (outcome.returncode == 0) is expected


def test_workflow_cancels_superseded_runs_for_the_same_ref() -> None:
    workflow = _workflow()

    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }
