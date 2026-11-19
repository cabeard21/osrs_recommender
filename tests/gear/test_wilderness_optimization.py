"""Wilderness budgets constrain the loss of a complete carried set."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.integrations.prices.client import PriceDTO, PriceSource


def scenario(*, owned=(), prayer=25):
    items = {
        item.id: item
        for item in (
            weapon(4151, "slash", 82, tradeable=True),
            weapon(4587, "slash", 66, tradeable=True),
        )
    }
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            skill: SkillState(level, None, Source.MANUAL, NOW)
            for skill, level in {"attack": 70, "strength": 70, "prayer": prayer}.items()
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in owned
        },
    )
    prices = {
        i: PriceDTO(
            item_id=i,
            high_price_gp=amount,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source=PriceSource.LIVE,
            provider="test",
        )
        for i, amount in {4151: 1_000_000, 4587: 60_000}.items()
    }
    return snapshot, SimpleNamespace(items=items, version="test"), prices


def request_for(*, skulled, protect_item, budget=0, risk_limit=None, roles=None):
    return OptimizationRequest(
        roles=roles or (RoleConfig(id="melee", style="slash", locks={"weapon": 4151}),),
        budget_gp=budget,
        max_swaps=2,
        wilderness={
            "depth": "level_21_plus",
            "skulled": skulled,
            "protect_item": protect_item,
            **({"max_loss_gp": risk_limit} if risk_limit is not None else {}),
        },
    )


@pytest.mark.parametrize("compact", [False, True])
def test_protected_purchase_over_cap_is_feasible_in_search_and_fixed_evaluation(
    make_content, compact
):
    snapshot, catalog, prices = scenario()
    request = request_for(skulled=True, protect_item=True)
    content = make_content()
    result = optimize(
        snapshot,
        request,
        catalog,
        content,
        prices,
        NOW,
        _execution_profile="combined" if compact else "baseline",
        _factored_evaluation=compact,
        _compact_states=compact,
    )
    solution = result["selected_solution"]
    assert solution["purchase_cost_gp"] == 1_000_000
    assert solution["wilderness_risk"]["loss_gp"] == 0
    assert solution["wilderness_risk"]["without_protect_item_gp"] == 1_000_000

    equipment = {"weapon": 4151}
    comparison = evaluate_configurations(
        snapshot, request, equipment, equipment, catalog, content, prices, NOW
    )
    assert comparison["proposed"]["status"] == "valid"
    assert comparison["proposed"]["wilderness_risk"] == solution["wilderness_risk"]


def test_shared_switches_compete_for_protection_even_when_owned(make_content):
    snapshot, catalog, prices = scenario(owned=(4151, 4587))
    roles = tuple(
        RoleConfig(id=f"role{i}", style="slash", locks={"weapon": item})
        for i, item in enumerate((4151, 4587))
    )
    content = make_content()
    request = request_for(skulled=True, protect_item=True, budget=59_999, roles=roles)
    assert optimize(snapshot, request, catalog, content, prices, NOW)["unrestricted"] is None
    exact = request.model_copy(update={"budget_gp": 60_000})
    solution = optimize(snapshot, exact, catalog, content, prices, NOW)["unrestricted"]
    assert solution["purchase_cost_gp"] == 0
    assert solution["wilderness_risk"]["loss_gp"] == 60_000


@pytest.mark.parametrize("compact", [False, True])
def test_purchase_limit_still_applies_when_locked_gear_is_protected(make_content, compact):
    snapshot, catalog, prices = scenario()
    request = request_for(skulled=True, protect_item=True, budget=999_999, risk_limit=0)
    content = make_content()
    options = {
        "_execution_profile": "combined" if compact else "baseline",
        "_factored_evaluation": compact,
        "_compact_states": compact,
    }
    assert request.purchase_budget == 999_999
    assert request.wilderness_risk_limit == 0
    assert (
        optimize(snapshot, request, catalog, content, prices, NOW, **options)["selected_solution"]
        is None
    )

    equipment = {"weapon": 4151}
    fixed = evaluate_configurations(
        snapshot, request, equipment, equipment, catalog, content, prices, NOW
    )["proposed"]
    assert fixed["status"] == "invalid"
    assert fixed["wilderness_risk"]["loss_gp"] == 0
    assert [reason["path"] for reason in fixed["reasons"]] == ["budget_gp"]

    exact = request.model_copy(update={"budget_gp": 1_000_000})
    winner = optimize(snapshot, exact, catalog, content, prices, NOW, **options)[
        "selected_solution"
    ]
    assert winner["purchase_cost_gp"] == 1_000_000
    assert winner["wilderness_risk"]["loss_gp"] == 0


def test_owned_gear_can_exceed_risk_without_exceeding_purchase_limit(make_content):
    snapshot, catalog, prices = scenario(owned=(4151,))
    request = request_for(skulled=True, protect_item=False, budget=0, risk_limit=999_999)
    content = make_content()
    assert optimize(snapshot, request, catalog, content, prices, NOW)["selected_solution"] is None
    equipment = {"weapon": 4151}
    fixed = evaluate_configurations(
        snapshot, request, equipment, equipment, catalog, content, prices, NOW
    )["proposed"]
    assert fixed["status"] == "invalid"
    assert fixed["purchase_cost_gp"] == 0
    assert fixed["wilderness_risk"]["loss_gp"] == 1_000_000
    assert [reason["path"] for reason in fixed["reasons"]] == ["wilderness.max_loss_gp"]


def test_fixed_comparison_reports_each_failed_limit(make_content):
    snapshot, catalog, prices = scenario()
    request = request_for(skulled=True, protect_item=False, budget=999_999, risk_limit=999_999)
    equipment = {"weapon": 4151}
    fixed = evaluate_configurations(
        snapshot, request, equipment, equipment, catalog, make_content(), prices, NOW
    )["proposed"]
    assert [reason["path"] for reason in fixed["reasons"]] == [
        "budget_gp",
        "wilderness.max_loss_gp",
    ]


def test_multi_switches_share_both_caps_at_exact_boundary(make_content):
    snapshot, catalog, prices = scenario()
    roles = tuple(
        RoleConfig(id=f"role{i}", style="slash", locks={"weapon": item})
        for i, item in enumerate((4151, 4587))
    )
    content = make_content()
    request = request_for(
        skulled=True, protect_item=True, budget=1_059_999, risk_limit=60_000, roles=roles
    )
    assert optimize(snapshot, request, catalog, content, prices, NOW)["unrestricted"] is None
    exact = request.model_copy(update={"budget_gp": 1_060_000})
    winner = optimize(snapshot, exact, catalog, content, prices, NOW)["unrestricted"]
    assert winner["purchase_cost_gp"] == 1_060_000
    assert winner["wilderness_risk"]["loss_gp"] == 60_000


def test_protect_item_requires_level_25_prayer(make_content):
    snapshot, catalog, prices = scenario(prayer=24)
    request = request_for(skulled=True, protect_item=True)
    with pytest.raises(ValueError, match="Protect Item requires level 25 Prayer"):
        optimize(snapshot, request, catalog, make_content(), prices, NOW)
