"""Dragonbane survives browser optimization and exact evaluation boundaries."""

from copy import deepcopy

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.gear.npcs import npc_catalog


@pytest.mark.parametrize(
    "style,weapon,ammo,spell",
    [
        ("ranged", 21012, 9243, None),
        ("magic", 30070, None, "fire_wave"),
    ],
)
def test_dragonbane_optimization_and_exact_evaluation_agree(
    client, session_factory, style, weapon, ammo, spell
):
    ids = (weapon, ammo) if ammo else (weapon,)
    body = scenario(client, session_factory, ids=ids)
    entry = next(
        e
        for e in npc_catalog().entries.values()
        if e["name"] == "Blue dragon" and e["support_status"] == "supported"
    )
    equipment = {"weapon": weapon, **({"ammunition": ammo} if ammo else {})}
    body["locks"] = equipment
    body["roles"] = [
        {
            "id": "single",
            "style": style,
            "stance": "rapid" if ammo else "accurate",
            **({"spell": spell} if spell else {}),
            "target": deepcopy(entry["target"]),
            "target_selection": {
                "key": entry["key"],
                "catalog_revision": entry["catalog_revision"],
            },
        }
    ]
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    assert result["selected_solution"] is not None, result
    performance = result["selected_solution"]["loadouts"]["single"]["performance"]
    assert performance["dragonbane_bonus"]["item_id"] == weapon
    assert result["assumptions"]["dragonbane_model_version"] == "dragonbane-v1"
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": equipment},
            "proposed_loadouts": {"single": equipment},
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == performance
    body["roles"][0]["target"]["traits"] = []
    rejected = client.post("/ui-api/gear/optimizations", json=body)
    assert rejected.status_code == 422
