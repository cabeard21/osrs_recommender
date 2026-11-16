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
