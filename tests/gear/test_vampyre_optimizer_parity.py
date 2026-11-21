"""Check complete bounded searches, including the native objective frontier."""

from dataclasses import replace

import pytest

from tools.benchmark_gear_desktop import without_observations
from tools.gear_search_quality_fixture import load_case
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.models import CombatTarget
from tracker.gear.native import capture
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize


@pytest.mark.parametrize("mode", ["ring", "stakes", "mixed", "auto"])
def test_complete_search_has_identical_native_results(mode):
    case = load_case("melee_1m")
    content = load_content()
    full = load_catalog(content)
    ids = (4151, 21140, 11865) if mode in {"ring", "mixed"} else (33716, 33718, 21140, 11865)
    catalog = EquipmentCatalog({i: full.items[i] for i in ids}, revision=full.revision)
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests=dict.fromkeys(content.quests, QuestStatus.COMPLETE),
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "vyre", case.at)
            for i in ids
        },
    )
    ranged = mode in {"auto", "stakes"}
    role = RoleConfig(
        id="vyre",
        style="ranged" if ranged else "slash",
        stance="rapid" if ranged else "accurate",
        target=CombatTarget(traits=("vampyre3" if ranged else "vampyre2",)),
        allowed_disciplines=("melee", "ranged", "magic") if mode == "auto" else None,
        combat_options=CombatOptionFilters(
            attack_types=("slash", "light", "magic"),
            stances=("accurate", "rapid"),
            spells=("fire_strike",),
        )
        if mode == "auto"
        else None,
    )
    roles = (role, RoleConfig(id="ordinary", style="slash")) if mode == "mixed" else (role,)
    request = OptimizationRequest(
        mode="owned",
        roles=roles,
        max_swaps=1 if mode == "mixed" else 0,
        objectives=({"kind": "prayer_bonus"},) if mode != "auto" else None,
    )
    args = snapshot, request, catalog, content, case.prices, case.at
    flags = {
        "_execution_profile": "combined",
        "_factored_evaluation": True,
        "_compact_states": True,
        "_fixed_reporting": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True, _native_required=True)
    selected = actual["selected_solution"]
    assert selected is not None
    assert selected["loadouts"]["vyre"]["performance"]["vampyre_bonus"]["tier"] == (
        3 if ranged else 2
    )
    if mode in {"ring", "mixed"}:
        assert selected["loadouts"]["vyre"]["equipment"]["ring"] == 21140
    assert without_observations(actual) == without_observations(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0


@pytest.mark.parametrize(
    "ranged,wear_ring,expected",
    [
        (True, False, 26),
        (True, True, 28),
        (False, False, 47),
        (False, True, 51),
    ],
)
def test_sentinel_reference_gear_through_native_optimizer(ranged, wear_ring, expected):
    from tracker.domain.types import UnlockState
    from tracker.gear.models import TargetSelection
    from tracker.gear.npcs import npc_catalog, resolve_request
    from tracker.gear.potions import PotionPolicy
    from tracker.gear.prayers import PrayerPolicy

    case = load_case("melee_1m")
    content = load_content()
    full = load_catalog(content)
    ids = (
        [11664, 22109, 19547, 33716, 13072, 13073, 8842, 19933]
        if ranged
        else [
            29028,
            21295,
            19553,
            33718,
            29022,
            12954,
            29025,
            7462,
            11840,
        ]
    )
    if wear_ring:
        ids.append(21140)
    potion = 2444 if ranged else 12695
    snapshot = replace(
        case.snapshot,
        skills={
            k: SkillState(87 if k == "attack" else 99, None, Source.MANUAL, case.at)
            for k in content.skills
        },
        quests=dict.fromkeys(content.quests, QuestStatus.COMPLETE),
        unlocks={
            **case.snapshot.unlocks,
            "deadeye": UnlockState.UNLOCKED,
            "knight_waves": UnlockState.UNLOCKED,
            "zeal": UnlockState.LOCKED,
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "fixture", case.at)
            for i in [*ids, potion]
        },
    )
    sentinel = next(e for e in npc_catalog().entries.values() if e["npc_id"] == 9756)
    role = RoleConfig(
        id="sentinel",
        style="ranged" if ranged else "slash",
        stance="rapid" if ranged else "accurate",
        target_selection=TargetSelection(
            key=sentinel["key"], catalog_revision=sentinel["catalog_revision"]
        ),
        prayers=PrayerPolicy(mode="fixed", selected_ids=("deadeye" if ranged else "piety",)),
        locks={full.items[i].slot: i for i in ids},
    )
    request = OptimizationRequest(
        mode="owned",
        roles=(role,),
        max_swaps=0,
        potions=PotionPolicy(mode="fixed", selected_ids=("ranging" if ranged else "super_combat",)),
    )
    catalog = EquipmentCatalog({i: full.items[i] for i in ids}, revision=full.revision)
    result = optimize(
        snapshot,
        resolve_request(request),
        catalog,
        content,
        case.prices,
        case.at,
        _execution_profile="combined",
        _factored_evaluation=True,
        _compact_states=True,
        _fixed_reporting=True,
        _native_search=True,
        _native_required=True,
    )
    assert result["selected_solution"], result["limitations"]
    attack = result["selected_solution"]["loadouts"]["sentinel"]["performance"]
    assert attack["max_hit"] == expected
    assert bool(attack["elite_void_ranged_bonus"]) is ranged
