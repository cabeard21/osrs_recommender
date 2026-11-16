"""Player defensive roll snapshot and tradeoff regression tests."""

from types import SimpleNamespace

import pytest

from tracker.gear.defensive_rolls import player_defence_rolls
from tracker.gear.models import EquipmentBonuses
from tracker.gear.potions import relevant_boost_skills
from tracker.gear.priorities import secondary_value


def test_rolls_use_player_levels_and_separate_magic_floors():
    rolls = player_defence_rolls(
        {"defence": 71, "magic": 73}, EquipmentBonuses(defence_stab=10), "accurate"
    )
    assert rolls.stab == 79 * 74
    assert rolls.magic == (51 + 21 + 8) * 64
    assert rolls.ranged == 79 * 64
    assert not rolls.limitations


@pytest.mark.parametrize(
    "stance,bonus",
    [
        ("accurate", 0),
        ("aggressive", 0),
        ("rapid", 0),
        ("controlled", 1),
        ("defensive", 3),
        ("longrange", 3),
    ],
)
def test_stance_bonus(stance, bonus):
    rolls = player_defence_rolls({"defence": 50, "magic": 50}, EquipmentBonuses(), stance)
    assert rolls.stab == (58 + bonus) * 64
    assert rolls.magic == (58 + bonus) * 64


def test_negative_bonuses_cannot_make_negative_roll():
    assert (
        player_defence_rolls({"defence": 50}, EquipmentBonuses(defence_stab=-100), "accurate").stab
        == 0
    )


def test_missing_stats_remain_unknown():
    rolls = player_defence_rolls({"defence": 50}, EquipmentBonuses(), "accurate")
    assert rolls.stab == 58 * 64
    assert rolls.magic is None
    assert "Magic" in " ".join(rolls.limitations)
    assert player_defence_rolls({}, EquipmentBonuses(), "accurate").stab is None
    with pytest.raises(ValueError, match="unavailable"):
        secondary_value("magic_defence_roll", {"player_defence_rolls": rolls.model_dump()})


@pytest.mark.parametrize(
    "priority,expected",
    [
        ("stab_defence_roll", 10),
        ("slash_defence_roll", 20),
        ("crush_defence_roll", 30),
        ("ranged_defence_roll", 40),
        ("magic_defence_roll", 50),
        ("balanced_defence_roll", 30),
        ("magic_ranged_defence_roll", 40),
    ],
)
def test_metric_roll_aggregation(priority, expected):
    assert (
        secondary_value(
            priority,
            {
                "player_defence_rolls": {
                    "stab": 10,
                    "slash": 20,
                    "crush": 30,
                    "ranged": 40,
                    "magic": 50,
                }
            },
        )
        == expected
    )


def test_defensive_skills_relevant_independent_of_outgoing_discipline():
    role = SimpleNamespace(style="slash", allowed_disciplines=None)
    request = SimpleNamespace(roles=(role,), secondary_priority="magic_ranged_defence_roll")
    assert relevant_boost_skills(request) == {"attack", "strength", "defence", "magic"}
    request.secondary_priority = "stab_defence_roll"
    assert relevant_boost_skills(request) == {"attack", "strength", "defence"}


def test_unsupported_partial_loadout_can_be_ranked_without_inventing_rolls():
    assert (
        secondary_value("stab_defence_roll", {"supported": False, "player_defence_rolls": None})
        == 0
    )
    with pytest.raises(ValueError, match="unavailable"):
        secondary_value("stab_defence_roll", {"supported": True, "player_defence_rolls": None})


@pytest.mark.parametrize(
    "priority,levels,missing",
    [
        ("stab_defence_roll", {}, "defence"),
        ("balanced_defence_roll", {"defence": 70}, "magic"),
        ("magic_ranged_defence_roll", {"magic": 70}, "defence"),
        ("melee_defence_roll", {}, "defence"),
        ("melee_ranged_defence_roll", {}, "defence"),
        ("melee_magic_defence_roll", {"defence": 70}, "magic"),
        ("stab_magic_defence_roll", {"magic": 70}, "defence"),
        ("stab_magic_defence_roll", {"defence": 70}, "magic"),
        ("stab_ranged_defence_roll", {}, "defence"),
        ("stab_magic_ranged_defence_roll", {"magic": 70}, "defence"),
        ("stab_magic_ranged_defence_roll", {"defence": 70}, "magic"),
        ("slash_magic_defence_roll", {"magic": 70}, "defence"),
        ("slash_magic_defence_roll", {"defence": 70}, "magic"),
        ("slash_ranged_defence_roll", {}, "defence"),
        ("slash_magic_ranged_defence_roll", {"magic": 70}, "defence"),
        ("slash_magic_ranged_defence_roll", {"defence": 70}, "magic"),
        ("crush_magic_defence_roll", {"magic": 70}, "defence"),
        ("crush_magic_defence_roll", {"defence": 70}, "magic"),
        ("crush_ranged_defence_roll", {}, "defence"),
        ("crush_magic_ranged_defence_roll", {"magic": 70}, "defence"),
        ("crush_magic_ranged_defence_roll", {"defence": 70}, "magic"),
    ],
)
def test_request_validation_rejects_unknown_required_defensive_stat(priority, levels, missing):
    from tracker.gear.evaluation import validate_request_context
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig

    request = OptimizationRequest(
        roles=(RoleConfig(id="a", style="slash"),), secondary_priority=priority
    )
    snapshot = SimpleNamespace(
        skills={key: SimpleNamespace(level=value) for key, value in levels.items()}
    )
    with pytest.raises(ValueError, match=f"unknown {missing} level"):
        validate_request_context(request, snapshot, {}, None)


