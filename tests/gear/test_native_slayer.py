"""Task equipment multipliers execute in the compiled scorer."""

from types import SimpleNamespace

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content())


def context(catalog, role, ids, level=99):
    from tracker.gear.native._scoring import ScoringContext

    items = {i: catalog.items[i] for i in ids}
    search = SimpleNamespace(
        items=items,
        eligible=items,
        request=SimpleNamespace(roles=(role,), secondary_priority="default"),
        levels=dict.fromkeys(("magic", "ranged", "attack", "strength", "defence", "slayer"), level),
    )
    return ScoringContext(search), search


@pytest.mark.parametrize(
    "style,weapon,head,spell",
    [
        ("slash", 4151, 8921, "fire_wave"),
        ("ranged", 861, 11783, "fire_wave"),
        ("magic", 4675, 11865, "fire_wave"),
        ("magic", 4675, 11865, "ice_barrage"),
    ],
)
@pytest.mark.parametrize("task", [False, True])
def test_native_task_matches_reference(catalog, style, weapon, head, spell, task):
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.scoring import prepare_equipment

    role = RoleConfig(
        id="task",
        style=style,
        spell=spell,
        on_slayer_task=task,
        target=CombatTarget(weakness_element="fire", weakness_percent=53),
    )
    ids = [weapon, head, *([892] if style == "ranged" else [])]
    scorer, search = context(catalog, role, ids)
    equipment = {
        "weapon": weapon,
        "head": head,
        **({"ammunition": 892} if style == "ranged" else {}),
    }
    expected = evaluate_prepared_score(
        prepare_equipment({s: search.items[i] for s, i in equipment.items()}), role, search.levels
    )
    actual = scorer.score(equipment, 0)
    assert expected.supported
    assert actual["supported"]
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy


@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("weapon", [4170, 21255])
@pytest.mark.parametrize("level", [75, 77, 98, 99])
def test_native_magic_dart_matches_reference(catalog, task, weapon, level):
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.scoring import prepare_equipment

    role = RoleConfig(id="dart", style="magic", spell="magic_dart", on_slayer_task=task)
    scorer, search = context(catalog, role, [weapon, 11865], level)
    equipment = {"weapon": weapon, "head": 11865}
    expected = evaluate_prepared_score(
        prepare_equipment({s: search.items[i] for s, i in equipment.items()}), role, search.levels
    )
    actual = scorer.score(equipment, 0)
    assert expected.supported and actual["supported"]
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy


@pytest.mark.parametrize("head", [8921, 11783, 11864, 11865])
@pytest.mark.parametrize("kind", ["melee", "ranged", "water", "powered", "bolts"])
def test_native_task_equipment_interactions(catalog, head, kind):
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.prayers import PrayerPolicy
    from tracker.gear.scoring import prepare_equipment

    equipment = {"head": head}
    if kind == "melee":
        equipment["weapon"] = 4151
        role = RoleConfig(id="task", style="slash", on_slayer_task=True)
    elif kind in {"ranged", "bolts"}:
        equipment.update(weapon=9185, ammunition=9243, shield=32879)
        role = RoleConfig(
            id="task",
            style="ranged",
            stance="rapid",
            on_slayer_task=True,
            target=CombatTarget(hitpoints=500, flat_armour=-2),
        )
    else:
        equipment["weapon"] = 28585 if kind == "powered" else 4675
        if kind == "water":
            equipment.update(shield=25574, neck=34428)
        role = RoleConfig(
            id="task",
            style="magic",
            spell="water_wave",
            on_slayer_task=True,
            prayers=PrayerPolicy(),
            target=CombatTarget(weakness_element="water", weakness_percent=53),
        )
        if kind == "powered":
            role = role.model_copy(update={"powered_attack": catalog.items[28585].powered_attack})
    role = role.model_copy(
        update={
            "active_prayer_ids": (
                "piety"
                if role.style == "slash"
                else "rigour"
                if role.style == "ranged"
                else "augury",
            )
        }
    )
    scorer, search = context(catalog, role, list(equipment.values()))
    expected = evaluate_prepared_score(
        prepare_equipment({s: search.items[i] for s, i in equipment.items()}), role, search.levels
    )
    actual = scorer.score(equipment, 0)
    assert expected.supported and actual["supported"]
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy


