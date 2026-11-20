"""Verify Salve arithmetic through the packed Cython candidate scorer."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.gear.test_revenant_combat import LEVELS, MASK, role_for
from tools.benchmark_gear_desktop import result_digest
from tools.gear_search_quality_fixture import load_case
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.native import capture
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig, optimize


@pytest.mark.parametrize(
    ("weapon_id", "style", "salve", "undead", "inside", "attack", "max_hit"),
    [
        (22545, "crush", 2, True, True, 23166, 39),
        (22545, "crush", 2, True, False, 15444, 26),
        (22550, "ranged", 4, True, True, 25807, 37),
        (22550, "ranged", 2, True, True, 24732, 34),
        (22550, "ranged", 4, False, True, 24732, 34),
        (29305, "ranged", 2, True, False, 16488, 24),
        (29305, "ranged", 4, True, False, 17205, 24),
        (21012, "ranged", 4, True, False, 22366, 31),
        (27788, "magic", 3, True, True, 19334, 44),
        (27788, "magic", 4, True, True, 19987, 46),
        (27275, "magic", 4, True, False, 14388, 51),
        (21255, "magic", 4, True, False, 10428, 34),
    ],
)
def test_native_salve_rolls(weapon_id, style, salve, undead, inside, attack, max_hit):
    native = pytest.importorskip("tracker.gear.native._scoring")
    shadow = weapon_id == 27275
    dart = weapon_id == 21255
    role = role_for(style, inside, task=True, powered="shadow" if shadow else None)
    traits = ("undead",) if undead else ("spectral",)
    if weapon_id == 21012:
        traits += ("dragon",)
    assert role.target is not None
    target = role.target.model_copy(update={"traits": traits})
    role = role.model_copy(update={"target": target, "spell": "magic_dart" if dart else role.spell})
    levels = {**LEVELS, "strength": 90} if weapon_id == 29305 else LEVELS
    levels = {**levels, "slayer": 99} if dart else levels
    gear = [
        EquipmentDefinition(
            id=weapon_id,
            name="Test weapon",
            slot="weapon",
            attack_styles=(style,),
            bonuses=EquipmentBonuses(
                crush=53,
                melee_strength=66,
                ranged=70,
                ranged_strength=60,
                magic=15,
                magic_damage=10 if shadow else 0,
            ),
            powered_attack="shadow" if shadow else None,
            powered_attack_model="shadow" if shadow else None,
            powered_attack_stances=("accurate",) if shadow else (),
            slayer_staff_enchanted=dart,
        ),
        MASK,
        EquipmentDefinition(id=12018, name="Test amulet", slot="neck", salve_bonus=salve),
    ]
    reference = evaluate_loadout(gear, role, levels)
    assert reference.supported
    assert (reference.attack_roll, reference.max_hit) == (attack, max_hit)
    items = {item.id: item for item in gear}
    equipment = {item.slot: item.id for item in gear}
    search = SimpleNamespace(
        request=SimpleNamespace(roles=(role,), secondary_priority="default"),
        levels=levels,
        items=items,
        eligible=items,
    )
    scored = native.ScoringContext(search).score(equipment, 0)
    assert scored["supported"]
    assert (scored["accuracy"], scored["dps"]) == (reference.accuracy, reference.dps)


def test_native_owned_salve_multi_frontier():
    pytest.importorskip("tracker.gear.native._scoring")
    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (4081, 25278, 6585, 4587)
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests={
            **case.snapshot.quests,
            "haunted_mine": QuestStatus.COMPLETE,
            "lair_of_tarn_razorlor": QuestStatus.COMPLETE,
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "salve", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="undead",
        style="slash",
        allowed_disciplines=("melee", "ranged"),
        target=CombatTarget(traits=("undead",)),
        combat_options=CombatOptionFilters(
            attack_types=("slash", "standard"), stances=("aggressive", "rapid"), spells=()
        ),
    )
    ordinary = role.model_copy(
        update={
            "id": "spectral",
            "allowed_disciplines": None,
            "stance": "aggressive",
            "target": CombatTarget(traits=("spectral",)),
        }
    )
    request = case.request.model_copy(update={"roles": (role, ordinary), "mode": "owned"})
    args = (
        snapshot,
        request,
        EquipmentCatalog({i: catalog.items[i] for i in ids}, revision=catalog.revision),
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
    loadouts = actual["selected_solution"]["loadouts"]
    assert loadouts["undead"]["equipment"]["neck"] == 25278
    assert loadouts["spectral"]["equipment"]["neck"] == 6585
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0
