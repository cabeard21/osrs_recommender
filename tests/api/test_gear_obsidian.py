"""Obsidian ordinary support and disclosures survive the browser API boundary."""

from tests.api.test_gear_optimizations import scenario
from tests.gear.test_obsidian import RULES


def test_obsidian_inspection_and_locked_full_set_optimization(client, session_factory):
    body = scenario(client, session_factory, ids=tuple(RULES))
    for item_id in RULES:
        response = client.get(f"/ui-api/gear/items/{item_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["equipment"]["requirements_complete"]
        assert data["equipment"]["unsupported_effects"] == []
        assert data["wear"]["status"] == "satisfied"
        if item_id not in (6524, 6568, 20050):
            assert any("not applied" in text for text in data["limitations"])
    gear = {"head": 21298, "body": 21301, "legs": 21304, "weapon": 6523, "shield": 6524}
    body["roles"] = [{"id": "single", "style": "stab", "stance": "accurate", "locks": gear}]
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    selected = response.json()["result"]["selected_solution"]
    assert selected is not None
    loadout = selected["loadouts"]["single"]
    assert all(loadout["equipment"][slot] == item_id for slot, item_id in gear.items())
    assert loadout["performance"]["supported"]
    assert any("not applied" in text for text in loadout["performance"]["limitations"])
