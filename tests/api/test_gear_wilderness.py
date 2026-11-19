"""Wilderness settings round-trip through Gear and its archived results."""

from datetime import UTC, datetime

import pytest

from tests.api.test_gear_ammo import ammo_body
from tests.api.test_gear_evaluations import evaluation_body
from tests.api.test_gear_optimizations import scenario
from tests.gear.test_objective_store import result
from tracker.db.models import ItemPrice, SkillSnapshot
from tracker.domain.types import PriceSourceLayer, Source
from tracker.gear.optimizer import SLOTS

WILDERNESS = {"depth": "level_21_plus", "skulled": True, "protect_item": True}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"depth": "level_20_plus"}, "depth"),
        ({"skulled": "true"}, "skulled"),
        ({"protect_item": 1}, "protect_item"),
        ({"max_loss_gp": -1}, "max_loss_gp"),
        ({"max_loss_gp": 1.5}, "max_loss_gp"),
        ({"max_loss_gp": "5000"}, "max_loss_gp"),
        ({"max_loss_gp": False}, "max_loss_gp"),
        ({"max_loss_gp": 2**31}, "max_loss_gp"),
        ({"spell_casts": 0}, "spell_casts"),
        ({"spell_casts": 10_001}, "spell_casts"),
        ({"spell_casts": 1.5}, "spell_casts"),
        ({"spell_casts": True}, "spell_casts"),
        ({"death_value": 0}, "death_value"),
        ({}, "protect_item"),  # No observed or assumed Prayer level.
    ],
)
def test_invalid_wilderness_settings_have_field_local_errors(
    client, session_factory, overrides, field
):
    body = {**scenario(client, session_factory), "wilderness": WILDERNESS | overrides}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["fields"][0]["path"] == f"wilderness.{field}"


