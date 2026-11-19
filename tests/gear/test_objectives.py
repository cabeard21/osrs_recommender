"""Canonical objective descriptors and exact vector projections."""

import pytest

from tracker.gear.objectives import (
    ObjectiveDescriptor,
    canonical_objectives,
    objective_value,
    required_objective_skills,
)


def test_objective_canonicalization_and_singleton_equivalence():
    objectives = canonical_objectives(
        [
            {"kind": "defence_roll", "styles": ["magic", "stab"], "aggregation": "mean"},
            {"kind": "defence_roll", "styles": ["stab"], "aggregation": "mean"},
            {"kind": "defence_roll", "styles": ["stab"], "aggregation": "minimum"},
        ]
    )
    assert len(objectives) == 2
    assert {objective.id for objective in objectives} == {
        "defence_roll:mean:stab+magic",
        "defence_roll:minimum:stab",
    }
    assert required_objective_skills(objectives) == {"defence", "magic"}


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "defence_roll"},
        {"kind": "defence_roll", "styles": ["invalid"]},
        {"kind": "accuracy", "styles": ["magic"]},
        {"kind": "prayer_bonus", "aggregation": "mean"},
        {"kind": "unknown"},
    ],
)
def test_rejects_invalid_objective_descriptors(bad):
    with pytest.raises(ValueError):
        ObjectiveDescriptor.model_validate(bad)


def test_minimum_and_mean_use_only_included_rolls():
    performance = {"player_defence_rolls": {"stab": 0, "ranged": 30, "magic": 90}}
    for aggregation, expected in [("minimum", 30), ("mean", 60)]:
        objective = ObjectiveDescriptor(
            kind="defence_roll", styles=("ranged", "magic"), aggregation=aggregation
        )
        assert objective_value(objective, performance) == expected
    with pytest.raises(ValueError, match="unavailable"):
        objective_value(objective, {"player_defence_rolls": {"ranged": 30}})


def test_request_conflict_and_legacy_serialization():
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig

    request = OptimizationRequest(roles=(RoleConfig(id="a", style="slash"),))
    assert "objectives" not in request.model_dump(mode="json")
    with pytest.raises(ValueError, match="secondary_priority"):
        OptimizationRequest(roles=request.roles, secondary_priority="accuracy", objectives=())


def test_magic_damage_metadata_reports_percentage_points():
    from tracker.gear.objectives import objective_definitions

    assert (
        objective_definitions((ObjectiveDescriptor(kind="magic_damage_bonus"),))[0]["unit"]
        == "percent"
    )


def test_cost_is_minimized_without_exposing_negative_or_unknown_values():
    from tracker.gear.objectives import objective_definitions, objective_values
    from tracker.gear.vector_archive import VectorArchive

    cost = ObjectiveDescriptor(kind="gp_per_damage")
    assert objective_definitions([cost])[0]["direction"] == "minimize"
    assert objective_values([cost], {}, {"gp_per_damage": 0}) == {cost.id: 0}
    assert objective_values([cost], {}, {"gp_per_damage": None}) == {}
    archive = VectorArchive((cost.id,))
    try:
        for value in (3.0, 1.0, None):
            archive.add(
                {
                    "score": 9,
                    "loadouts": {},
                    "objective_values": {cost.id: value} if value is not None else {},
                }
            )
        assert [row["objective_values"][cost.id] for row in archive.iter_solutions()] == [1.0]
    finally:
        archive.close()


def test_wilderness_objective_uses_exact_trip_loss_and_minimizes_it():
    from tracker.gear.objectives import objective_definitions, objective_values
    from tracker.gear.vector_archive import VectorArchive

    risk = ObjectiveDescriptor(kind="wilderness_loss_gp")
    (definition,) = objective_definitions((risk,))
    assert (definition["unit"], definition["direction"]) == ("GP", "minimize")
    assert objective_values((risk,), {}, wilderness_risk={"loss_gp": None}) == {}
    archive = VectorArchive((risk.id,))
    try:
        for score, loss in ((8, 0), (10, 100), (9, 150), (12, None)):
            values = objective_values((risk,), {}, wilderness_risk={"loss_gp": loss})
            archive.add(
                {
                    "score": score,
                    "loadouts": {"a": {"equipment": {"head": score}}},
                    "objective_values": values,
                }
            )
        assert [(r["score"], r["objective_values"][risk.id]) for r in archive.iter_solutions()] == [
            (10, 100),
            (8, 0),
        ]
    finally:
        archive.close()
