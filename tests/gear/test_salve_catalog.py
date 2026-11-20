"""Exact Salve forms, non-GE acquisition and contextual candidate retention."""

from dataclasses import replace

import pytest

from tests.gear.test_optimizer import run, weapon
from tests.gear.test_untradeable_upgrades import NOW, context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, QuestStatus
from tracker.gear.catalog import load_catalog
from tracker.gear.evaluation import item_problems, purchases, unowned_untradeables
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search


@pytest.fixture(scope="module")
def items():
    return load_catalog(Content()).items


@pytest.mark.parametrize(
    "item_id,kind,route",
    [
        (4081, 1, "Haunted Mine"),
        (10588, 2, "Tarn’s diary"),
        (12017, 3, "Nightmare Zone"),
        (25250, 3, "Soul Wars"),
        (26763, 3, "Emir’s Arena"),
        (12018, 4, "Nightmare Zone"),
        (25278, 4, "Soul Wars"),
        (26782, 4, "Emir’s Arena"),
    ],
)
def test_reviewed_salve_forms(items, item_id, kind, route):
    from tracker.gear.salve import acquisition_description

    item = items[item_id]
    assert item.salve_bonus == kind
    assert item.requirements_complete and item.requires.to_yaml() == {"members": True}
    assert item.tradeable is False and not item.unsupported_effects
    assert route in acquisition_description(item.id)
    assert ("Tarn’s diary" in acquisition_description(item.id)) == (kind in {2, 4})


def test_review_checks_identity_and_only_clears_generic_blocker():
    from tracker.gear.salve import apply_review

    row = {
        "id": 4081,
        "name": "Salve amulet",
        "slot": "neck",
        "unsupported_effects": ["Offensive effects have not been validated.", "Unknown"],
    }
    assert apply_review(row)["unsupported_effects"] == ["Unknown"]
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "slot": "head"})
    other = {"id": 1}
    assert apply_review(other) is other


def test_exact_ownership_and_acquisition_requirements(items):
    snapshot, _, content = context()
    owned = 25250
    snapshot = replace(
        snapshot,
        members=True,
        observed_items={
            (owned, Container.BANK): ObservedItemFact(owned, Container.BANK, 1, "test", NOW)
        },
    )
    role = RoleConfig(id="melee", style="crush")
    request = OptimizationRequest(roles=(role,), include_untradeables=True)

    def facts(account):
        return {
            i: equipment_fact(account, items[i], content, {}, NOW) for i in (owned, 12017, 12018)
        }

    unknown = facts(snapshot)
    assert not item_problems(owned, unknown[owned], request.model_copy(update={"mode": "owned"}))
    assert unknown[12017]["planning_ownership"]["status"] == "unowned"
    assert item_problems(12017, unknown[12017], request)
    quested = facts(replace(snapshot, quests={"haunted_mine": QuestStatus.COMPLETE}))
    assert not item_problems(12017, quested[12017], request)
    assert item_problems(12018, quested[12018], request)
    assert item_problems(12017, quested[12017], request.model_copy(update={"mode": "owned"}))
    assert unowned_untradeables({owned, 12017}, quested, request) == [12017]
    assert not purchases({owned, 12017}, quested, request)
    both = facts(
        replace(
            snapshot,
            quests=dict.fromkeys(("haunted_mine", "lair_of_tarn_razorlor"), QuestStatus.COMPLETE),
        )
    )
    assert not item_problems(12018, both[12018], request)
    assert item_problems(
        12018, both[12018], request.model_copy(update={"excluded_item_ids": (12018,)})
    )


def test_undead_candidate_pool_keeps_eligible_physical_necks(items, monkeypatch):
    snapshot, _, content = context()
    snapshot = replace(
        snapshot,
        members=True,
        quests=dict.fromkeys(("haunted_mine", "lair_of_tarn_razorlor"), QuestStatus.COMPLETE),
    )
    salves = {i: item for i, item in items.items() if item.name.startswith("Salve amulet")}
    all_items = {**salves, 1: weapon(1, "slash")}
    request = OptimizationRequest(
        roles=(RoleConfig(id="undead", style="slash", target=CombatTarget(traits=("undead",))),),
        include_untradeables=True,
        excluded_item_ids=(25278,),
    )
    facts = {i: equipment_fact(snapshot, item, content, {}, NOW) for i, item in all_items.items()}
    monkeypatch.setattr("tracker.gear.optimizer.CANDIDATES_PER_SLOT", 2)
    search = _Search(snapshot, request, all_items, facts, None)
    assert set(search.candidate_pools()["neck"]) == {None, *set(salves) - {25278}}


@pytest.mark.parametrize("locked,branches", [(29305, 2), (17, 1), (None, 2)])
def test_strength_potion_search_depends_on_eligible_spear_and_weapon_lock(locked, branches):
    role = RoleConfig(id="ranged", style="ranged", locks={"weapon": locked} if locked else {})
    result = run(
        [weapon(29305, "ranged", 48), weapon(17, "ranged", 15)],
        (role,),
        max_swaps=0,
        potions={"mode": "optimize", "allowed_ids": ("super_strength",)},
    )
    assert result["search"]["potion_selection"]["branch_count"] == branches


def test_frontier_pools_preserve_salve_after_second_truncation(items):
    from types import SimpleNamespace

    from tracker.gear.frontier import _metric_pools
    from tracker.gear.vector_search import VectorSearch

    snapshot, _, content = context()
    snapshot = replace(
        snapshot,
        members=True,
        quests=dict.fromkeys(("haunted_mine", "lair_of_tarn_razorlor"), QuestStatus.COMPLETE),
    )
    salves = {i: it for i, it in items.items() if it.name.startswith("Salve amulet")}
    filler = {
        i: items[4081].model_copy(update={"id": i, "salve_bonus": 0}) for i in range(100, 170)
    }
    catalog = {**filler, **salves}
    facts = {i: equipment_fact(snapshot, it, content, {}, NOW) for i, it in catalog.items()}
    role = RoleConfig(id="undead", style="crush", target=CombatTarget(traits=("undead",)))
    req = OptimizationRequest(roles=(role,), include_untradeables=True)
    search = _Search(snapshot, req, catalog, facts, None)
    search.pools = {**search.candidate_pools(), "neck": [None, *catalog]}
    vector = SimpleNamespace(
        search=search, objectives=(), options=SimpleNamespace(cost_index=None, risk_index=None)
    )
    assert set(salves) <= set(_metric_pools(search, search)["neck"])
    assert set(salves) <= set(VectorSearch.candidate_pools(vector)["neck"])