def test_wilderness_is_optional_and_fixed_results_use_same_frozen_context(client, session_factory):
    body = evaluation_body(client, session_factory, locks={"weapon": 4151})
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            SkillSnapshot(
                player_id=1, skill="prayer", level=25, source=Source.RUNELITE, observed_at=now
            )
        )
        session.merge(
            ItemPrice(
                item_id=4151,
                high_price_gp=2_000_000,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="test-wilderness",
            )
        )
        session.commit()
    body["scenario"]["expected_snapshot_id"] = client.get("/ui-api/gear/context").json()["account"][
        "snapshot_id"
    ]
    ordinary = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert ordinary.status_code == 200, ordinary.text
    ordinary = ordinary.json()
    assert "wilderness" not in ordinary["scenario"]
    assert "wilderness_risk" not in ordinary["result"]["selected_solution"]
    disabled = client.post(
        "/ui-api/gear/optimizations", json=body["scenario"] | {"wilderness": None}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["scenario_fingerprint"] == ordinary["scenario_fingerprint"]

    body["scenario"]["wilderness"] = WILDERNESS
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert optimized.status_code == 200, optimized.text
    optimized = optimized.json()
    assert optimized["scenario"]["wilderness"] == WILDERNESS
    assert optimized["scenario_fingerprint"] != ordinary["scenario_fingerprint"]
    assert (
        optimized["result"]["assumptions_fingerprint"]
        != ordinary["result"]["assumptions_fingerprint"]
    )
    selected = optimized["result"]["selected_solution"]
    assert selected["purchase_cost_gp"] == 0
    risk = selected["wilderness_risk"]
    assert risk["loss_gp"] == 0
    assert risk["without_protect_item_gp"] == 2_000_000
    assert risk["items"] == [{"item_id": 4151, "outcome": "kept", "loss_gp": 0, "quantity": 1}]
    assert risk["quantities"] == []

    evaluated = client.post("/ui-api/gear/evaluations", json=body)
    assert evaluated.status_code == 200, evaluated.text
    evaluated = evaluated.json()
    assert evaluated["baseline"]["wilderness_risk"] == risk
    assert evaluated["proposed"]["wilderness_risk"] == risk
    assert evaluated["scenario_fingerprint"] == optimized["scenario_fingerprint"]
    assert evaluated["assumptions_fingerprint"] == optimized["result"]["assumptions_fingerprint"]
    assert evaluated["price_revision"] == optimized["price_revision"]

    body["scenario"]["wilderness"] = WILDERNESS | {"protect_item": False}
    rejected = client.post("/ui-api/gear/evaluations", json=body)
    assert rejected.status_code == 200, rejected.text
    rejected = rejected.json()
    assert rejected["deltas"] is None
    assert rejected["proposed"]["status"] == "invalid"
    assert rejected["proposed"]["reasons"][0]["path"] == "budget_gp"
    assert rejected["proposed"]["wilderness_risk"]["loss_gp"] == 2_000_000


@pytest.mark.parametrize("fixed_trip", [False, True])
def test_arrow_comparisons_return_reviewed_quantities_within_risk_cap(
    client, session_factory, fixed_trip
):
    body = ammo_body(client, session_factory)
    body["loadout"].pop("cape")
    body["scenario"].update(
        budget_gp=0,
        wilderness={
            "depth": "level_1_20",
            "skulled": False,
            "protect_item": False,
            "max_loss_gp": 100,
        },
    )
    if fixed_trip:
        body["scenario"]["objectives"] = [{"kind": "wilderness_loss_gp"}]
        body["scenario"]["wilderness"]["attacks_per_setup"] = 5
    reply = client.post("/ui-api/gear/ammo-comparisons", json=body)
    assert reply.status_code == 200, reply.text
    points = reply.json()["points"]
    current = next(point for point in points if point["current"])
    assert all(point["wilderness_risk"]["loss_gp"] <= 100 for point in points)
    assert current["wilderness_risk"]["quantities"][0]["resource_id"] == 882
    if fixed_trip:
        assert current["wilderness_risk"]["quantities"][0]["quantity"] == 5


def magic_wilderness_scenario(client, session_factory, *, air_quote=True):
    submitted = scenario(client, session_factory, ids=(1387,))
    now = datetime.now(UTC)
    quotes = {1387: 100, 558: 2, 562: 2, **({556: 5} if air_quote else {})}
    with session_factory() as session:
        for item_id, gp in quotes.items():
            session.merge(
                ItemPrice(
                    item_id=item_id,
                    high_price_gp=gp,
                    high_trade_at=now,
                    fetched_at=now,
                    source=PriceSourceLayer.CACHED,
                    provider="test-wilderness-runes",
                )
            )
        session.commit()
    return submitted | {
        "roles": [
            {
                "id": "single",
                "style": "magic",
                "spell": "fire_bolt",
                "combat_options": {
                    "attack_types": ["magic"],
                    "stances": ["accurate"],
                    "spells": ["fire_bolt", "wind_strike"],
                },
            }
        ],
        "locks": {slot: 1387 if slot == "weapon" else None for slot in SLOTS},
        "reserved_supply_slots": 28,
        "wilderness": WILDERNESS | {"protect_item": False, "max_loss_gp": 270, "spell_casts": 10},
    }


def evaluate_wilderness_spells(client, scenario, first, second):
    loadouts = {"single": {"weapon": 1387}}
    return client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": scenario,
            "baseline_loadouts": loadouts,
            "proposed_loadouts": loadouts,
            "baseline_combat_options": {
                "single": {"attack_type": "magic", "stance": "accurate", "spell": first},
            },
            "proposed_combat_options": {
                "single": {"attack_type": "magic", "stance": "accurate", "spell": second},
            },
        },
    )


