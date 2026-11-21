"""Complete desktop Gear results for priced and unpriced joint combat options."""

from dataclasses import replace

import pytest

from tools.benchmark_gear_desktop import without_observations
from tools.gear_search_quality_fixture import load_case
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.models import TargetSelection
from tracker.gear.npcs import npc_catalog
from tracker.gear.objective_store import close_result_archives
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig
from tracker.gear.parallel import AutoProcessPool
from tracker.gear.service import GearService
from tracker.integrations.prices.client import PriceDTO, PriceSource


@pytest.fixture(scope="module")
def trek():
    case = load_case("melee_1m")
    content = load_content()
    full = load_catalog(content)
    # Silver bolts make every feasible ranged attack on the Juvinate cost GP.
    amounts = {9185: 10000, 9145: 80, 4151: 100000, 4587: 60000, 1725: 1000, 1718: 2000}
    catalog = EquipmentCatalog({i: full.items[i] for i in amounts}, revision=full.revision)
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests=dict.fromkeys(content.quests, QuestStatus.COMPLETE),
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "fixture", case.at)
            for i in amounts
        },
    )
    prices = {
        i: PriceDTO(
            item_id=i,
            high_price_gp=amount,
            high_trade_at=case.at,
            low_price_gp=amount,
            low_trade_at=case.at,
            provider="fixture",
            fetched_at=case.at,
            source=PriceSource.LIVE,
        )
        for i, amount in amounts.items()
    }
    return snapshot, content, catalog, prices, case.at


def target(npc_id):
    catalog = npc_catalog()
    key = next(key for key, row in catalog.entries.items() if row["npc_id"] == npc_id)
    return TargetSelection(key=key, catalog_revision=catalog.revision)


def trek_request(*, four_roles=False, potions=False):
    juvinate = RoleConfig(
        id="juvinate",
        style="ranged",
        stance="rapid",
        locks={"weapon": 9185, "ammunition": 9145},
        target_selection=target(5635),
        safe_spotting=True,
        weight=0.25 if four_roles else 1,
        combat_options=CombatOptionFilters(
            attack_types=("heavy",), stances=("accurate", "rapid"), spells=()
        ),
    )
    beast = RoleConfig(
        id="nail_beast",
        style="slash",
        locks={"weapon": 4151},
        target_selection=target(2948),
        weight=1.5 if four_roles else 1,
        combat_options=CombatOptionFilters(
            attack_types=("slash",), stances=("accurate", "controlled"), spells=()
        ),
    )
    roles = (juvinate, beast)
    objectives = [{"kind": "gp_per_damage"}, {"kind": "prayer_bonus"}]
    if four_roles:
        roles += (
            RoleConfig(id="standby", style="slash", weight=0, locks={"weapon": 4587}),
            RoleConfig(id="special", style="special", parent_role=beast.id, locks={"weapon": 4587}),
        )
        objectives += [
            {"kind": "defence_roll", "styles": ["stab", "magic"], "aggregation": "minimum"},
            {"kind": "wilderness_loss_gp"},
        ]
    return OptimizationRequest(
        mode="owned",
        roles=roles,
        objectives=objectives,
        max_swaps=3 if four_roles else 8,
        max_dps_loss_pct=100,
        potions={"mode": "optimize", "allowed_ids": ["super_strength"]}
        if potions
        else {"mode": "disabled"},
        wilderness={"skulled": True, "attacks_per_setup": 10} if four_roles else None,
    )


def desktop_result(trek, request, prices, *, native, pool=None):
    snapshot, content, catalog, _, at = trek
    service = GearService(
        content,
        auto_pool=pool,
        optimization_profile="combined",
        fixed_reporting=True,
        factored_evaluation=True,
        compact_states=True,
        native_search=native,
        native_required=native,
    )
    service._equipment = catalog
    result = service.optimize(snapshot, request, price_records=prices, now=at)
    try:
        # Materialize every rich report and point ID while its archive is still open.
        return without_observations(result), service.native_diagnostics
    finally:
        close_result_archives(result)


def assert_screened(evidence, roles, search):
    assert evidence["fallback_requests"] == 0
    assert evidence["native_requests"] > 0
    batches = [event for event in evidence["events"] if event["event"] == "vector_option_batch"]
    assert batches
    profiles = search.get("potion_selection", {}).get("profiles")
    branches = [profile["search"] for profile in profiles] if profiles else [search]
    assert sorted(batch["screened"] for batch in batches) == sorted(
        branch["objective_frontier"]["option_attempts"] for branch in branches
    )
    for batch in batches:
        assert tuple(batch["roles"]) == tuple(role.style for role in roles)
        assert batch["screened"] == batch["attempts"] > 0


@pytest.mark.parametrize("priced", [True, False])
def test_trekking_complete_frontiers_and_unpriced_baselines(trek, priced):
    pytest.importorskip("tracker.gear.native._frontier")
    request = trek_request()
    prices = trek[3] if priced else {}
    reference, _ = desktop_result(trek, request, prices, native=False)
    actual, evidence = desktop_result(trek, request, prices, native=True)
    assert actual == reference
    assert actual["selected_solution"] and actual["unrestricted"]
    groups = actual["objective_frontiers"]
    assert [g["swap_limit"] for g in groups] == [*range(request.max_swaps + 1), None]
    assert all(not g["sampled"] for g in groups)
    assert not groups[0]["points"] and groups[0]["baseline_solution"] is None
    assert all(g["baseline_solution"] for g in groups[1:])
    assert all(len(g["points"]) == (2 if priced else 0) for g in groups[1:])
    assert groups[-1]["baseline_solution"] == actual["unrestricted"]
    assert_screened(evidence, request.roles, actual["search"])


@pytest.mark.parametrize("spawned", [False, True], ids=["serial", "spawned-potion-branches"])
def test_four_roles_share_weighted_cost_and_wilderness_loss(trek, spawned):
    pytest.importorskip("tracker.gear.native._frontier")
    request = trek_request(four_roles=True, potions=spawned)
    reference, _ = desktop_result(trek, request, trek[3], native=False)
    if spawned:
        pool = AutoProcessPool(2)
        try:
            pool.start(trek[1], trek[2], native_required=True)
            actual, evidence = desktop_result(trek, request, trek[3], native=True, pool=pool)
        finally:
            pool.close()
        assert actual["search"]["potion_selection"]["branch_count"] == 2
    else:
        actual, evidence = desktop_result(trek, request, trek[3], native=True)
    assert actual == reference
    assert all(not g["sampled"] for g in actual["objective_frontiers"])
    group = actual["objective_frontiers"][-1]
    assert group["points"]
    for point in group["points"]:
        solution = point["solution"]
        assert set(solution["loadouts"]) == {role.id for role in request.roles}
        loss = solution["objective_values"]["wilderness_loss_gp"]
        assert loss == solution["wilderness_risk"]["loss_gp"] > 0
    assert_screened(evidence, request.roles, actual["search"])