@pytest.mark.parametrize(
    "priority", ["ranged_defence_roll", "melee_defence_roll", "melee_ranged_defence_roll"]
)
def test_physical_metric_does_not_require_magic_or_ranged_level(priority):
    rolls = player_defence_rolls({"defence": 70}, EquipmentBonuses(), "accurate")
    assert secondary_value(priority, {"player_defence_rolls": rolls.model_dump()}) == 78 * 64


@pytest.mark.parametrize(
    "priority,styles",
    [
        ("melee_defence_roll", ("stab", "slash", "crush")),
        ("melee_magic_defence_roll", ("stab", "slash", "crush", "magic")),
        ("melee_ranged_defence_roll", ("stab", "slash", "crush", "ranged")),
        ("stab_magic_defence_roll", ("stab", "magic")),
        ("stab_ranged_defence_roll", ("stab", "ranged")),
        ("stab_magic_ranged_defence_roll", ("stab", "magic", "ranged")),
        ("slash_magic_defence_roll", ("slash", "magic")),
        ("slash_ranged_defence_roll", ("slash", "ranged")),
        ("slash_magic_ranged_defence_roll", ("slash", "magic", "ranged")),
        ("crush_magic_defence_roll", ("crush", "magic")),
        ("crush_ranged_defence_roll", ("crush", "ranged")),
        ("crush_magic_ranged_defence_roll", ("crush", "magic", "ranged")),
    ],
)
def test_melee_metrics_use_every_included_weakest_roll(priority, styles):
    for weakest in styles:
        rolls = dict.fromkeys(styles, 1000)
        rolls[weakest] = 17
        assert secondary_value(priority, {"player_defence_rolls": rolls}) == 17
        rolls[weakest] = 0
        assert secondary_value(priority, {"player_defence_rolls": rolls}) == 0
        rolls[weakest] = None
        with pytest.raises(ValueError, match="unavailable"):
            secondary_value(priority, {"player_defence_rolls": rolls})
    assert secondary_value(priority, {"player_defence_rolls": dict.fromkeys(styles, 99)}) == 99
    assert secondary_value(priority, {"supported": False}) == 0


@pytest.mark.parametrize(
    "priority,skills",
    [
        ("melee_defence_roll", {"defence"}),
        ("melee_ranged_defence_roll", {"defence"}),
        ("melee_magic_defence_roll", {"defence", "magic"}),
        ("stab_magic_defence_roll", {"defence", "magic"}),
        ("stab_ranged_defence_roll", {"defence"}),
        ("stab_magic_ranged_defence_roll", {"defence", "magic"}),
        ("slash_magic_defence_roll", {"defence", "magic"}),
        ("slash_ranged_defence_roll", {"defence"}),
        ("slash_magic_ranged_defence_roll", {"defence", "magic"}),
        ("crush_magic_defence_roll", {"defence", "magic"}),
        ("crush_ranged_defence_roll", {"defence"}),
        ("crush_magic_ranged_defence_roll", {"defence", "magic"}),
    ],
)
def test_melee_metric_required_skills_and_potion_relevance(priority, skills):
    from tracker.gear.defensive_rolls import required_defensive_skills

    assert required_defensive_skills(priority) == skills
    role = SimpleNamespace(style="slash", allowed_disciplines=None)
    request = SimpleNamespace(roles=(role,), secondary_priority=priority)
    assert relevant_boost_skills(request) == skills | {"attack", "strength"}


def test_melee_magic_metric_does_not_require_ranged_level():
    rolls = player_defence_rolls({"defence": 70, "magic": 70}, EquipmentBonuses(), "accurate")
    assert (
        secondary_value("melee_magic_defence_roll", {"player_defence_rolls": rolls.model_dump()})
        == 78 * 64
    )
