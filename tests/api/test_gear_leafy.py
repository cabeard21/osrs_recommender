"""Leafy target restrictions survive browser API boundaries."""

from copy import deepcopy

import pytest

from tests.api.test_gear_optimizations import NOW, scenario
from tracker.db.models import SkillSnapshot
from tracker.domain.types import Source
from tracker.gear.npcs import npc_catalog


def leafy_scenario(client, session_factory, ids=(20727, 11865)):
    body = scenario(client, session_factory, ids=ids)
    with session_factory() as session:
        from tracker.db.models import Player

        player = session.query(Player).first()
        session.add(
            SkillSnapshot(
                player_id=player.id,
                skill="slayer",
                level=70,
                source=Source.RUNELITE,
                observed_at=NOW,
            )
        )
        session.commit()
    body["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    catalog = npc_catalog()
    entry = next(e for e in catalog.entries.values() if e["npc_id"] == 427)
    body["roles"] = [
        {
            "id": "single",
            "style": "slash",
            "on_slayer_task": True,
            "locks": {"weapon": 20727, "head": 11865},
            "target": deepcopy(entry["target"]),
            "target_selection": {"key": entry["key"], "catalog_revision": catalog.revision},
        }
    ]
    return body


def test_leafy_optimization_and_evaluation_agree(client, session_factory):
    body = leafy_scenario(client, session_factory)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    loadout = reply.json()["result"]["selected_solution"]["loadouts"]["single"]
    assert loadout["performance"]["leafy_bonus"]["item_id"] == 20727
    equipment = loadout["equipment"]
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": equipment},
            "proposed_loadouts": {"single": equipment},
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == loadout["performance"]


@pytest.mark.parametrize("route", ["optimizations", "evaluations"])
def test_cannot_strip_leafy_trait(client, session_factory, route):
    body = leafy_scenario(client, session_factory)
    body["roles"][0]["target"]["traits"] = []
    payload = (
        body
        if route == "optimizations"
        else {
            "scenario": body,
            "baseline_loadouts": {"single": {"weapon": 20727}},
            "proposed_loadouts": {"single": {"weapon": 20727}},
        }
    )
    reply = client.post("/ui-api/gear/" + route, json=payload)
    assert reply.status_code == 422, reply.text
    assert "restrictions" in reply.text
