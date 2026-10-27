"""Joint browser results remain exact projections of the shared Python search."""

from datetime import UTC, datetime

import pytest

from tests.api.test_gear_optimizations import scenario
from tests.gear.test_ammunition_sharing import ammunition_case
from tracker.accounts.service import AccountService
from tracker.db.models import ItemPrice
from tracker.domain.types import PriceSourceLayer
from tracker.gear.catalog import EquipmentCatalog


def joint_scenario(client, app, session_factory, count=2):
    body = scenario(client, session_factory)
    original = app.state.gear_service.equipment_catalog()
    app.state.gear_service._equipment = EquipmentCatalog(
        {4151: original.items[4151]}, revision="joint-api-bundled-subset"
    )
    return {
        **body,
        "roles": [
            {
                "id": f"role-{i}",
                "style": "slash",
                "stance": "accurate",
                "weight": i + 1,
                "target": {"defence_level": 20 * i},
                "locks": {"weapon": 4151},
            }
            for i in range(count)
        ],
        "base_role": "role-0",
        "max_swaps": 2,
    }


@pytest.mark.parametrize("count", [2, 3, 4])
def test_joint_api_matches_one_shared_service_result(client, app, session_factory, count):
    body = joint_scenario(client, app, session_factory, count)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    direct = app.state.gear_service.optimize(AccountService(session_factory).get_snapshot(1), body)
    for key in ("curve", "unrestricted", "selected_solution", "active_time_shares", "search"):
        assert data["result"][key] == direct[key]
    solution = data["result"]["selected_solution"]
    assert len(solution["loadouts"]) == count
    assert solution["score"] == pytest.approx(
        sum(
            row["performance"]["dps"] * data["result"]["active_time_shares"][role_id]
            for role_id, row in solution["loadouts"].items()
        )
    )
    assert solution["distinct_items"] == 1
    assert solution["carried_item_ids"] == [4151]
    assert solution["gear_inventory_slots"] == solution["maximum_actions"] == 0
    assert data["baseline"]["status"] == "unavailable"
    assert data["baseline"]["performance"] is None
    assert "joint" in " ".join(data["baseline"]["reasons"]).lower()
    assert data["scenario"]["base_role"] == body["base_role"]
    assert data["scenario"]["expected_snapshot_id"] == body["expected_snapshot_id"]
    assert [r["target"]["defence_level"] for r in data["scenario"]["roles"]] == [
        20 * i for i in range(count)
    ]
    assert data["scenario_fingerprint"] and data["price_revision"]


def test_joint_utility_role_is_unscored_but_carried(client, app, session_factory):
    body = joint_scenario(client, app, session_factory)
    body["roles"][1] = {
        "id": "utility",
        "style": "special",
        "parent_role": "role-0",
        "locks": {"weapon": 4151},
    }
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    assert result["selected_solution"]["loadouts"]["utility"]["performance"]["dps"] is None
    assert result["active_time_shares"] == {"role-0": 1}
    assert {(t["from_role"], t["to_role"]) for t in result["selected_solution"]["transitions"]} == {
        ("role-0", "utility"),
        ("utility", "role-0"),
    }


def test_joint_api_returns_the_refined_shared_arrow_for_every_feasible_curve_point(
    client, app, session_factory
):
    items, roles = ammunition_case()
    app.state.gear_service._equipment = EquipmentCatalog(
        {item.id: item for item in items}, revision="shared-arrow-api-regression"
    )
    body = scenario(client, session_factory, ids=tuple(item.id for item in items))
    body.update(roles=[role.model_dump(mode="json") for role in roles], max_swaps=4)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    for solution in [
        data["result"]["selected_solution"],
        data["result"]["unrestricted"],
        *(point["solution"] for point in data["result"]["curve"][1:]),
    ]:
        assert solution is not None
        assert {
            loadout["equipment"]["ammunition"] for loadout in solution["loadouts"].values()
        } == {890}
        assert solution["maximum_actions"] == 1
        assert all(a["slot"] != "ammunition" for t in solution["transitions"] for a in t["actions"])
        ammunition_ids = {item.id for item in items if item.slot == "ammunition"}
        assert set(solution["carried_item_ids"]) & ammunition_ids == {890}
        assert solution["purchases"] == []
    assert data["scenario"]["roles"] == body["roles"]
    assert data["result"]["search"]["ammunition_refinement"]["improved_finalists"] > 0


