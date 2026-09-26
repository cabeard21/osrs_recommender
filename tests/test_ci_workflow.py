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


def test_makefile_exposes_fast_and_complete_lanes() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "test:" in makefile
    assert '-m "not browser and not llm_live"' in makefile
    assert "test-full:" in makefile
    assert '-m "not llm_live"' in makefile
    assert "test-ci: test-full" in makefile
    assert "test-cov:" in makefile
    assert "--cov=tracker.quest_cape" in makefile
    assert "--cov-fail-under=80" in makefile


def test_ci_runs_complete_suite_and_parallelizes_container_smoke() -> None:
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
    assert any(
        "playwright install --with-deps chromium" in command for command in validate_commands
    )
    assert any(command.startswith("make test-cov") for command in validate_commands)

    assert "needs" not in validate
    assert "needs" not in smoke
    assert set(publish["needs"]) == {"validate", "container-smoke"}
    assert publish["if"] == "github.event_name != 'pull_request'"


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
