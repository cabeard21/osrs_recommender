"""Canonical NPC selection, search, exact evaluation and impossible equipment locks."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.gear.npcs import npc_catalog


@pytest.mark.parametrize(
    "npc_id,style,ids,tier",
    [
        (9560, "slash", (4151,), 1),
        (4427, "slash", (4151, 21140), 2),
        (9756, "ranged", (33716, 21140), 3),
    ],
)
def test_selected_vampyre_round_trip(client, session_factory, npc_id, style, ids, tier):
    body = scenario(client, session_factory, ids=ids)
    body.update(
        mode="future",
        budget_gp=0,
        quest_overrides=dict.fromkeys(
            (
                "in_aid_of_the_myreque",
                "in_search_of_the_myreque",
                "priest_in_peril",
                "sins_of_the_father",
                "the_blood_moon_rises",
            ),
            "complete",
        ),
        locks={"weapon": ids[0]},
    )
    if tier == 1:
        body["quest_overrides"] = {}
    catalog = npc_catalog()
    entry = next(e for e in catalog.entries.values() if e["npc_id"] == npc_id)
    body["roles"] = [
        {
            "id": "vyre",
            "style": style,
            "stance": "rapid" if style == "ranged" else "accurate",
            "target": entry["target"],
            "target_selection": {"key": entry["key"], "catalog_revision": catalog.revision},
        }
    ]
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["assumptions"]["vampyre_model_version"]
    assert result["selected_solution"], result["limitations"]
    loadout = result["selected_solution"]["loadouts"]["vyre"]
    assert loadout["performance"]["vampyre_bonus"]["tier"] == tier
    if tier == 1:
        assert loadout["performance"]["dps"] > 0
        assert loadout["equipment"]["weapon"] == 4151
    else:
        assert loadout["equipment"]["ring"] == 21140
    selected = {"vyre": loadout["equipment"]}
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": selected,
            "proposed_loadouts": selected,
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == loadout["performance"]
    if tier == 2:
        body["locks"]["ring"] = None
        blocked = client.post("/ui-api/gear/optimizations", json=body)
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["result"]["selected_solution"] is None
        assert "Efaritay" in " ".join(blocked.json()["result"]["limitations"])
