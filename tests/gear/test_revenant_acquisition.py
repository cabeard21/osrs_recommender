from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container
from tracker.gear.evaluation import purchase_cost
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def fact(item_id, *owned, excluded=(), quotes=None):
    snapshot = AccountSnapshot(
        1,
        "test",
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in owned
        },
    )
    return equipment_fact(
        snapshot,
        EquipmentDefinition(id=item_id, name="Weapon", slot="weapon"),
        Content(),
        quotes or {},
        NOW,
        excluded_item_ids=excluded,
    )


@pytest.mark.parametrize(
    "usable,owned,action",
    [
        (22545, 22542, "Activate"),
        (22542, 22545, "Uncharge"),
        (27655, 27652, "Activate"),
        (27788, 22555, "Swap"),
        (27785, 22552, "Swap"),
        (27679, 27662, "Swap"),
    ],
)
def test_account_observes_exact_form_and_plans_reversible_preparation(usable, owned, action):
    row = fact(usable, owned)
    assert row["ownership"]["status"] == "unknown"
    assert row["planning_ownership"]["status"] == "owned"
    prep = row["preparation"]
    assert prep["source_item_id"] == owned
    assert prep["usable_item_id"] == usable
    assert action in prep["message"]
    assert prep["charging_required"] is (usable in {22545, 27655, 27679})
    assert prep["activation_reserve"] == (
        [{"item_id": 21820, "quantity": 1000}] if prep["charging_required"] else []
    )


def test_preparation_skips_excluded_sources_and_prefers_equivalent_charged_mode():
    assert fact(27788, 22555, 27785)["preparation"]["source_item_id"] == 22555
    assert fact(27788, 22555, 27785, excluded=(22555,))["preparation"]["source_item_id"] == 27785
    assert fact(27788, 22555, excluded=(22555,))["planning_ownership"]["status"] != "owned"


def test_charged_observation_and_sibling_tier_are_distinct():
    row = fact(22545, 22545)
    assert row["preparation"]["charges"] == "unknown"
    assert not row["preparation"]["charging_required"]
    assert row["preparation"]["activation_reserve"] == []
    assert fact(27660, 22545)["planning_ownership"]["status"] != "owned"


def test_two_ready_modes_need_two_physical_copies_before_a_trip():
    record = SimpleNamespace(
        high_price_gp=42,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source="live",
    )
    facts = {i: fact(i, quotes={27662: record}) for i in (27665, 27679)}
    assert all(row["preparation"]["market_item_id"] == 27662 for row in facts.values())
    request = SimpleNamespace(mode="usable", assumed_item_ids=(), include_untradeables=False)
    assert purchase_cost(set(facts), facts, request) == 84
    from tracker.gear.evaluation import purchases

    assert purchases(set(facts), facts, request)[0]["quantity"] == 2


def test_buy_from_cheapest_available_uncharged_sceptre_setting():
    def price(gp):
        return SimpleNamespace(
            high_price_gp=gp,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )

    prices = {22552: price(100), 27785: price(60)}
    assert fact(22555, quotes=prices)["preparation"]["market_item_id"] == 27785
    assert fact(27788, quotes=prices, excluded=(27785,))["preparation"]["market_item_id"] == 22552
    assert fact(27788, quotes={27785: price(60)})["price"]["amount_gp"] == 60


@pytest.mark.parametrize("item_id", [22542, 22547, 22552, 27785, 27657, 27652, 27662, 27676])
def test_revenant_weapon_lock_keeps_requested_physical_form(item_id):
    req = OptimizationRequest(
        roles=(RoleConfig(id="role", style="magic"),), locks={"weapon": item_id}
    )
    assert req.prepared_weapon_locks().locks["weapon"] == item_id


def test_legacy_role_keeps_uncharged_and_charged_cost_choices_under_small_slot_cap(monkeypatch):
    from tracker.content.loader import load_content
    from tracker.domain.types import SkillState, Source
    from tracker.gear import optimizer
    from tracker.gear.catalog import load_catalog

    content = load_content()
    catalog = load_catalog(content)
    items = {i: catalog.items[i] for i in (22542, 22545, 27657, 27660)}
    snapshot = AccountSnapshot(
        1,
        "cost tradeoffs",
        skills={k: SkillState(85, None, Source.MANUAL, NOW) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW)
            for i in (22542, 27657)
        },
    )
    req = OptimizationRequest.model_validate(
        {
            "roles": [{"id": "mace", "style": "crush"}],
            "mode": "owned",
            "objectives": [{"kind": "gp_per_damage"}],
        }
    )
    facts = {i: equipment_fact(snapshot, item, content, {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    pool = optimizer._Search(snapshot, req, items, facts, None).candidate_pools()
    assert items.keys() <= set(pool["weapon"])


@pytest.mark.parametrize(
    "mode,quantity,expected_cost",
    [
        ("owned", 1, None),
        ("owned", 2, 0),
        ("usable", 1, 50),
        ("usable", 0, 100),
    ],
)
def test_locked_joint_trip_allocates_one_copy_per_ready_state(mode, quantity, expected_cost):
    from tracker.content.loader import load_content
    from tracker.domain.types import SkillState, Source
    from tracker.gear.catalog import EquipmentCatalog, load_catalog
    from tracker.gear.optimizer import optimize

    content = load_content()
    catalog = load_catalog(content)
    empty, charged = 22542, 22545
    gear = EquipmentCatalog({i: catalog.items[i] for i in (empty, charged)})
    snapshot = AccountSnapshot(
        1,
        "joint copy test",
        skills={k: SkillState(85, None, Source.MANUAL, NOW) for k in content.skills},
        observed_items={
            (empty, Container.BANK): ObservedItemFact(empty, Container.BANK, quantity, "test", NOW)
        }
        if quantity
        else {},
    )
    req = OptimizationRequest(
        roles=tuple(
            RoleConfig(id=str(i), style="crush", locks={"weapon": i}) for i in (empty, charged)
        ),
        mode=mode,
        max_swaps=1,
        budget_gp=100,
    )
    record = SimpleNamespace(
        high_price_gp=50,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source="live",
    )
    result = optimize(snapshot, req, gear, content, {empty: record}, NOW, local_refinement=False)
    selected = result["selected_solution"]
    if expected_cost is None:
        assert selected is None
        return
    assert selected["purchase_cost_gp"] == expected_cost
    assert selected["distinct_items"] == 2
    assert selected["maximum_actions"] == 1
    assert selected["loadouts"][str(charged)]["preparations"][0]["source_item_id"] == (
        empty if quantity == 2 else None
    )
    assert [row.get("quantity", 1) for row in selected["purchases"]] == (
        [2 - quantity] if quantity < 2 else []
    )
