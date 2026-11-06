from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import load_catalog
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize


def request(*, global_lock=False, spells=("powered:28583",), excluded=(), mode="usable"):
    return OptimizationRequest(
        roles=(
            RoleConfig(
                id="magic",
                style="magic",
                locks={} if global_lock else {"weapon": 28583},
                combat_options=CombatOptionFilters(
                    attack_types=("magic",), stances=("accurate",), spells=spells
                ),
            ),
        ),
        locks={"weapon": 28583} if global_lock else {},
        mode=mode,
        budget_gp=1_000_000_000,
        max_swaps=0,
        excluded_item_ids=excluded,
    )


@pytest.mark.parametrize("global_lock", [False, True])
def test_uncharged_lock_projects_same_edition_and_explicit_attack(global_lock):
    submitted = request(global_lock=global_lock)
    before = submitted.model_dump(mode="json")
    result = submitted.prepared_weapon_locks()
    locks = result.locks if global_lock else result.roles[0].locks
    assert locks["weapon"] == 28585
    assert result.roles[0].combat_options.spells == ("powered:28585",)
    assert submitted.model_dump(mode="json") == before
    assert submitted.roles[0].combat_options.spells == ("powered:28583",)


@pytest.mark.parametrize("spells", [(), ("fire_strike",)])
def test_preparation_does_not_enable_an_excluded_attack(spells):
    assert request(spells=spells).prepared_weapon_locks().roles[0].combat_options.spells == spells


@pytest.mark.parametrize("excluded", [(28583,), (28585,)])
def test_neither_source_nor_usable_exclusion_can_be_bypassed(excluded):
    with pytest.raises(ValueError, match="excluded"):
        request(excluded=excluded).prepared_weapon_locks()


@pytest.mark.parametrize("owned", [False, True])
def test_warped_lock_is_feasible_with_market_price_or_owned_uncharged(owned):
    at = datetime(2026, 11, 6, tzinfo=UTC)
    content = load_content()
    catalog = load_catalog(content)
    seen = ObservedItemFact(28583, Container.BANK, 1, "fixture", at)
    snapshot = AccountSnapshot(
        1,
        "warped-lock",
        skills={k: SkillState(65, None, Source.MANUAL, at) for k in content.skills},
        observed_items={(28583, Container.BANK): seen} if owned else {},
    )
    price = SimpleNamespace(
        high_price_gp=92542,
        low_price_gp=88603,
        high_trade_at=at,
        low_trade_at=at,
        fetched_at=at,
        source="cached",
    )
    result = optimize(
        snapshot,
        request(mode="owned" if owned else "usable"),
        catalog,
        content,
        {28583: price} if not owned else {},
        at,
        local_refinement=False,
    )
    selected = result["selected_solution"]
    assert selected is not None
    loadout = selected["loadouts"]["magic"]
    assert loadout["equipment"]["weapon"] == 28585
    assert loadout["combat_option"]["powered_attack"] == "warped"
    assert loadout["preparations"][0]["market_item_id"] == 28583
    assert loadout["preparations"][0]["charging_required"]
    if owned:
        assert selected["purchase_cost_gp"] == 0
    else:
        purchase = next(p for p in selected["purchases"] if p["item_id"] == 28583)
        assert purchase["cost_gp"] == 92542
        assert 28583 in {item["item_id"] for item in result["items"]}
        zero_budget = optimize(
            snapshot,
            request().model_copy(update={"budget_gp": 0, "include_untradeables": True}),
            catalog,
            content,
            {28583: price},
            at,
            local_refinement=False,
        )
        assert zero_budget["selected_solution"] is None


def test_fixed_prepared_result_respects_original_lock_without_mutating_scenario():
    from tracker.gear.evaluation import evaluate_configurations

    at = datetime(2026, 11, 6, tzinfo=UTC)
    content = load_content()
    seen = ObservedItemFact(28583, Container.BANK, 1, "fixture", at)
    snapshot = AccountSnapshot(
        1,
        "fixed-preparation",
        skills={k: SkillState(65, None, Source.MANUAL, at) for k in content.skills},
        observed_items={(28583, Container.BANK): seen},
    )
    submitted = request(mode="owned")
    original = submitted.model_dump(mode="json")
    selected = {
        "attack_type": "magic",
        "stance": "accurate",
        "spell": None,
        "powered_attack": "warped",
    }
    result = evaluate_configurations(
        snapshot,
        submitted,
        {"weapon": 28585},
        {"weapon": 28585},
        load_catalog(content),
        content,
        {},
        at,
        baseline_combat_option=selected,
        proposed_combat_option=selected,
    )
    assert result["baseline"]["status"] == "valid"
    assert result["proposed"]["status"] == "valid"
    assert submitted.model_dump(mode="json") == original
