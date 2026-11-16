"""Dragonbane complete-search Python/native differential coverage."""

from dataclasses import replace

import pytest

from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus, SkillState, Source, UnlockState
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig, optimize


@pytest.mark.parametrize("style", ["stab", "ranged", "magic", "multi", "auto"])
def test_dragonbane_complete_search_native_parity(style):
    from tools.benchmark_gear_desktop import result_digest
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.native import capture

    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (22978, 21012, 25916, 25918, 30070, 9144, 21946, 11865, 1387)
    items = {i: catalog.items[i] for i in ids}
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests={**case.snapshot.quests, "desert_treasure_i": QuestStatus.COMPLETE},
        unlocks={**case.snapshot.unlocks, "barbarian_hasta_training": UnlockState.UNLOCKED},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1000, "dragonbane", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="dragon",
        style="magic" if style in {"multi", "auto"} else style,
        allowed_disciplines=("melee", "ranged", "magic") if style == "auto" else None,
        target=CombatTarget(traits=("dragon",), weakness_element="fire", weakness_percent=50),
        on_slayer_task=True,
        combat_options=CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "heavy", "magic"),
            stances=("accurate", "defensive", "controlled", "rapid"),
            spells=("fire_wave", "ice_barrage"),
        ),
    )
    roles = (role, RoleConfig(id="ordinary", style="ranged")) if style == "multi" else (role,)
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
    assert (
        actual["selected_solution"]["loadouts"]["dragon"]["performance"]["dragonbane_bonus"]
        is not None
    )
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0


@pytest.mark.parametrize(
    "item_id,style,stance",
    [
        (22978, "stab", "controlled"),
        (22978, "slash", "controlled"),
        (22978, "crush", "controlled"),
        (30070, "crush", "aggressive"),
        (21012, "ranged", "rapid"),
        (25916, "ranged", "accurate"),
        (25918, "ranged", "longrange"),
        (30070, "magic", "accurate"),
    ],
)
@pytest.mark.parametrize("on_task", [False, True])
@pytest.mark.parametrize("dragon", [False, True])
def test_dragonbane_native_exact_scores(item_id, style, stance, on_task, dragon):
    from tests.gear.test_native_scoring import context
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.scoring import prepare_equipment

    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context(style, stance)
    weapon = search.items[1].model_copy(
        update={
            "id": item_id,
            "attack_speed": 4 if item_id in {22978, 30070} else 6,
            "attack_profiles": ((style, stance),),
            "spell_compatibility": ("fire_wave",),
            "bonuses": EquipmentBonuses(
                stab=85,
                slash=65,
                crush=65,
                melee_strength=70,
                ranged=95,
                ranged_strength=122,
                magic=16,
                magic_damage=10,
            ),
        }
    )
    head = search.items[2].model_copy(update={"slayer_bonus": "all"})
    search.items = {item_id: weapon, 2: head}
    search.eligible = search.items
    role = search.request.roles[0].model_copy(
        update={
            "spell": "fire_wave",
            "on_slayer_task": on_task,
            "target": CombatTarget(
                traits=("dragon",) if dragon else (),
                defence_level=125,
                magic_level=85,
                weakness_element="fire",
                weakness_percent=50,
            ),
        }
    )
    search.request.roles = (role,)
    equipment = {"weapon": item_id, "head": 2}
    expected = evaluate_prepared_score(prepare_equipment([weapon, head]), role, search.levels)
    actual = native.ScoringContext(search).score(equipment, 0, False)
    assert expected.supported and actual["supported"]
    assert actual["accuracy"] == expected.accuracy
    assert actual["dps"] == expected.dps
    assert actual["interval"] == (
        3.0 if style == "magic" or stance == "rapid" else weapon.attack_speed * 0.6
    )


@pytest.mark.parametrize("element", ["fire", "water", "earth"])
@pytest.mark.parametrize("on_task", [False, True])
@pytest.mark.parametrize("pages", ["burnt", "searing"])
def test_wand_tome_native_parity(element, on_task, pages):
    from tests.gear.test_native_scoring import context
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.models import EquipmentDefinition, TomeEffect
    from tracker.gear.scoring import prepare_equipment

    native = pytest.importorskip("tracker.gear.native._scoring")
    catalog = load_catalog(load_content())
    search = context("magic")
    spell = element + "_wave"
    wand = catalog.items[30070]
    head = catalog.items[11865]
    tome = EquipmentDefinition(
        id=3, name="Tome", slot="shield", tome_effect=TomeEffect(element=element, rune_id=554)
    )
    search.items = {wand.id: wand, head.id: head, tome.id: tome}
    search.eligible = search.items
    role = search.request.roles[0].model_copy(
        update={
            "spell": spell,
            "on_slayer_task": on_task,
            "fire_tome_pages": pages,
            "target": CombatTarget(
                traits=("dragon",),
                defence_level=125,
                magic_level=85,
                weakness_element=element,
                weakness_percent=50,
            ),
        }
    )
    search.request.roles = (role,)
    expected = evaluate_prepared_score(prepare_equipment([wand, head, tome]), role, search.levels)
    actual = native.ScoringContext(search).score(
        {"weapon": wand.id, "head": head.id, "shield": tome.id}, 0, False
    )
    assert expected.supported and actual["supported"]
    assert actual["accuracy"] == expected.accuracy
    assert actual["dps"] == expected.dps
