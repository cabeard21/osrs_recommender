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


def test_ci_runs_complete_parallel_coverage_independently_of_other_checks() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)

    validate = jobs["validate"]
    checks = jobs["checks"]
    coverage = jobs["coverage"]
    frontend = jobs["frontend"]
    smoke = jobs["container-smoke"]
    publish = jobs["publish"]
    assert isinstance(validate, dict)
    assert isinstance(checks, dict)
    assert isinstance(coverage, dict)
    assert isinstance(frontend, dict)
    assert isinstance(smoke, dict)
    assert isinstance(publish, dict)

    coverage_commands = _run_commands(coverage)
    assert any(
        "playwright install --with-deps chromium" in command for command in coverage_commands
    )
    command = next(c for c in coverage_commands if c.startswith("make test-cov"))
    assert "-n 2 --dist=loadscope --durations=25" in command
    assert "--ignore" not in command and "--no-cov" not in command
    assert not any("npm" in c for c in coverage_commands)
    assert any("npm run build" in c and "npm test" in c for c in _run_commands(frontend))
    assert any("mypy tracker" in c for c in _run_commands(checks))

    assert "needs" not in checks
    assert "needs" not in coverage
    assert "needs" not in frontend
    assert "needs" not in smoke
    assert set(validate["needs"]) == {"checks", "coverage", "frontend"}
    assert validate["if"] == "always()"
    validation_gate = " ".join(_run_commands(validate))
    for job in validate["needs"]:
        assert f"test '${{{{ needs.{job}.result }}}}' = success" in validation_gate
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