@pytest.mark.parametrize(
    "changes,path",
    [
        ({"base_role": "missing"}, "base_role"),
        ({"transitions": [["role-0", "missing"]]}, "transitions.0.1"),
        ({"transitions": [["role-0", "role-0"]]}, "transitions.0"),
        ({"ordered_roles": ["role-0", "missing"]}, "ordered_roles.1"),
        (
            {"ordered_roles": ["role-0", "role-1"], "transitions": [["role-0", "role-1"]]},
            "transitions",
        ),
        ({"loop": True}, "loop"),
        ({"locks": {"weapon": 999999}}, "locks.weapon"),
        ({"locks": {"head": 4151}}, "locks.head"),
        ({"excluded_item_ids": [4151]}, "roles.0.locks.weapon"),
    ],
)
def test_joint_constraint_errors_identify_fields(client, app, session_factory, changes, path):
    body = {**joint_scenario(client, app, session_factory), **changes}
    if path == "locks.weapon":
        body["roles"] = [{**role, "locks": {}} for role in body["roles"]]
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert path in {e["path"] for e in reply.json()["error"]["fields"]}


@pytest.mark.parametrize(
    "changes,path",
    [
        ({"id": "role-0"}, "roles.1.id"),
        ({"style": "ranged", "stance": "aggressive"}, "roles.1.stance"),
        ({"style": "magic", "spell": "invented"}, "roles.1.spell"),
        ({"style": "magic", "spell": []}, "roles.1.spell"),
        ({"style": "ranged", "stance": []}, "roles.1.stance"),
        ({"target": {"unsupported_mechanics": ["prayer"]}}, "roles.1.target.unsupported_mechanics"),
        ({"parent_role": "missing"}, "roles.1.parent_role"),
        ({"style": "special"}, "roles.1.parent_role"),
        ({"locks": {"head": 4151}}, "roles.1.locks.head"),
        ({"locks": {"weapon": 999999}}, "roles.1.locks.weapon"),
        ({"target": {"defence_level": True}}, "roles.1.target.defence_level"),
    ],
)
def test_every_role_is_validated_with_its_field_path(client, app, session_factory, changes, path):
    body = joint_scenario(client, app, session_factory)
    body["roles"][1] = {**body["roles"][1], **changes}
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 422, reply.text
    assert path in {e["path"] for e in reply.json()["error"]["fields"]}


def test_repeated_looping_phases_use_only_backend_directed_edges(client, app, session_factory):
    body = joint_scenario(client, app, session_factory, 3)
    body.update(ordered_roles=["role-0", "role-1", "role-0", "role-2"], loop=True)
    reply = client.post("/ui-api/gear/optimizations", json=body)
    assert reply.status_code == 200, reply.text
    transitions = reply.json()["result"]["selected_solution"]["transitions"]
    assert [(t["from_role"], t["to_role"]) for t in transitions] == [
        ("role-0", "role-1"),
        ("role-1", "role-0"),
        ("role-0", "role-2"),
        ("role-2", "role-0"),
    ]


def test_manual_evaluation_stays_single_role(client, app, session_factory):
    body = joint_scenario(client, app, session_factory)
    reply = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"role-0": {"weapon": 4151}},
            "proposed_loadouts": {"role-0": {"weapon": 4151}},
        },
    )
    assert reply.status_code == 422, reply.text
    assert "one ordinary" in reply.text.lower()


def test_joint_directed_actions_inventory_and_curve_are_exact(client, app, session_factory):
    body = scenario(client, session_factory, ids=(4151, 12954, 861, 882))
    catalog = app.state.gear_service.equipment_catalog()
    app.state.gear_service._equipment = EquipmentCatalog(
        {
            i: catalog.items[i].model_copy(update={"requires": None, "requirements_complete": True})
            for i in (4151, 12954, 861, 882)
        },
        revision="joint-directed-test",
    )
    body.update(
        roles=[
            {
                "id": "melee",
                "style": "slash",
                "locks": {"weapon": 4151, "shield": 12954, "ammunition": None},
            },
            {
                "id": "bow",
                "style": "ranged",
                "stance": "rapid",
                "locks": {"weapon": 861, "shield": None, "ammunition": 882},
            },
        ],
        base_role="melee",
        max_swaps=3,
        reserved_supply_slots=26,
        transitions=[["melee", "bow"], ["bow", "melee"]],
    )
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    solution = result["selected_solution"]
    assert solution is not None
    forward, reverse = solution["transitions"]
    assert forward["changed_slots"] == reverse["changed_slots"] == 3
    assert forward["action_count"] == 2 and reverse["action_count"] == 3
    assert any(a["automatically_removed"] == [4151, 12954] for a in forward["actions"])
    assert solution["distinct_items"] == 4
    assert solution["gear_inventory_slots"] == solution["max_gear_inventory_slots"] == 2
    assert solution["reserved_supply_slots"] == solution["remaining_supply_slots"] == 26
    assert solution["remaining_inventory_slots"] == 0
    assert result["curve"][2]["solution"] is None
    assert result["curve"][3]["solution"] == solution == result["unrestricted"]
    for transition in solution["transitions"]:
        assert max(a["gear_inventory_slots"] for a in transition["actions"]) <= 2
    body.update(transitions=[["melee", "bow"]], max_swaps=2)
    directed = client.post("/ui-api/gear/optimizations", json=body).json()["result"]
    assert directed["selected_solution"]["maximum_actions"] == 2
    body["reserved_supply_slots"] = 27
    full = client.post("/ui-api/gear/optimizations", json=body).json()["result"]
    assert full["selected_solution"] is None and full["unrestricted"] is None