@pytest.mark.parametrize("archived", [False, True])
def test_magic_wilderness_compares_exact_spell_runes_and_reserved_slots(
    client, session_factory, archived
):
    request = magic_wilderness_scenario(client, session_factory)
    if archived:
        request["objectives"] = [{"kind": "prayer_bonus"}]
    reply = client.post("/ui-api/gear/optimizations", json=request)
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["scenario"]["wilderness"]["spell_casts"] == 10
    selected = payload["result"]["selected_solution"]
    assert selected is not None, payload["result"].get("limitations")
    assert selected["purchase_cost_gp"] == 0
    assert selected["loadouts"]["single"]["combat_option"]["spell"] == "fire_bolt"
    risk = selected["wilderness_risk"]
    assert risk["loss_gp"] == 270
    assert {
        (row["kind"], row["item_id"], row["resource_id"], row["quantity"])
        for row in risk["quantities"]
    } == {("rune", 556, 556, 30), ("rune", 562, 562, 10)}
    if archived:
        run = payload["objective_run"]
        detail = client.get(
            f"/ui-api/gear/optimization-runs/{run['run_id']}/solutions/{run['selected_solution_id']}"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["solution"]["wilderness_risk"] == risk
        assert run["scenario"]["wilderness"]["spell_casts"] == 10
        for group in run["groups"]:
            assert all(row["wilderness_loss_gp"] <= 270 for row in group["points"])

    compared = evaluate_wilderness_spells(client, request, "fire_bolt", "wind_strike")
    assert compared.status_code == 200, compared.text
    compared = compared.json()
    assert compared["scenario_fingerprint"] == payload["scenario_fingerprint"]
    assert compared["baseline"]["status"] == compared["proposed"]["status"] == "valid"
    assert compared["baseline"]["wilderness_risk"] == risk
    assert compared["proposed"]["wilderness_risk"]["loss_gp"] == 170
    assert len(compared["proposed"]["wilderness_risk"]["quantities"]) == 2

    request["wilderness"]["max_loss_gp"] = 269
    compared = evaluate_wilderness_spells(client, request, "fire_bolt", "wind_strike")
    assert compared.status_code == 200, compared.text
    compared = compared.json()
    assert compared["baseline"]["status"] == "invalid"
    assert compared["baseline"]["reasons"][0]["path"] == "wilderness.max_loss_gp"
    assert compared["baseline"]["wilderness_risk"]["loss_gp"] == 270
    assert compared["proposed"]["status"] == "valid"


def test_unknown_required_rune_price_rejects_fixed_risk_and_preserves_quantities(
    client, session_factory
):
    request = magic_wilderness_scenario(client, session_factory, air_quote=False)
    reply = evaluate_wilderness_spells(client, request, "fire_bolt", "fire_bolt")
    assert reply.status_code == 200, reply.text
    selected = reply.json()["proposed"]
    assert selected["status"] == "invalid"
    assert selected["reasons"][0]["path"] == "wilderness.max_loss_gp"
    risk = selected["wilderness_risk"]
    assert risk["loss_gp"] is None
    assert {row["resource_id"]: row["quantity"] for row in risk["quantities"]} == {556: 30, 562: 10}


def test_fixed_auto_prefers_the_spell_that_fits_wilderness_risk(client, session_factory):
    request = magic_wilderness_scenario(client, session_factory)
    request["roles"][0]["allowed_disciplines"] = ["magic"]
    request["wilderness"]["max_loss_gp"] = 269
    loadouts = {"single": {"weapon": 1387}}
    reply = client.post(
        "/ui-api/gear/evaluations",
        json={"scenario": request, "baseline_loadouts": loadouts, "proposed_loadouts": loadouts},
    )
    assert reply.status_code == 200, reply.text
    result = reply.json()["proposed"]
    assert result["status"] == "valid", (result["reasons"], result["wilderness_risk"])
    assert result["combat_option"]["spell"] == "wind_strike"
    assert result["wilderness_risk"]["loss_gp"] == 170


def test_purchase_and_pvp_loss_caps_are_independent(client, session_factory):
    request = scenario(client, session_factory, ids=())
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            ItemPrice(
                item_id=4151,
                high_price_gp=2_000_000,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="test-wilderness",
            )
        )
        session.commit()
    request.update(
        mode="usable", locks={slot: 4151 if slot == "weapon" else None for slot in SLOTS}
    )
    equipment = {"single": {"weapon": 4151}}

    def submit(purchase, risk, *, skulled):
        body = request | {
            "budget_gp": purchase,
            "wilderness": WILDERNESS
            | {"protect_item": False, "skulled": skulled, "max_loss_gp": risk},
        }
        optimized = client.post("/ui-api/gear/optimizations", json=body)
        assert optimized.status_code == 200, optimized.text
        compared = client.post(
            "/ui-api/gear/evaluations",
            json={"scenario": body, "baseline_loadouts": equipment, "proposed_loadouts": equipment},
        )
        assert compared.status_code == 200, compared.text
        return optimized.json(), compared.json()

    protected, trial = submit(1_999_999, 2_000_000, skulled=False)
    assert protected["result"]["selected_solution"] is None
    proposal = trial["proposed"]
    assert proposal["status"] == "invalid"
    assert proposal["purchase_cost_gp"] == 2_000_000
    assert proposal["wilderness_risk"]["loss_gp"] == 0
    assert {reason["path"] for reason in proposal["reasons"]} == {"budget_gp"}

    risky, trial = submit(2_000_000, 1_999_999, skulled=True)
    assert risky["result"]["selected_solution"] is None
    proposal = trial["proposed"]
    assert proposal["status"] == "invalid"
    assert proposal["purchase_cost_gp"] == proposal["wilderness_risk"]["loss_gp"] == 2_000_000
    assert {reason["path"] for reason in proposal["reasons"]} == {"wilderness.max_loss_gp"}

    exact, trial = submit(2_000_000, 2_000_000, skulled=True)
    assert exact["scenario"]["budget_gp"] == 2_000_000
    assert exact["scenario"]["wilderness"]["max_loss_gp"] == 2_000_000
    solution = exact["result"]["selected_solution"]
    assert solution["purchase_cost_gp"] == solution["wilderness_risk"]["loss_gp"] == 2_000_000
    assert trial["proposed"]["status"] == "valid"
    assert trial["proposed"]["wilderness_risk"] == solution["wilderness_risk"]
    assert trial["scenario_fingerprint"] == exact["scenario_fingerprint"]
    assert trial["assumptions_fingerprint"] == exact["result"]["assumptions_fingerprint"]
    assert exact["scenario_fingerprint"] != risky["scenario_fingerprint"]

    safe, trial = submit(2_000_000, 0, skulled=False)
    assert safe["scenario"]["wilderness"]["max_loss_gp"] == 0
    assert safe["result"]["selected_solution"]["purchase_cost_gp"] == 2_000_000
    assert trial["proposed"]["wilderness_risk"]["loss_gp"] == 0

    legacy, _ = submit(0, None, skulled=False)
    assert "max_loss_gp" not in legacy["scenario"]["wilderness"]
    solution = legacy["result"]["selected_solution"]
    assert solution["purchase_cost_gp"] == 2_000_000
    assert solution["wilderness_risk"]["loss_gp"] == 0
    replay = client.post("/ui-api/gear/optimizations", json=legacy["scenario"])
    assert replay.status_code == 200, replay.text
    assert replay.json()["scenario_fingerprint"] == legacy["scenario_fingerprint"]