@pytest.mark.parametrize(
    "case_name", ["effect_magic_fixed", "effect_ranged", "effect_auto", "effect_multi"]
)
@pytest.mark.parametrize("task", [False, True])
def test_complete_task_archives_execute_natively(catalog, case_name, task):
    from dataclasses import replace

    from tools.benchmark_gear_desktop import case_provenance, result_digest
    from tools.gear_search_quality_fixture import load_case
    from tools.native_effect_cases import derive_effect_case
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.domain.types import Container
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.native import capture
    from tracker.gear.optimizer import optimize
    from tracker.gear.prayers import PrayerPolicy

    base = replace(load_case("melee_1m"), catalog=catalog, content=load_content())
    case, _ = derive_effect_case(base, case_provenance(base), case_name)
    ids = {8921, 11783, 11864, 11865, 4170, 21255}
    ids |= {1381, 9185, 9243, 10499, 25574, 34413}
    items = {i: catalog.items[i] for i in ids}
    observed = {
        **case.snapshot.observed_items,
        **{
            (i, Container.BANK): ObservedItemFact(
                i, Container.BANK, 1, "slayer-native-fixture", case.at
            )
            for i in ids
        },
    }
    roles = tuple(
        role.model_copy(
            update={
                "on_slayer_task": task if index == 0 else not task,
                "prayers": PrayerPolicy(),
                "combat_options": role.combat_options.model_copy(
                    update={
                        "spells": ("water_wave", "magic_dart"),
                        "stances": ("accurate", "rapid"),
                    }
                )
                if role.combat_options
                else None,
            }
        )
        for index, role in enumerate(case.request.roles)
    )
    request = case.request.model_copy(update={"roles": roles})
    snapshot = replace(case.snapshot, observed_items=observed)
    args = (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        case.content,
        case.prices,
        case.at,
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
    }
    expected = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert actual["selected_solution"] is not None
    assert result_digest(actual) == result_digest(expected)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0


@pytest.mark.parametrize("priced", [False, True])
def test_native_enchantment_cost_frontier_matches_python(catalog, priced):
    from dataclasses import replace

    from tools.benchmark_gear_desktop import case_provenance, result_digest
    from tools.gear_search_quality_fixture import load_case
    from tools.native_effect_cases import derive_effect_case
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.domain.types import Container
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.native import capture
    from tracker.gear.objectives import ObjectiveDescriptor
    from tracker.gear.optimizer import optimize
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    base = replace(load_case("melee_1m"), catalog=catalog, content=load_content())
    case, _ = derive_effect_case(base, case_provenance(base), "effect_magic_fixed")
    items = {i: catalog.items[i] for i in (4170, 21255, 11865, 1381)}
    snapshot = replace(
        case.snapshot,
        observed_items={
            (i, Container.BANK): ObservedItemFact(
                i, Container.BANK, 1, "slayer-native-fixture", case.at
            )
            for i in items
        },
    )
    role = RoleConfig(id="dart", style="magic", spell="magic_dart", on_slayer_task=True)
    request = case.request.model_copy(
        update={
            "roles": (role,),
            "secondary_priority": "default",
            "objectives": (ObjectiveDescriptor(kind="gp_per_damage"),),
        }
    )
    prices = {**case.prices}
    if priced:
        prices[21257] = PriceDTO(
            item_id=21257,
            high_price_gp=503,
            high_trade_at=case.at,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=case.at,
            source=PriceSource.LIVE,
            provider="native-slayer-fixture",
        )
    else:
        prices.pop(21257, None)
    args = (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        case.content,
        prices,
        case.at,
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
    }
    expected = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert actual["selected_solution"] is not None
    assert result_digest(actual) == result_digest(expected)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0