def test_joint_shared_purchase_union_and_budget_use_one_frozen_price(client, app, session_factory):
    body = scenario(client, session_factory, ids=())
    catalog = app.state.gear_service.equipment_catalog()
    app.state.gear_service._equipment = EquipmentCatalog(
        {4151: catalog.items[4151]}, revision="joint-price-test"
    )
    now = datetime.now(UTC)
    with session_factory() as session:
        session.merge(
            ItemPrice(
                item_id=4151,
                high_price_gp=500,
                high_trade_at=now,
                fetched_at=now,
                source=PriceSourceLayer.CACHED,
                provider="joint-frozen-test",
            )
        )
        session.commit()
    body.update(
        roles=[
            {"id": key, "style": "slash", "locks": {"weapon": 4151}} for key in ("a", "b", "c", "d")
        ],
        mode="usable",
        budget_gp=500,
    )
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["result"]["selected_solution"]["purchases"] == [
        {"item_id": 4151, "cost_gp": 500, "conditional": False}
    ]
    assert data["result"]["selected_solution"]["purchase_cost_gp"] == 500
    assert data["items"][0]["price"]["provider"] == "joint-frozen-test"
    body["budget_gp"] = 499
    assert (
        client.post("/ui-api/gear/optimizations", json=body).json()["result"]["selected_solution"]
        is None
    )


def test_magic_level_checked_for_later_roles(client, app, session_factory):
    body = joint_scenario(client, app, session_factory)
    body.update(mode="future", skill_overrides={"magic": 1})
    body["roles"][1].update(style="magic", spell="fire_strike")
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["path"] == "roles.1.spell"


@pytest.mark.parametrize(
    "changes,path",
    [
        (
            {
                "roles": [
                    {"id": "a", "style": "special", "parent_role": "b"},
                    {"id": "b", "style": "slash"},
                ]
            },
            "roles.0.locks.weapon",
        ),
        ({"roles": [{"id": "a", "style": "slash", "weight": 0}]}, "roles"),
        (
            {
                "roles": [{"id": "a", "style": "slash", "locks": {"weapon": 1}}],
                "locks": {"weapon": 2},
            },
            "roles.0.locks.weapon",
        ),
        ({"locks": {"weapon": 1}, "excluded_item_ids": [1]}, "locks.weapon"),
        ({"transitions": [["a", "b"]] * 17}, "transitions"),
        ({"ordered_roles": ["a"] * 101}, "ordered_roles"),
        ({"mode": "future", "skill_overrides": {"attack": 1.5}}, "skill_overrides.attack"),
        (
            {"roles": [{"id": "a", "style": "magic", "target": {"ranged_light": -65}}]},
            "roles.0.target.ranged_light",
        ),
        (
            {"roles": [{"id": "a", "style": "magic", "target": {"bonuses": {"magic": True}}}]},
            "roles.0.target.bonuses.magic",
        ),
    ],
)
def test_browser_cross_field_validation_has_editable_locations(changes, path):
    from pydantic import ValidationError

    from tracker.api.gear_optimizations import BrowserOptimizationRequest

    body = {
        "roles": [{"id": "a", "style": "slash"}, {"id": "b", "style": "slash"}],
        "expected_snapshot_id": "test",
        **changes,
    }
    with pytest.raises(ValidationError) as caught:
        BrowserOptimizationRequest.model_validate(body)
    assert path in {".".join(str(v) for v in e["loc"]) for e in caught.value.errors()}


@pytest.mark.parametrize(
    "body", [None, [], {"roles": {}}, {"roles": [None]}, {"roles": [{"id": [], "style": []}]}]
)
def test_malformed_joint_shapes_never_raise_unstructured_errors(body):
    from pydantic import ValidationError

    from tracker.api.gear_optimizations import BrowserOptimizationRequest

    with pytest.raises(ValidationError):
        BrowserOptimizationRequest.model_validate(body)