def test_objective_run_summaries_and_details_preserve_wilderness_risk(client, app, session_factory):
    scenario(client, session_factory)
    source = result(2)
    expected_reports = []
    for index, point in enumerate(source["objective_frontiers"][0]["points"]):
        report = {
            "loss_gp": 9 - index,
            "without_protect_item_gp": None,
            "items": [],
            "quantities": [],
            "rules_revision": "test-wilderness",
        }
        expected_reports.append(report)
        point["solution"]["wilderness_risk"] = report
    published = app.state.gear_service.objective_store.publish_result(
        source,
        metadata={"scenario": {"budget_gp": 1, "wilderness": WILDERNESS | {"max_loss_gp": 9}}},
        player_id=1,
    )
    archive = f"/ui-api/gear/optimization-runs/{published['run_id']}"
    group = published["objective_frontiers"][0]["id"]
    metadata = client.get(archive)
    assert metadata.status_code == 200, metadata.text
    manifest = metadata.json()
    assert manifest["scenario"]["budget_gp"] == 1
    assert manifest["scenario"]["wilderness"]["max_loss_gp"] == 9
    assert {row["wilderness_loss_gp"] for row in manifest["groups"][0]["points"]} == {8, 9}
    rows = client.get(
        f"{archive}/frontiers/{group}/points",
        params={"sort": "wilderness_loss_gp", "direction": "asc"},
    )
    assert rows.status_code == 200, rows.text
    points = rows.json()["points"]
    assert [row["wilderness_loss_gp"] for row in points] == [8, 9]
    assert [row["purchase_cost_gp"] for row in points] == [1, 0]
    by_purchase = client.get(
        f"{archive}/frontiers/{group}/points",
        params={"sort": "purchase_cost_gp", "direction": "asc"},
    )
    assert by_purchase.status_code == 200, by_purchase.text
    assert [row["wilderness_loss_gp"] for row in by_purchase.json()["points"]] == [9, 8]
    details = client.get(f"{archive}/solutions/{points[0]['solution_id']}")
    assert details.status_code == 200, details.text
    assert details.json()["solution"]["wilderness_risk"] == expected_reports[1]


