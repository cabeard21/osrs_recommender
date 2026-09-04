from __future__ import annotations

from pathlib import Path

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


def test_makefile_exposes_fast_ci_and_exhaustive_local_lanes() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "test-ci:" in makefile
    assert "--ignore=tests/golden" in makefile
    assert "--ignore=tests/ui/test_pages_browser.py" in makefile
    assert "test-cov:" in makefile
    assert "--cov-fail-under=80" in makefile


def test_ci_keeps_exhaustive_suites_local_and_parallelizes_the_container_smoke() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    validate = jobs["validate"]
    smoke = jobs["container-smoke"]
    publish = jobs["publish"]
    assert isinstance(validate, dict)
    assert isinstance(smoke, dict)
    assert isinstance(publish, dict)

    validate_commands = _run_commands(validate)
    all_commands = "\n".join(
        command for job in jobs.values() if isinstance(job, dict) for command in _run_commands(job)
    )
    assert any(command.startswith("make test-ci") for command in validate_commands)
    assert "playwright install" not in all_commands
    assert "tests/golden" not in all_commands
    assert "test_pages_browser" not in all_commands
    assert "--cov" not in all_commands

    assert "needs" not in validate
    assert "needs" not in smoke
    assert set(publish["needs"]) == {"validate", "container-smoke"}


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


def test_workflow_cancels_superseded_runs_for_the_same_ref() -> None:
    workflow = _workflow()

    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }
