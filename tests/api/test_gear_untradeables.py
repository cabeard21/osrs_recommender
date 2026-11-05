"""Untradeable what-if upgrades stay separate from observed ownership and GE buys."""

import pytest

from tests.api.test_gear_optimizations import scenario
from tracker.accounts.service import AccountService
from tracker.content.loader import Content
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.service import GearService


@pytest.fixture
def untradeable_context(client, session_factory, monkeypatch):
    body = {**scenario(client, session_factory, ids=(1,)), "mode": "usable"}
    snapshot = AccountService(session_factory).get_snapshot(1)
    gear = GearService(Content())
    gear._equipment = EquipmentCatalog(
        {
            1: EquipmentDefinition(
                id=1,
                name="Owned blade",
                slot="weapon",
                attack_styles=("slash",),
                requirements_complete=True,
                tradeable=True,
            ),
            2: EquipmentDefinition(
                id=2,
                name="Earned cape",
                slot="cape",
                requirements_complete=True,
                tradeable=False,
                bonuses=EquipmentBonuses(melee_strength=40),
            ),
        },
        revision="untradeable-test",
    )
    for module in ("gear_optimizations", "gear_evaluations"):
        monkeypatch.setattr(f"tracker.api.{module}.resources", lambda _: (snapshot, gear, {}))
    return body


def test_untradeable_toggle_uses_normal_optimizer_without_ge_cost(client, untradeable_context):
    body = untradeable_context
    disabled = client.post("/ui-api/gear/optimizations", json=body)
    enabled = client.post("/ui-api/gear/optimizations", json={**body, "include_untradeables": True})
    assert disabled.status_code == enabled.status_code == 200, enabled.text
    first, second = disabled.json(), enabled.json()
    selected = second["result"]["selected_solution"]
    assert selected["unowned_untradeable_item_ids"] == [2]
    assert selected["purchases"] == []
    assert selected["purchase_cost_gp"] == 0
    assert first["result"]["selected_solution"]["unowned_untradeable_item_ids"] == []
    assert first["scenario_fingerprint"] != second["scenario_fingerprint"]
    assert first["result"]["assumptions_fingerprint"] != second["result"]["assumptions_fingerprint"]
    cape = next(i for i in second["items"] if i["item_id"] == 2)
    assert cape["ownership"]["status"] == "unowned"


def test_fixed_untradeable_trial_is_labeled_and_requires_toggle(client, untradeable_context):
    request = {
        "scenario": untradeable_context,
        "baseline_loadouts": {"single": {"weapon": 1}},
        "proposed_loadouts": {"single": {"weapon": 1, "cape": 2}},
    }
    disabled = client.post("/ui-api/gear/evaluations", json=request)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["proposed"]["status"] == "invalid"
    request["scenario"] = {**untradeable_context, "include_untradeables": True}
    enabled = client.post("/ui-api/gear/evaluations", json=request)
    assert enabled.status_code == 200, enabled.text
    result = enabled.json()
    assert result["proposed"]["status"] == "valid"
    assert result["proposed"]["unowned_untradeable_item_ids"] == [2]
    assert result["proposed"]["purchases"] == []
    assert result["deltas"]["purchase_cost_gp"] == 0


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_untradeable_toggle_is_strict_boolean(client, untradeable_context, value):
    reply = client.post(
        "/ui-api/gear/optimizations",
        json={
            **untradeable_context,
            "include_untradeables": value,
        },
    )
    assert reply.status_code == 422
