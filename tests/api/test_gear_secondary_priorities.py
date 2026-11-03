"""Secondary preference identity and Python-authoritative browser projection."""

import pytest

from tests.api.test_gear_joint_optimizations import joint_scenario
from tests.api.test_gear_optimizations import scenario
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition


def test_default_priority_preserves_omitted_behavior(client, session_factory):
    body = scenario(client, session_factory)
    omitted = client.post("/ui-api/gear/optimizations", json=body)
    explicit = client.post(
        "/ui-api/gear/optimizations", json={**body, "secondary_priority": "default"}
    )
    assert omitted.status_code == explicit.status_code == 200
    left, right = omitted.json(), explicit.json()
    assert left["scenario_fingerprint"] == right["scenario_fingerprint"]
    assert left["result"]["selected_solution"] == right["result"]["selected_solution"]
    assert left["result"]["selected_solution"]["secondary_value"] is None


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("mode", ["fast", "thorough"])
@pytest.mark.parametrize("priority", ["balanced_defence", "magic_ranged_defence"])
def test_priority_provenance_and_weighted_value(
    client, app, session_factory, count, mode, priority
):
    body = {
        **joint_scenario(client, app, session_factory, count),
        "optimization_mode": mode,
        "secondary_priority": priority,
    }
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    result = data["result"]
    assert data["secondary_priority"] == priority
    assert data["scenario"]["secondary_priority"] == priority
    assert result["secondary_priority"] == priority
    styles = (
        ("magic", "ranged")
        if priority == "magic_ranged_defence"
        else ("stab", "slash", "crush", "ranged", "magic")
    )
    for solution in [
        result["selected_solution"],
        result["unrestricted"],
        *(p["solution"] for p in result["curve"]),
    ]:
        if solution is None:
            continue
        assert solution["secondary_priority"] == priority
        expected = sum(
            result["active_time_shares"][role]
            * sum(loadout["performance"]["bonuses"][f"defence_{style}"] for style in styles)
            / len(styles)
            for role, loadout in solution["loadouts"].items()
        )
        assert solution["secondary_value"] == pytest.approx(expected)
    switched = client.post(
        "/ui-api/gear/optimizations", json={**body, "secondary_priority": "prayer_bonus"}
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["scenario_fingerprint"] != data["scenario_fingerprint"]
    assert switched.json()["work_budget_policy"] == data["work_budget_policy"]


@pytest.mark.parametrize("priority", ["unknown", "Default", None, True, 1, {}, []])
def test_invalid_priorities_are_field_errors(client, session_factory, priority):
    response = client.post(
        "/ui-api/gear/optimizations",
        json={**scenario(client, session_factory), "secondary_priority": priority},
    )
    assert response.status_code == 422
    assert any(row["path"] == "secondary_priority" for row in response.json()["error"]["fields"])


def test_trial_retains_selected_priority_identity(client, session_factory):
    body = {**scenario(client, session_factory), "secondary_priority": "accuracy"}
    optimized = client.post("/ui-api/gear/optimizations", json=body)
    assert optimized.status_code == 200, optimized.text
    data = optimized.json()
    loadouts = {"single": data["result"]["selected_solution"]["loadouts"]["single"]["equipment"]}
    response = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": data["scenario"],
            "baseline_loadouts": loadouts,
            "proposed_loadouts": loadouts,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["scenario_fingerprint"] == data["scenario_fingerprint"]


@pytest.mark.parametrize("mode", ["fast", "thorough"])
def test_equal_dps_priority_switch_changes_equipment(client, app, session_factory, mode):
    # Synthetic bonus fixtures isolate tie behavior from catalog review decisions.
    original = app.state.gear_service.equipment_catalog()
    helmets = [
        EquipmentDefinition(
            id=900001,
            name="Defence fixture",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(defence_stab=20),
        ),
        EquipmentDefinition(
            id=900002,
            name="Prayer fixture",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(prayer=5),
        ),
    ]
    app.state.gear_service._equipment = EquipmentCatalog(
        {4151: original.items[4151], **{i.id: i for i in helmets}}, revision="priority-fixture"
    )
    body = {
        **scenario(client, session_factory, ids=(4151, 900001, 900002)),
        "optimization_mode": mode,
        "locks": {"weapon": 4151},
    }
    solutions = {}
    for priority in ("default", "stab_defence", "prayer_bonus"):
        response = client.post(
            "/ui-api/gear/optimizations", json={**body, "secondary_priority": priority}
        )
        assert response.status_code == 200, response.text
        solutions[priority] = response.json()["result"]["selected_solution"]
    assert len({s["score"] for s in solutions.values()}) == 1
    assert solutions["stab_defence"]["loadouts"]["single"]["equipment"]["head"] == 900001
    assert solutions["prayer_bonus"]["loadouts"]["single"]["equipment"]["head"] == 900002
    assert solutions["stab_defence"]["secondary_value"] == 20
    assert solutions["prayer_bonus"]["secondary_value"] == 5
