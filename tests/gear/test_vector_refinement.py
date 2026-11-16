"""Full-vector refinement keeps complementary and resource-feasible discoveries."""

from types import SimpleNamespace

import pytest

from tracker.gear.vector_refinement import _finalist, _safe_improvement, refine


def solution(equipment, *, score=1, value=1, cost=0):
    return {
        "score": score,
        "objective_values": {"defence": value},
        "loadouts": {key: {"equipment": row} for key, row in equipment.items()},
        "carried_item_ids": sorted({item for row in equipment.values() for item in row.values()}),
        "purchase_cost_gp": cost,
        "gear_inventory_slots": 0,
        "max_gear_inventory_slots": 0,
        "maximum_actions": 0,
        "transitions": [],
    }


def engine(evaluate, roles=1, locks=None):
    configured = tuple(
        SimpleNamespace(id=str(i), style="slash", locks=locks or {}) for i in range(roles)
    )
    items = {
        1: SimpleNamespace(slot="head", two_handed=False),
        2: SimpleNamespace(slot="head", two_handed=False),
        3: SimpleNamespace(slot="body", two_handed=False),
        4: SimpleNamespace(slot="body", two_handed=False),
    }
    instance = SimpleNamespace(
        objectives=("defence",),
        ids=("defence",),
        search=SimpleNamespace(
            cancelled=None,
            request=SimpleNamespace(roles=configured, locks={}),
            eligible=items,
            items=items,
        ),
        pools={"head": [1, 2], "body": [3, 4]},
        archives={},
        offered=[],
        attempted=[],
        nodes=0,
        limit=10000,
        phase_limit=10000,
        identity=lambda assignment: repr(
            sorted((key, sorted(row.items())) for key, row in assignment.items())
        ),
    )

    def tick():
        instance.nodes += 1
        return instance.nodes <= instance.phase_limit

    def capture(assignment, charge=True):
        instance.attempted.append(assignment)
        value = evaluate(assignment)
        if value is not None:
            instance.offer(value)

    instance.tick, instance.capture = tick, capture
    instance.offer = lambda row: instance.offered.append(row)
    return instance


def test_thorough_substitutions_find_complementary_two_slot_change():
    def evaluate(assignment):
        equipment = assignment["0"]
        paired = equipment.get("head") == 2 and equipment.get("body") == 4
        return solution(assignment, score=2 if paired else 0, value=2 if paired else 0)

    seed = solution({"0": {"head": 1, "body": 3}})
    fast = engine(evaluate)
    refine(fast, [seed], False)
    assert not any(row["score"] == 2 for row in fast.offered)
    thorough = engine(evaluate)
    diagnostics = refine(thorough, [seed], True)
    assert any(row["score"] == 2 for row in thorough.offered)
    assert diagnostics["complete_assignment_attempts"] > 0


def test_shared_substitution_changes_roles_together():
    seed = solution({"0": {"head": 1}, "1": {"head": 1}})
    instance = engine(lambda assignment: solution(assignment), roles=2)
    diagnostics = refine(instance, [seed], False)
    assert any(
        assignment["0"].get("head") == assignment["1"].get("head") == 2
        for assignment in instance.attempted
    )
    assert diagnostics["shared_assignment_attempts"] > 0


def test_locked_coordinates_are_preserved_in_every_phase():
    seed = solution({"0": {"head": 1, "body": 3}})
    instance = engine(lambda assignment: solution(assignment), locks={"head": 1})
    refine(instance, [seed], True)
    assert all(assignment["0"]["head"] == 1 for assignment in instance.attempted)


def test_finalist_restart_finds_chained_improvement_and_respects_attempt_limit():
    seed = solution({"0": {"head": 1, "body": 3}})

    def evaluate(assignment):
        score = int(assignment["0"].get("head") == 2) + int(assignment["0"].get("body") == 4)
        return solution(assignment, score=1 + score, value=1 + score)

    instance = engine(evaluate)
    diagnostics = _finalist(instance, seed, limit=12)
    assert diagnostics["improvements"] == 2
    assert any(row["score"] == 3 for row in instance.offered)
    assert diagnostics["evaluated_assignments"] <= 12
    limited = _finalist(engine(evaluate), seed, limit=1)
    assert limited["evaluated_assignments"] == 1
    assert limited["work_budget_exhausted"]


def test_finalist_requires_all_objectives_and_nonincreasing_resources():
    seed = solution({"0": {"head": 1}}, score=5, value=5)
    assert not _safe_improvement(solution({"0": {"head": 2}}, score=6, value=4), seed, ("defence",))
    assert not _safe_improvement(
        solution({"0": {"head": 2}}, score=6, value=6, cost=1), seed, ("defence",)
    )
    assert _safe_improvement(solution({"0": {"head": 2}}, score=6, value=6), seed, ("defence",))


def test_refinement_honors_cancellation():
    instance = engine(lambda assignment: solution(assignment))
    instance.search.cancelled = lambda: True
    with pytest.raises(ValueError, match="optimization_cancelled"):
        refine(instance, [solution({"0": {"head": 1}})], True)


def test_dps_only_has_no_secondary_refinement_work():
    instance = engine(lambda assignment: solution(assignment))
    instance.objectives = ()
    diagnostics = refine(instance, [solution({"0": {"head": 1}})], True)
    assert diagnostics["shared_assignment_limit"] == 0
    assert diagnostics["finalist_seed_count"] == 0
    assert not instance.attempted
