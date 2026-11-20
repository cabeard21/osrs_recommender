import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import Player
from tracker.gear.optimizer import SLOTS
from tracker.gear.salve import MODEL_VERSION


@pytest.mark.parametrize("trait", ["undead", "spectral"])
def test_salve_ownership_and_effect_through_optimization_and_fixed_evaluation(
    client, session_factory, trait
):
    amulet = 25278
    body = scenario(client, session_factory, ids=(amulet, 1333))
    with session_factory() as session:
        player = session.query(Player).one()
        player.members = True
        session.commit()
    body["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    equipment = {"neck": amulet, "weapon": 1333}
    body.update(
        locks={slot: equipment.get(slot) for slot in SLOTS},
        roles=[
            {
                "id": "fight",
                "style": "slash",
                "stance": "aggressive",
                "target": {"name": "Test undead status", "traits": [trait]},
            }
        ],
    )
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    report = response.json()["result"]
    assert report["assumptions"]["salve_model_version"] == MODEL_VERSION
    solution = report["selected_solution"]
    assert solution is not None, report
    loadout = solution["loadouts"]["fight"]
    assert loadout["equipment"]["neck"] == amulet
    assert solution["purchases"] == []
    expected = (
        {
            "item_id": amulet,
            "accuracy_percent": 20,
            "damage_percent": 20,
            "suppresses_slayer": False,
        }
        if trait == "undead"
        else None
    )
    assert loadout["performance"]["salve_bonus"] == expected

    exact = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"fight": equipment},
            "proposed_loadouts": {"fight": equipment},
        },
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["proposed"]["performance"] == loadout["performance"]
    assert exact.json()["assumptions_fingerprint"] == report["assumptions_fingerprint"]
