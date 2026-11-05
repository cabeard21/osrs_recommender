"""Prayer selections round-trip through browser optimization and exact evaluation."""

from datetime import UTC, datetime

import pytest

from tests.api.test_gear_evaluations import evaluation_body
from tracker.db.models import Player, SkillSnapshot
from tracker.domain.types import Source


def prayer_body(client, session_factory, policy):
    body = evaluation_body(client, session_factory)
    with session_factory() as session:
        player = session.query(Player).one()
        session.add(
            SkillSnapshot(
                player_id=player.id,
                skill="prayer",
                level=99,
                source=Source.RUNELITE,
                observed_at=datetime.now(UTC),
            )
        )
        session.commit()
    body["scenario"]["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    body["scenario"]["roles"][0]["prayers"] = policy
    return body


@pytest.mark.parametrize("auto", [False, True])
def test_selected_prayers_preserve_exact_evaluation_parity(client, session_factory, auto):
    body = prayer_body(
        client,
        session_factory,
        {
            "mode": "optimize",
            "allowed_ids": ["ultimate_strength"],
        },
    )
    role = body["scenario"]["roles"][0]
    if auto:
        role.update(
            allowed_disciplines=["melee"],
            combat_options={
                "attack_types": ["slash"],
                "stances": ["accurate"],
                "spells": [],
            },
        )
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert optimized.status_code == 200, optimized.text
    row = optimized.json()["result"]["selected_solution"]["loadouts"]["single"]
    assert row["selected_prayer_ids"] == ["ultimate_strength"]
    body["baseline_loadouts"] = body["proposed_loadouts"] = {"single": row["equipment"]}
    body["selected_prayer_ids"] = {"single": row["selected_prayer_ids"]}
    body["baseline_combat_options"] = body["proposed_combat_options"] = {
        "single": row["combat_option"],
    }
    evaluated = client.post("/ui-api/gear/evaluations", json=body)
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["proposed"]["performance"] == row["performance"]
    assert evaluated.json()["proposed"]["selected_prayer_ids"] == ["ultimate_strength"]


def test_optimized_evaluation_requires_setup_and_rejects_outside_allowlist(client, session_factory):
    body = prayer_body(
        client,
        session_factory,
        {
            "mode": "optimize",
            "allowed_ids": ["ultimate_strength"],
        },
    )
    assert client.post("/ui-api/gear/evaluations", json=body).status_code == 422
    body["selected_prayer_ids"] = {"single": ["incredible_reflexes"]}
    assert client.post("/ui-api/gear/evaluations", json=body).status_code == 422


def test_unavailable_and_forged_prayers_rejected(client, session_factory):
    body = prayer_body(client, session_factory, {"mode": "fixed", "selected_ids": ["piety"]})
    assert client.post("/ui-api/gear/optimizations", json=body["scenario"]).status_code == 422


def test_fixed_prayer_order_is_semantically_irrelevant(client, session_factory):
    body = prayer_body(
        client,
        session_factory,
        {
            "mode": "fixed",
            "selected_ids": ["steel_skin", "incredible_reflexes"],
        },
    )
    body["selected_prayer_ids"] = {"single": ["incredible_reflexes", "steel_skin"]}
    reply = client.post("/ui-api/gear/evaluations", json=body)
    assert reply.status_code == 200, reply.text
    role = body["scenario"]["roles"][0]
    role["prayers"] = {"mode": "disabled"}
    role["active_prayer_ids"] = ["piety"]
    assert client.post("/ui-api/gear/optimizations", json=body["scenario"]).status_code == 422
