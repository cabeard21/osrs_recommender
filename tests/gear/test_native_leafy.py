"""Leafy immunity and seeking damage execute in the compiled scorer."""

from types import SimpleNamespace

import pytest

from tracker.gear.combat import accuracy_probability, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment


def context(items, role, level=99):
    from tracker.gear.native._scoring import ScoringContext

    search = SimpleNamespace(
        items={item.id: item for item in items},
        eligible={item.id for item in items},
        request=SimpleNamespace(roles=(role,), secondary_priority="default"),
        levels=dict.fromkeys(("attack", "strength", "ranged", "magic", "defence", "slayer"), level),
    )
    return ScoringContext(search), search


def weapon(item_id=20727, style="slash", ammo_for=()):
    return EquipmentDefinition(
        id=item_id,
        name="Reviewed fixture",
        slot="weapon",
        attack_styles=(style,),
        ammo_for=ammo_for,
        bonuses=EquipmentBonuses(slash=72, melee_strength=92),
        attack_speed=5,
    )


@pytest.mark.parametrize("task", [False, True])
def test_native_leaf_battleaxe_multiplier(task):
    role = RoleConfig(
        id="leaf", style="slash", on_slayer_task=task, target=CombatTarget(traits=("leafy",))
    )
    axe = weapon()
    mask = EquipmentDefinition(id=8921, name="Black mask", slot="head", slayer_bonus="melee")
    scorer, _ = context([axe, mask], role)
    actual = scorer.score({"weapon": axe.id, "head": mask.id}, 0)
    maximum = (26 * 7 // 6 if task else 26) * 47 // 40
    attack = 110 * 136
    if task:
        attack = attack * 7 // 6
    accuracy = accuracy_probability(attack, 10 * 64)
    expected = accuracy * ((1 + maximum * (maximum + 1) / 2) / (maximum + 1)) / 3
    assert actual["supported"]
    assert actual["dps"] == expected


@pytest.mark.parametrize("maximum", range(5))
@pytest.mark.parametrize("armour", [-2, 0, 2, 4])
def test_native_seeking_clamp_exact_distribution(maximum, armour):
    bow = weapon(861, "ranged", ("arrow:33601",))
    arrow = EquipmentDefinition(
        id=33601,
        name="Seeking broad arrows",
        slot="ammunition",
        ammo_type="arrow:33601",
        bonuses=EquipmentBonuses(ranged_strength=round(maximum * 640 / 9) - 64),
    )
    role = RoleConfig(
        id="leaf",
        style="ranged",
        stance="rapid",
        target=CombatTarget(traits=("leafy",), flat_armour=armour),
    )
    scorer, search = context([bow, arrow], role, level=1)
    equipment = {"weapon": bow.id, "ammunition": arrow.id}
    actual = scorer.score(equipment, 0)
    accuracy = accuracy_probability(9 * 64, 10 * 64)
    mean = sum(max(0, max(d, 3) - armour) for d in range(maximum + 1)) / (maximum + 1)
    assert actual["supported"]
    assert actual["dps"] == accuracy * mean / 2.4
    reference = evaluate_prepared_score(prepare_equipment([bow, arrow]), role, search.levels)
    assert reference.supported and actual["dps"] == reference.dps


@pytest.mark.parametrize(
    "item,ammo",
    [
        (weapon(4151), None),
        (weapon(861, "ranged", ("arrow:892",)), 892),
        (weapon(4212, "ranged"), 33601),
    ],
)
def test_native_leafy_rejects_incompatible_attacks(item, ammo):
    role = RoleConfig(
        id="leaf", style=item.attack_styles[0], target=CombatTarget(traits=("leafy",))
    )
    arrow = EquipmentDefinition(
        id=ammo or 4160, name="Arrow", slot="ammunition", ammo_type=f"arrow:{ammo or 4160}"
    )
    scorer, _ = context([item, arrow], role)
    actual = scorer.score({"weapon": item.id, "ammunition": arrow.id}, 0)
    assert not actual["supported"]


@pytest.mark.parametrize("style", ["slash", "ranged", "magic", "multi", "auto"])
def test_complete_leafy_search_matches_python_without_fallback(style):
    from dataclasses import replace

    from tools.benchmark_gear_desktop import result_digest
    from tools.gear_search_quality_fixture import load_case
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import load_content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.catalog import EquipmentCatalog, load_catalog
    from tracker.gear.native import capture
    from tracker.gear.optimizer import CombatOptionFilters, optimize

    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (4158, 11902, 20727, 4160, 33601, 11875, 21316, 861, 9185, 4170, 21255, 11865, 4151, 892)
    items = {i: catalog.items[i] for i in ids}
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(
                i, Container.BANK, 1000, "leafy-native-fixture", case.at
            )
            for i in ids
        },
    )
    role = RoleConfig(
        id="leaf",
        style="ranged" if style in {"multi", "auto"} else style,
        allowed_disciplines=("melee", "ranged", "magic") if style == "auto" else None,
        target=CombatTarget(traits=("leafy",)),
        on_slayer_task=True,
        combat_options=CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "standard", "heavy", "magic"),
            stances=("accurate", "aggressive", "controlled", "defensive", "rapid"),
            spells=("magic_dart", "fire_wave"),
        ),
    )
    roles = (role, RoleConfig(id="ordinary", style="slash")) if style == "multi" else (role,)
    request = case.request.model_copy(update={"roles": roles, "mode": "owned"})
    args = (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        content,
        case.prices,
        case.at,
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert actual["selected_solution"] is not None
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0


@pytest.mark.parametrize("cap,supported", [(2, False), (3, True)])
@pytest.mark.parametrize("leafy", [False, True])
def test_seeking_cap_applies_after_hit_floor(cap, supported, leafy):
    bow = weapon(861, "ranged", ("arrow:33601",))
    ammo = EquipmentDefinition(
        id=33601,
        name="Seeking broad arrows",
        slot="ammunition",
        ammo_type="arrow:33601",
        bonuses=EquipmentBonuses(ranged_strength=-64),
    )
    role = RoleConfig(
        id="cap",
        style="ranged",
        stance="rapid",
        target=CombatTarget(traits=("leafy",) if leafy else (), damage_cap=cap),
    )
    scorer, search = context([bow, ammo], role, level=1)
    equipment = {"weapon": bow.id, "ammunition": ammo.id}
    actual = scorer.score(equipment, 0)
    reference = evaluate_prepared_score(prepare_equipment([bow, ammo]), role, search.levels)
    assert actual["supported"] == reference.supported == supported
    if supported:
        assert actual["dps"] == reference.dps
