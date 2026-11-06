from types import SimpleNamespace

from tracker.gear.evaluation import item_problems, purchase_cost, purchases


def test_prepared_ownership_qualifies_without_changing_observed_fact():
    fact = {
        "ownership": {"status": "unowned"},
        "planning_ownership": {"status": "owned"},
        "wear": {"status": "satisfied"},
    }
    request = SimpleNamespace(excluded_item_ids=(), mode="owned", assumed_item_ids=())
    assert item_problems(1, fact, request) == ()
    assert fact["ownership"]["status"] == "unowned"


def test_same_market_weapon_purchase_is_deduplicated():
    fact = {
        "ownership": {"status": "unowned"},
        "price": {"amount_gp": 100},
        "acquisition": "tradeable",
        "preparation": {"market_item_id": 3},
    }
    request = SimpleNamespace(mode="usable", assumed_item_ids=(), include_untradeables=False)
    facts = {1: fact, 2: fact}
    assert purchase_cost({1, 2}, facts, request) == 100
    assert purchases({1, 2}, facts, request) == [
        {"item_id": 3, "cost_gp": 100, "conditional": False}
    ]


def test_full_catalog_powered_search_selects_shadow_with_magic_gear(monkeypatch):
    from datetime import UTC, datetime

    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import load_content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.catalog import load_catalog
    from tracker.gear.optimizer import (
        CombatOptionFilters,
        OptimizationRequest,
        RoleConfig,
        optimize,
    )

    monkeypatch.setattr("tracker.gear.optimizer.CANDIDATES_PER_SLOT", 2)
    at = datetime(2026, 11, 5, tzinfo=UTC)
    content = load_content()
    catalog = load_catalog(content)
    owned = (27277, 31115, 11908, 28583, 21018, 21021, 21024, 12002, 19544, 13235)
    snapshot = AccountSnapshot(
        1,
        "powered-replay",
        skills={k: SkillState(99, None, Source.MANUAL, at) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "fixture", at)
            for i in owned
        },
    )
    role = RoleConfig(
        id="magic",
        style="magic",
        combat_options=CombatOptionFilters(
            attack_types=("magic",),
            stances=("accurate",),
            spells=("powered:27275", "powered:31113", "powered:11907", "powered:28585"),
        ),
    )
    result = optimize(
        snapshot,
        OptimizationRequest(roles=(role,), mode="owned", max_swaps=0),
        catalog,
        content,
        {},
        at,
        local_refinement=False,
    )
    loadout = result["selected_solution"]["loadouts"]["magic"]
    assert loadout["equipment"]["weapon"] == 27275
    assert loadout["equipment"]["body"] == 21021
    assert loadout["combat_option"]["powered_attack"] == "shadow"
    assert loadout["preparations"][0]["charging_required"]
    assert result["selected_solution"]["purchase_cost_gp"] == 0
