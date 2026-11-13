"""Native scorer differential tests; compiler-dependent tests are explicit."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tracker.gear.combat import SPELLS, evaluate_prepared_score
from tracker.gear.combat_options import CombatOption
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.native.packing import support_reason
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig
from tracker.gear.priorities import secondary_value
from tracker.gear.scoring import prepare_equipment


def context(style="slash", stance="accurate", pattern="single", armour=0, cap=None):
    weapon = EquipmentDefinition(
        id=1,
        name="weapon",
        slot="weapon",
        attack_styles=(style,),
        attack_pattern=pattern,
        bonuses=EquipmentBonuses(slash=45, ranged=35, melee_strength=66, ranged_strength=38),
    )
    head = EquipmentDefinition(
        id=2,
        name="head",
        slot="head",
        bonuses=EquipmentBonuses(defence_stab=10, defence_slash=20, defence_magic=-3),
    )
    role = RoleConfig(
        id="role",
        style=style,
        stance=stance,
        target=CombatTarget(defence_level=125, flat_armour=armour, damage_cap=cap),
    )
    search = SimpleNamespace(
        items={1: weapon, 2: head},
        eligible={1: weapon, 2: head},
        request=SimpleNamespace(roles=(role,), secondary_priority="balanced_defence"),
        levels={"attack": 91, "strength": 87, "ranged": 85, "magic": 99, "defence": 78},
        scoring_options=lambda role, weapon: (
            (role, CombatOption(attack_type=style, stance=stance)),
        ),
    )
    return search


def test_support_accepts_magic_and_fractional_magic_metric():
    search = context()
    assert support_reason(search) is None
    search.request.secondary_priority = "magic_damage_bonus"
    assert support_reason(search) is None
    search.request.secondary_priority = "balanced_defence"
    search.request.roles = (RoleConfig(id="magic", style="magic"),)
    assert support_reason(search) is None


@pytest.mark.parametrize(
    "priority",
    [
        "magic_damage_bonus",
        "balanced_defence_roll",
        "magic_ranged_defence_roll",
        "magic_defence_roll",
    ],
)
@pytest.mark.parametrize("metric", [False, True])
def test_native_magic_and_defence_metrics(priority, metric):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context("magic")
    search.items[1] = search.items[1].model_copy(
        update={"bonuses": EquipmentBonuses(magic=55, magic_damage=3.7)}
    )
    search.items[2] = search.items[2].model_copy(
        update={"bonuses": EquipmentBonuses(magic_damage=1.2, defence_magic=25, defence_ranged=30)}
    )
    role = search.request.roles[0].model_copy(
        update={
            "spell": "fire_wave",
            "target": CombatTarget(weakness_element="fire", weakness_percent=50),
        }
    )
    search.request.roles = (role,)
    search.request.secondary_priority = priority
    equipment = {"head": 2, "weapon": 1}
    expected = evaluate_prepared_score(
        prepare_equipment([search.items[i] for i in equipment.values()]),
        role,
        search.levels,
        include_defence=True,
    )
    actual = native.ScoringContext(search).score(equipment, 0, metric)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    assert actual["secondary"] == secondary_value(
        priority,
        {
            "bonuses": expected.bonuses.__dict__,
            "player_defence_rolls": expected.player_defence_rolls,
        },
    )
    assert actual["interval"] == 3.0


@pytest.mark.parametrize(
    "model",
    ["warped", "bone", "seas", "swamp", "sanguinesti", "shadow", "ayak", "thammaron", "accursed"],
)
@pytest.mark.parametrize("cap", [None, 1, 100])
def test_native_reviewed_powered_attacks(model, cap):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context("magic")
    search.items[1] = search.items[1].model_copy(
        update={
            "powered_attack": "test_powered",
            "powered_attack_model": model,
            "powered_attack_stances": ("accurate", "longrange"),
            "attack_speed": 3 if model == "ayak" else 5 if model == "shadow" else 4,
            "bonuses": EquipmentBonuses(magic=75, magic_damage=35.5),
        }
    )
    role = search.request.roles[0].model_copy(
        update={
            "powered_attack": "test_powered",
            "active_prayer_ids": ("augury",),
            "target": CombatTarget(traits=("rat",), damage_cap=cap),
        }
    )
    search.request.roles = (role,)
    prepared = prepare_equipment([search.items[1], search.items[2]])
    expected = evaluate_prepared_score(prepared, role, search.levels, include_defence=True)
    actual = native.ScoringContext(search).score({"weapon": 1, "head": 2}, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    if expected.supported:
        assert actual["player_defence_rolls"] == expected.player_defence_rolls


@pytest.mark.parametrize("spell", SPELLS)
def test_native_reviewed_spells_and_weakness(spell):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context("magic")
    weapon = search.items[1].model_copy(
        update={
            "id": 1409,
            "spell_compatibility": (spell,),
            "bonuses": EquipmentBonuses(magic=48, magic_damage=3.3),
        }
    )
    search.items = {1409: weapon, 2: search.items[2]}
    search.eligible = search.items
    role = search.request.roles[0].model_copy(
        update={
            "spell": spell,
            "active_prayer_ids": ("augury",),
            "target": CombatTarget(weakness_element="fire", weakness_percent=137),
        }
    )
    search.request.roles = (role,)
    expected = evaluate_prepared_score(prepare_equipment([weapon]), role, search.levels)
    actual = native.ScoringContext(search).score({"weapon": 1409}, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy


@pytest.mark.parametrize(
    "priority",
    [
        "balanced_defence_roll",
        "magic_ranged_defence_roll",
        "stab_defence_roll",
        "slash_defence_roll",
        "crush_defence_roll",
        "ranged_defence_roll",
        "magic_defence_roll",
    ],
)
def test_native_defensive_prayer_option_winner(priority):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context()
    role = search.request.roles[0].model_copy(
        update={
            "combat_options": CombatOptionFilters(
                attack_types=("slash",), stances=("accurate", "defensive"), spells=()
            )
        }
    )
    options = tuple(
        (
            role.model_copy(update={"stance": stance, "active_prayer_ids": prayers}),
            CombatOption(attack_type="slash", stance=stance),
        )
        for stance in ("accurate", "defensive")
        for prayers in ((), ("piety",), ("steel_skin",))
    )
    search.request.roles = (role,)
    search.request.secondary_priority = priority
    search.scoring_options = lambda role, weapon: options
    prepared = prepare_equipment([search.items[1], search.items[2]])
    rows = [
        (
            evaluate_prepared_score(prepared, configured, search.levels, include_defence=True),
            configured,
            option,
        )
        for configured, option in options
    ]

    def rank(row):
        score, configured, option = row
        return (
            secondary_value(
                priority,
                {"supported": score.supported, "player_defence_rolls": score.player_defence_rolls},
            ),
            score.dps,
            option.attack_type,
            option.stance,
            option.spell or "",
            -len(configured.active_prayer_ids),
            tuple(reversed(configured.active_prayer_ids)),
        )

    expected, configured, option = max(rows, key=rank)
    scorer = native.ScoringContext(search)
    actual = scorer.score({"weapon": 1, "head": 2}, 0, True)
    assert actual["dps"] == expected.dps
    assert scorer.option_records[actual["option_index"]] == (configured, option)


def test_native_fractional_sum_keeps_compensation_and_insertion_order():
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context("magic")
    search.request.secondary_priority = "magic_damage_bonus"
    search.items = {
        1: search.items[1].model_copy(update={"bonuses": EquipmentBonuses(magic_damage=1000000.0)}),
        2: search.items[2].model_copy(update={"bonuses": EquipmentBonuses(magic_damage=0.1)}),
        3: EquipmentDefinition(
            id=3, name="body", slot="body", bonuses=EquipmentBonuses(magic_damage=-1000000.0)
        ),
    }
    search.eligible = search.items
    scorer = native.ScoringContext(search)
    for equipment in ({"weapon": 1, "head": 2, "body": 3}, {"body": 3, "weapon": 1, "head": 2}):
        expected = evaluate_prepared_score(
            prepare_equipment([search.items[i] for i in equipment.values()]),
            search.request.roles[0],
            search.levels,
        )
        actual = scorer.score(equipment, 0)
        assert actual["bonuses"][7] == expected.bonuses.magic_damage
        assert actual["dps"] == expected.dps


@pytest.mark.parametrize("quest_complete,unlocked", [(False, True), (True, False), (True, True)])
def test_fixed_ancient_packing_preserves_account_access(quest_complete, unlocked):
    from tests.gear.test_combat_options import account
    from tracker.domain.types import QuestStatus, UnlockState
    from tracker.gear.native.packing import OPTION_WIDTH, pack

    search = context("magic")
    search.snapshot = replace(
        account(),
        quests={
            "desert_treasure_i": QuestStatus.COMPLETE if quest_complete else QuestStatus.NOT_STARTED
        },
        unlocks={"spellbook_ancient": UnlockState.UNLOCKED if unlocked else UnlockState.LOCKED},
    )
    search.items[1] = search.items[1].model_copy(update={"spell_compatibility": ("ice_barrage",)})
    search.request.roles = (search.request.roles[0].model_copy(update={"spell": "ice_barrage"}),)
    packed = pack(search)
    weapon = packed["dense_index"][1]
    for metric in (False, True):
        offset = packed["offsets"][int(metric) * packed["item_count"] + weapon]
        assert bool(packed["options"][offset * OPTION_WIDTH + 9]) == (quest_complete and unlocked)


@pytest.mark.parametrize(
    "style,stance",
    [("slash", "accurate"), ("slash", "aggressive"), ("ranged", "rapid"), ("ranged", "accurate")],
)
@pytest.mark.parametrize("pattern", ["single", "independent_double", "conditional_double"])
@pytest.mark.parametrize("armour,cap", [(-4, None), (0, 1), (6, 50)])
def test_native_score_matches_python(style, stance, pattern, armour, cap):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context(style, stance, pattern, armour, cap)
    scorer = native.ScoringContext(search)
    row = {"weapon": 1, "head": 2}
    expected = evaluate_prepared_score(
        prepare_equipment([search.items[i] for i in row.values()]),
        search.request.roles[0],
        search.levels,
    )
    actual = scorer.score(row, 0)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    if expected.supported:
        assert actual["secondary"] == secondary_value(
            "balanced_defence", {"bonuses": expected.bonuses.__dict__}
        )


def test_native_row_validation():
    native = pytest.importorskip("tracker.gear.native._scoring")
    scorer = native.ScoringContext(context())
    with pytest.raises(ValueError):
        scorer.score({"weapon": 999}, 0)
    with pytest.raises(ValueError):
        scorer.score({"weapon": 1}, -1)


@pytest.mark.parametrize("required,compatible", [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize("metric", [False, True])
def test_ammunition_rules_and_adjusted_bonus_priority(required, compatible, metric):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context("ranged", "rapid")
    weapon = search.items[1].model_copy(update={"ammo_for": ("arrow:test",) if required else ()})
    ammo = EquipmentDefinition(
        id=3,
        name="ammo",
        slot="ammunition",
        ammo_type="arrow:test" if compatible else "bolt:test",
        bonuses=EquipmentBonuses(ranged=25, ranged_strength=40),
    )
    search.items = {**search.items, 1: weapon, 3: ammo}
    search.eligible = search.items
    search.request.secondary_priority = "ranged_strength_bonus"
    scorer = native.ScoringContext(search)
    expected = evaluate_prepared_score(
        prepare_equipment([weapon, ammo]), search.request.roles[0], search.levels
    )
    actual = scorer.score({"weapon": 1, "ammunition": 3}, 0, metric)
    assert actual["supported"] == expected.supported
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    if expected.supported:
        assert actual["secondary"] == expected.bonuses.ranged_strength
        assert actual["bonuses"][3] == expected.bonuses.ranged
        assert actual["bonuses"][6] == expected.bonuses.ranged_strength


@pytest.mark.parametrize("metric", [False, True])
@pytest.mark.parametrize(
    "priority",
    [
        "balanced_defence",
        "accuracy",
        "default",
        "magic_ranged_defence",
        "prayer_bonus",
        "melee_strength_bonus",
    ],
)
def test_configured_option_and_prayer_winner_ties(metric, priority):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context()
    role = search.request.roles[0].model_copy(
        update={
            "combat_options": CombatOptionFilters(
                attack_types=("slash",), stances=("accurate", "aggressive", "controlled"), spells=()
            )
        }
    )
    options = tuple(
        (
            role.model_copy(update={"stance": stance, "active_prayer_ids": prayers}),
            CombatOption(attack_type="slash", stance=stance),
        )
        for stance in ("accurate", "aggressive", "controlled")
        for prayers in ((), ("piety",), ("ultimate_strength",))
    )
    search.request.roles = (role,)
    search.request.secondary_priority = priority
    search.scoring_options = lambda role, weapon: options
    scorer = native.ScoringContext(search)
    equipment = {"weapon": 1, "head": 2}
    prepared = prepare_equipment([search.items[i] for i in equipment.values()])
    rows = [
        (evaluate_prepared_score(prepared, configured, search.levels), configured, option)
        for configured, option in options
    ]

    def key(row):
        score, configured, option = row
        secondary = secondary_value(
            priority, {"bonuses": score.bonuses.__dict__, "accuracy": score.accuracy}
        )
        primary = (secondary, score.dps) if metric else (score.dps,)
        return (
            *primary,
            option.attack_type,
            option.stance,
            option.spell or "",
            -len(configured.active_prayer_ids),
            tuple(reversed(configured.active_prayer_ids)),
        )

    expected, configured, option = max(rows, key=key)
    actual = scorer.score(equipment, 0, metric)
    assert actual["dps"] == expected.dps
    assert actual["accuracy"] == expected.accuracy
    assert scorer.option_records[actual["option_index"]] == (configured, option)


@pytest.mark.parametrize("problem", ["unsupported", "two_handed", "slot", "empty_weapon"])
def test_illegal_equipment_matches_reference(problem):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context()
    row = {"weapon": 1, "head": 2}
    if problem == "unsupported":
        search.items[2] = search.items[2].model_copy(update={"unsupported_effects": ("fixture",)})
    elif problem == "two_handed":
        search.items[1] = search.items[1].model_copy(update={"two_handed": True})
        search.items[2] = search.items[2].model_copy(update={"slot": "shield"})
        row = {"weapon": 1, "shield": 2}
    elif problem == "slot":
        row = {"weapon": 2}
    else:
        row = {"head": 2}
    assert not native.ScoringContext(search).score(row, 0)["supported"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("level", "level_range"),
        ("unknown", "unknown_combat_levels"),
        ("bonus", "bonus_range"),
        ("speed", "attack_speed"),
        ("powered", "powered_damage_range"),
        ("target", "target_bonus_range"),
    ],
)
def test_native_numeric_preflight(mutation, reason):
    search = context()
    if mutation == "level":
        search.levels = {**search.levels, "attack": 10001}
    elif mutation == "unknown":
        search.levels = {**search.levels, "strength": 0}
    elif mutation == "bonus":
        search.items[1] = search.items[1].model_copy(
            update={"bonuses": EquipmentBonuses(slash=1000001)}
        )
    elif mutation == "speed":
        search.items[1] = search.items[1].model_copy(update={"attack_speed": 10001})
    elif mutation == "powered":
        search.items[1] = search.items[1].model_copy(update={"powered_attack_base_max_hit": 10001})
    else:
        target = CombatTarget(ranged_heavy=1000001)
        search.request.roles = (search.request.roles[0].model_copy(update={"target": target}),)
    assert support_reason(search) == reason


@pytest.mark.parametrize("count", [0, 5])
def test_native_role_count_is_checked_before_buffer_construction(count):
    search = context()
    search.request.roles = search.request.roles * count
    assert support_reason(search) == "role_count"
    native = pytest.importorskip("tracker.gear.native._scoring")
    with pytest.raises(ValueError, match="role_count"):
        native.ScoringContext(search)


def test_native_dimensions_and_dense_lookup_are_immutable():
    native = pytest.importorskip("tracker.gear.native._scoring")
    scorer = native.ScoringContext(context())
    with pytest.raises(TypeError):
        scorer.dense_index[1] = 1000000
    with pytest.raises(AttributeError):
        scorer.item_count = 1000000
    with pytest.raises(AttributeError):
        scorer.role_count = 1000000
