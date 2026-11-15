"""Safe-spot constraints survive browser optimization and exact comparison."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.api.gear_optimizations import BrowserOptimizationRequest, scenario_fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("safe_spotting", "true"),
        ("safe_spotting", 1),
        ("fight_duration_seconds", 0),
        ("fight_duration_seconds", 3601),
        ("fight_duration_seconds", True),
        ("fight_duration_seconds", 1.5),
    ],
)
def test_reach_settings_strict_at_browser_boundary(client, session_factory, field, value):
    body = scenario(client, session_factory)
    body["roles"][0][field] = value
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert field in str(reply.json()["error"]["fields"])


def test_reach_setting_roundtrip_and_fingerprint(client, session_factory):
    body = scenario(client, session_factory, ids=(1333,))
    original = BrowserOptimizationRequest.model_validate(body)
    assert original.roles[0].safe_spotting is False
    changed = {**body, "roles": [{**body["roles"][0], "safe_spotting": True}]}
    constrained = BrowserOptimizationRequest.model_validate(changed)
    assert scenario_fingerprint(original) != scenario_fingerprint(constrained)
    reply = client.post("/ui-api/gear/optimizations", json=changed)
    assert reply.status_code == 200, reply.text
    assert reply.json()["scenario"]["roles"][0]["safe_spotting"] is True
    assert reply.json()["result"]["selected_solution"] is None


def test_reach_blocks_exact_short_weapon_without_repair(client, session_factory):
    body = scenario(client, session_factory, ids=(1333,))
    body["roles"][0]["safe_spotting"] = True
    reply = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": {"weapon": 1333}},
            "proposed_loadouts": {"single": {"weapon": 1333}},
        },
    )
    assert reply.status_code == 200, reply.text
    proposed = reply.json()["proposed"]
    assert proposed["status"] in {"invalid", "unsupported"}
    assert proposed["performance"] is None
    assert "spot" in str(proposed["reasons"]).lower()


def test_safe_halberd_optimization_and_exact_comparison_agree(client, session_factory):
    body = scenario(client, session_factory, ids=(3202,))
    from tracker.db.models import Player

    with session_factory() as session:
        player = session.query(Player).one()
        player.members = True
        session.commit()
    body["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    body["roles"] = [
        {
            "id": "single",
            "style": "slash",
            "stance": "aggressive",
            "safe_spotting": True,
            "fight_duration_seconds": 60,
            "locks": {"weapon": 3202},
        }
    ]
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    selected = reply.json()["result"]["selected_solution"]
    assert selected is not None
    loadout = selected["loadouts"]["single"]
    evaluated = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": loadout["equipment"]},
            "proposed_loadouts": {"single": loadout["equipment"]},
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    assert (
        evaluated.json()["assumptions_fingerprint"]
        == reply.json()["result"]["assumptions_fingerprint"]
    )
    assert evaluated.json()["proposed"]["performance"] == loadout["performance"]