def test_wilderness_vector_run_replays_the_separate_caps(client, session_factory):
    request = scenario(client, session_factory) | {
        "budget_gp": 25_000,
        "wilderness": WILDERNESS | {"protect_item": False, "skulled": False, "max_loss_gp": 0},
        "objectives": [{"kind": "prayer_bonus"}],
    }
    response = client.post("/ui-api/gear/optimizations", json=request)
    assert response.status_code == 200, response.text
    payload = response.json()
    run = payload["objective_run"]
    assert run["scenario"]["budget_gp"] == 25_000
    assert run["scenario"]["wilderness"]["max_loss_gp"] == 0
    assert run["groups"][0]["points"][0]["wilderness_loss_gp"] == 0
    archive = f"/ui-api/gear/optimization-runs/{run['run_id']}"
    restored = client.get(archive)
    assert restored.status_code == 200, restored.text
    assert restored.json()["response"] == payload
    selected = client.get(f"{archive}/solutions/{run['selected_solution_id']}")
    assert selected.status_code == 200, selected.text
    assert selected.json()["solution"]["wilderness_risk"]["loss_gp"] == 0


def test_risk_objective_agrees_across_fixed_archived_and_timeline(client, session_factory):
    body = evaluation_body(client, session_factory, locks={"weapon": 4151})
    body["scenario"].update(
        wilderness={"skulled": False},
        objectives=[{"kind": "wilderness_loss_gp"}],
    )
    evaluated = client.post("/ui-api/gear/evaluations", json=body)
    assert evaluated.status_code == 200, evaluated.text
    for side in ("baseline", "proposed"):
        row = evaluated.json()[side]
        assert type(row["objective_values"]["wilderness_loss_gp"]) is int
        assert (
            row["objective_values"]["wilderness_loss_gp"] == row["wilderness_risk"]["loss_gp"] == 0
        )
    assert evaluated.json()["deltas"]["objective_values"] == {"wilderness_loss_gp": 0}
    optimized = client.post("/ui-api/gear/optimizations", json=body["scenario"])
    assert optimized.status_code == 200, optimized.text
    run = optimized.json()["objective_run"]
    timeline = client.post(
        "/ui-api/gear/potion-timelines",
        json={"run_id": run["run_id"], "solution_id": run["selected_solution_id"]},
    )
    assert timeline.status_code == 200, timeline.text
    for sample in [timeline.json()["baseline"], *timeline.json()["samples"]]:
        assert type(sample["objective_values"]["wilderness_loss_gp"]) is int
        assert sample["objective_values"] == {"wilderness_loss_gp": 0}
        assert all(
            "wilderness_loss_gp" not in role.get("objective_values", {})
            for role in sample["roles"].values()
        )


def test_direct_risk_timeline_values_one_trip_including_utility_switch(
    client, app, session_factory
):
    from tracker.gear.combat import MODEL_VERSION

    submitted = scenario(client, session_factory, ids=(4151, 1333))
    submitted.update(
        roles=[
            {"id": "main", "style": "slash"},
            {"id": "other", "style": "slash"},
            {"id": "spec", "style": "special", "parent_role": "main", "locks": {"weapon": 1333}},
        ],
        wilderness={"skulled": True, "max_loss_gp": 800},
        objectives=[{"kind": "wilderness_loss_gp"}],
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        for item, cost in ((4151, 600), (1333, 200)):
            session.merge(
                ItemPrice(
                    item_id=item,
                    high_price_gp=cost,
                    high_trade_at=now,
                    fetched_at=now,
                    source=PriceSourceLayer.CACHED,
                    provider="test",
                )
            )
        session.commit()
    setup = {
        "equipment": {"weapon": 4151},
        "combat_option": {"attack_type": "slash", "stance": "accurate"},
    }
    body = {
        "scenario": submitted,
        "selected_potion_ids": [],
        "expected_catalog_version": app.state.gear_service.equipment_catalog().revision,
        "expected_model_version": MODEL_VERSION,
        "loadouts": {"main": setup, "other": setup, "spec": {"equipment": {"weapon": 1333}}},
    }
    route = "/ui-api/gear/potion-timelines"
    response = client.post(route, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["baseline"]["objective_values"] == {"wilderness_loss_gp": 800}
    assert set(response.json()["baseline"]["roles"]) == {"main", "other"}
    assert (
        client.post(route, json={**body, "loadouts": {"main": setup, "other": setup}}).status_code
        == 422
    )
    submitted["wilderness"]["max_loss_gp"] = 799
    assert client.post(route, json=body).status_code == 422
