"""Size-based maximum damage executes in compiled scoring and full searches."""

from types import SimpleNamespace

import pytest

from tracker.gear.combat import accuracy_probability, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.scoring import prepare_equipment


def context(items, role):
    from tracker.gear.native._scoring import ScoringContext

    search = SimpleNamespace(
        items={item.id: item for item in items},
        eligible={item.id for item in items},
        request=SimpleNamespace(roles=(role,), secondary_priority="default"),
        levels=dict.fromkeys(("attack", "strength", "ranged", "magic", "defence"), 99),
    )
    return ScoringContext(search), search


def weapon(effect=True, style="slash"):
    return EquipmentDefinition(
        id=27021,
        name="Size damage fixture",
        slot="weapon",
        bonuses=EquipmentBonuses(slash=98, melee_strength=100),
        attack_styles=(style,),
        attack_speed=6,
        size_damage_bonus={"damage_per_size": 2, "max_size": 5} if effect else None,
    )


@pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 5, 6, 64])
@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("armour", [-5, 0, 6])
def test_native_size_bonus_changes_roll_maximum_after_slayer(size, task, armour):
    role = RoleConfig(
        id="size",
        style="slash",
        stance="aggressive",
        on_slayer_task=task,
        target=CombatTarget(size=size, flat_armour=armour),
    )
    blade = weapon()
    mask = EquipmentDefinition(id=8921, name="Black mask", slot="head", slayer_bonus="melee")
    scorer, search = context([blade, mask], role)
    actual = scorer.score({"weapon": blade.id, "head": mask.id}, 0)
    maximum = (28 * 7 // 6 if task else 28) + 2 * min(size, 5)
    attack = 107 * (98 + 64)
    if task:
        attack = attack * 7 // 6
    accuracy = accuracy_probability(attack, 10 * 64)
    mean = sum(max(0, max(1, roll) - armour) for roll in range(maximum + 1)) / (maximum + 1)
    assert actual["supported"]
    assert actual["dps"] == pytest.approx(accuracy * mean / 3.6)
    reference = evaluate_prepared_score(prepare_equipment([blade, mask]), role, search.levels)
    assert reference.supported
    assert actual["dps"] == reference.dps


@pytest.mark.parametrize("cap,supported", [(37, False), (38, True)])
def test_native_size_damage_obeys_post_bonus_cap(cap, supported):
    role = RoleConfig(
        id="size", style="slash", stance="aggressive", target=CombatTarget(size=5, damage_cap=cap)
    )
    blade = weapon()
    scorer, search = context([blade], role)
    actual = scorer.score({"weapon": blade.id}, 0)
    reference = evaluate_prepared_score(prepare_equipment([blade]), role, search.levels)
    assert actual["supported"] == reference.supported == supported


@pytest.mark.parametrize("style", ["ranged", "magic"])
def test_native_size_bonus_is_melee_only(style):
    role = RoleConfig(id="size", style=style, target=CombatTarget(size=5))
    blade = weapon(style=style)
    scorer, _ = context([blade], role)
    baseline, _ = context([weapon(False, style)], role)
    assert scorer.score({"weapon": blade.id}, 0) == baseline.score({"weapon": blade.id}, 0)


@pytest.mark.parametrize(
    "field,value",
    [("damage_per_size", 0), ("damage_per_size", 101), ("max_size", 0), ("max_size", 65)],
)
def test_native_rejects_size_damage_outside_packed_bounds(field, value):
    blade = weapon()
    effect = blade.size_damage_bonus.model_copy(update={field: value})
    invalid = blade.model_copy(update={"size_damage_bonus": effect})
    with pytest.raises(ValueError, match="size_bonus_range"):
        context([invalid], RoleConfig(id="size", style="slash"))


@pytest.mark.parametrize("size", [-1, 65])
def test_native_rejects_target_size_outside_packed_bounds(size):
    target = CombatTarget().model_copy(update={"size": size})
    with pytest.raises(ValueError, match="target_size_range"):
        context([weapon()], RoleConfig(id="size", style="slash", target=target))


@pytest.mark.parametrize("size", [1, 5])
def test_complete_size_damage_search_matches_python_without_fallback(size):
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
    ids = (27021, 4587, 11865, 1127)
    items = {i: catalog.items[i] for i in ids}
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "size-fixture", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="size",
        style="slash",
        target=CombatTarget(size=size),
        on_slayer_task=True,
        combat_options=CombatOptionFilters(
            attack_types=("slash", "crush"),
            stances=("accurate", "aggressive", "defensive"),
            spells=(),
        ),
    )
    request = case.request.model_copy(update={"roles": (role,), "mode": "owned"})
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
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert actual["selected_solution"] is not None
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0
