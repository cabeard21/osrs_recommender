"""Exact amulet effects survive inspection, optimization, evaluation and workers."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.db.models import SkillSnapshot
from tracker.gear.parallel_payload import context_payload, decode_context

AMULETS = (34407, 34413, 34419, 34425, 34428)


@pytest.mark.parametrize("support_policy", ["verified_only", "community_best_effort"])
def test_elemental_amulets_are_verified_items(client, session_factory, support_policy):
    scenario(client, session_factory, ids=AMULETS)
    for item_id in AMULETS:
        reply = client.get(
            f"/ui-api/gear/items/{item_id}", params={"support_policy": support_policy}
        )
        assert reply.status_code == 200, reply.text
        item = reply.json()
        assert item["support_status"] == "verified"
        assert item["wear"]["status"] == "satisfied"
        assert item["equipment"]["requirements_complete"]
        assert item["equipment"]["unsupported_effects"] == []
        assert item["equipment"]["elemental_spell_bonus"]["base_max_hit_bonus"] == 2
        assert item["equipment"]["bonuses"]["magic"] == 10
        assert item["equipment"]["bonuses"]["magic_damage"] == 0
        assert item["acquisition"] == "tradeable"


@pytest.mark.parametrize("item_id", AMULETS)
def test_amulet_optimization_and_fixed_evaluation_agree(client, session_factory, item_id):
    body = scenario(client, session_factory, ids=(1381, item_id))
    body["roles"] = [
        {
            "id": "single",
            "style": "magic",
            "stance": "accurate",
            "spell": "wind_blast",
            "locks": {"weapon": 1381, "neck": item_id},
        }
    ]
    optimized = client.post("/ui-api/gear/optimizations", json=body)
    assert optimized.status_code == 200, optimized.text
    loadout = optimized.json()["result"]["selected_solution"]["loadouts"]["single"]
    assert loadout["performance"]["supported"]
    assert loadout["performance"]["max_hit"] == (18 if item_id in (34407, 34428) else 16)
    applied = loadout["performance"]["elemental_amulet_bonus"]
    assert (applied is not None) == (item_id in (34407, 34428))
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": loadout["equipment"]},
            "proposed_loadouts": {"single": loadout["equipment"]},
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == loadout["performance"]
    assert evaluated.json()["model_version"] == optimized.json()["result"]["model_version"]


def test_amulet_metadata_survives_worker_context(app):
    service = app.state.gear_service
    catalog = service.equipment_catalog()
    # The complete context is the same detached boundary used by spawned workers.
    payload, identity = context_payload(service.content, catalog)
    _, decoded = decode_context(payload, identity)
    for item_id in AMULETS:
        assert decoded.items[item_id] == catalog.items[item_id]
        assert decoded.items[item_id].elemental_spell_bonus is not None


@pytest.mark.parametrize("level", [58, 59])
def test_amulet_wear_boundary_does_not_require_runecraft(client, session_factory, level):
    scenario(client, session_factory, ids=AMULETS)
    with session_factory() as session:
        session.query(SkillSnapshot).filter(SkillSnapshot.skill == "magic").update(
            {SkillSnapshot.level: level}
        )
        session.commit()
    for item_id in AMULETS:
        item = client.get(f"/ui-api/gear/items/{item_id}").json()
        assert (item["wear"]["status"] == "satisfied") == (level == 59)
        assert (not item["wear"]["unmet"]) == (level == 59)
