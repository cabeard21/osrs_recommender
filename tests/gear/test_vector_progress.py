"""Vector search progress enters tradeoffs before work and reserves finalist progress."""

from tests.gear.test_factored_multi import multi_case
from tracker.gear.optimizer import optimize
from tracker.gear.progress import LANE_STAGES, StageReporter
from tracker.gear.vector_search import VectorSearch


def test_vector_work_starts_in_frontiers_and_never_reenters_the_stage(monkeypatch):
    import tracker.gear.optimizer as optimizer_module

    args = list(multi_case(True))
    args[1] = args[1].model_copy(
        update={
            "roles": args[1].roles[:1],
            "objectives": (),
            "secondary_priority": "default",
        }
    )
    from tracker.gear.objectives import canonical_objectives

    args[1] = args[1].model_copy(
        update={"objectives": canonical_objectives([{"kind": "prayer_bonus"}])}
    )
    events = []
    original = VectorSearch.explore

    def explore(engine, seeds):
        assert events[-1]["phase"] == "frontiers"
        engine.nodes = engine.limit - 1
        engine.tick()
        assert events[-1]["stage_done"] <= 650
        # The separate finalist phase must still have room after all node work.
        engine.report_refinement(0.5)
        assert 650 < events[-1]["stage_done"] < 1000
        return original(engine, seeds)

    monkeypatch.setattr(VectorSearch, "explore", explore)
    monkeypatch.setattr(
        optimizer_module, "StageReporter", lambda emit: StageReporter(emit, interval=0)
    )
    result = optimize(*args, progress=events.append)
    phases = [event["phase"] for event in events if event["phase"] in LANE_STAGES]
    assert phases.count("frontiers") >= 2  # Stage start plus in-stage updates.
    entered = [event for event in events if event["phase"] == "frontiers"]
    assert sum(event["stage_done"] == 0 for event in entered) == 1
    assert [event["stage_done"] for event in entered] == sorted(
        event["stage_done"] for event in entered
    )
    indices = [LANE_STAGES.index(phase) for phase in phases]
    assert indices == sorted(indices)
    for group in result["objective_frontiers"]:
        group["points"].close()


def test_vector_finalist_progress_does_not_change_discoveries_or_attempts():
    from tests.gear.test_vector_refinement import engine, solution
    from tracker.gear.vector_refinement import _finalist

    seed = solution({"0": {"head": 1, "body": 3}})

    def evaluate(assignment):
        score = int(assignment["0"].get("head") == 2) + int(assignment["0"].get("body") == 4)
        return solution(assignment, score=1 + score, value=1 + score)

    baseline = engine(evaluate)
    expected = _finalist(baseline, seed, limit=12)
    observed = engine(evaluate)
    fractions = []
    actual = _finalist(observed, seed, limit=12, progress=fractions.append)
    assert actual == expected
    assert observed.offered == baseline.offered
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1
    assert any(0 < fraction < 1 for fraction in fractions)
