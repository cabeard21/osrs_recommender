"""Scoring lanes need only prayer effects that participate in their ranking key."""

from copy import copy

import pytest

from tests.gear.test_prayer_search_efficiency import scenario, search
from tracker.gear.priorities import secondary_value


def reference(instance, role, equipment):
    rows = []
    for configured, option in instance.configured_options(
        role, instance.items.get(equipment.get("weapon"))
    ):
        performance = instance.evaluate(equipment, configured).model_dump(mode="json")
        if performance["supported"]:
            rows.append((performance, option, configured.active_prayer_ids))
    return max(
        rows,
        key=lambda row: (
            *(
                (secondary_value(instance.request.secondary_priority, row[0]), row[0]["dps"])
                if getattr(instance, "metric_first", False)
                else (row[0]["dps"],)
            ),
            row[1].attack_type,
            row[1].stance,
            row[1].spell or "",
            -len(row[2]),
            tuple(reversed(row[2])),
        ),
    )


def test_dps_lane_scores_offensive_equivalence_once_keeps_full_frontier_options():
    args = scenario("slash")
    instance = search(args)
    role = args[1].roles[0]
    full = instance.configured_options(role, instance.items[1])
    scoring = instance.scoring_options(role, instance.items[1])
    assert len(scoring) < len(full)
    assert len(scoring) == 18
    assert instance.configured_options(role, instance.items[1]) is full


@pytest.mark.parametrize("style,weapon", [("slash", 1), ("ranged", 2), ("magic", 3)])
@pytest.mark.parametrize(
    "metric",
    [
        "default",
        "slash_defence_roll",
        "magic_defence_roll",
        "balanced_defence_roll",
        "accuracy",
        "prayer_bonus",
    ],
)
@pytest.mark.parametrize("metric_first", [False, True])
def test_lane_grouping_matches_exhaustive_performance_and_prayer_ids(
    style, weapon, metric, metric_first
):
    args = scenario(style)
    role = args[1].roles[0]
    if style == "magic":
        role = role.model_copy(
            update={
                "combat_options": role.combat_options.model_copy(update={"spells": ("powered:3",)})
            }
        )
    request = args[1].model_copy(update={"roles": (role,), "secondary_priority": metric})
    instance = search((args[0], request, *args[2:]))
    instance.metric_first = metric_first
    instance.performance_cache = {}
    instance.option_cache = {}
    expected, option, ids = reference(instance, role, {"weapon": weapon})
    assert instance.performance({"weapon": weapon}, role) == expected
    assert instance.selected_prayers({"weapon": weapon}, role) == list(ids)
    assert instance.combat_option({"weapon": weapon}, role) == option.model_dump(
        mode="json", include={"attack_type", "stance", "spell", "powered_attack"}
    )


def test_shallow_copied_metric_lane_cannot_reuse_dps_lane_scoring_options():
    args = scenario("slash")
    instance = search(args)
    role = args[1].roles[0]
    dps = instance.scoring_options(role, instance.items[1])
    metric = copy(instance)
    metric.metric_first = True
    metric.request = instance.request.model_copy(
        update={"secondary_priority": "slash_defence_roll"}
    )
    physical = metric.scoring_options(role, instance.items[1])
    assert len(physical) > len(dps)
    magical = copy(metric)
    magical.request = instance.request.model_copy(
        update={"secondary_priority": "magic_defence_roll"}
    )
    all_defence = magical.scoring_options(role, instance.items[1])
    assert len(all_defence) > len(physical)
    assert instance.scoring_options(role, instance.items[1]) is dps


def test_dps_lane_materializes_only_the_winning_performance(monkeypatch):
    from tracker.gear.models import CombatPerformance

    args = scenario("slash")
    instance = search(args)
    role = args[1].roles[0]
    expected, _, _ = reference(instance, role, {"weapon": 1})
    instance.performance_cache = {}
    instance.option_cache = {}
    original = CombatPerformance.model_dump
    calls = []

    def counted(self, *values, **kwargs):
        calls.append(1)
        return original(self, *values, **kwargs)

    monkeypatch.setattr(CombatPerformance, "model_dump", counted)
    assert instance.performance({"weapon": 1}, role) == expected
    assert len(calls) == 1


def test_candidate_performance_checks_cancellation_before_scoring():
    args = scenario("slash")
    instance = search(args)
    instance.cancelled = lambda: True
    instance.performance_cache = {}
    with pytest.raises(ValueError, match="optimization_cancelled"):
        instance.performance({"weapon": 1}, args[1].roles[0])


def test_optimizer_materializes_one_rich_result_after_lightweight_scoring(monkeypatch):
    import tracker.gear.optimizer as module

    args = scenario("slash")
    instance = search(args)
    role = args[1].roles[0]
    expected, _, _ = reference(instance, role, {"weapon": 1})
    instance.performance_cache = {}
    instance.option_cache = {}
    full = module.evaluate_prepared_loadout
    light = module.evaluate_prepared_score
    full_calls = []
    light_calls = []

    def full_count(*values, **kwargs):
        full_calls.append(1)
        return full(*values, **kwargs)

    def light_count(*values, **kwargs):
        light_calls.append(1)
        return light(*values, **kwargs)

    monkeypatch.setattr(module, "evaluate_prepared_loadout", full_count)
    monkeypatch.setattr(module, "evaluate_prepared_score", light_count)
    assert instance.performance({"weapon": 1}, role) == expected
    assert len(full_calls) == 1
    assert len(light_calls) > 1


def test_metric_roll_lane_scores_only_supported_highest_grade(monkeypatch):
    import tracker.gear.optimizer as module

    args = scenario("slash")
    request = args[1].model_copy(update={"secondary_priority": "slash_defence_roll"})
    instance = search((args[0], request, *args[2:]))
    instance.metric_first = True
    instance.performance_cache = {}
    instance.option_cache = {}
    role = request.roles[0]
    expected, _, _ = reference(instance, role, {"weapon": 1})
    calls = []
    original = module.evaluate_prepared_score

    def counted(*values, **kwargs):
        calls.append(values[1].active_prayer_ids)
        return original(*values, **kwargs)

    monkeypatch.setattr(module, "evaluate_prepared_score", counted)
    assert instance.performance({"weapon": 1}, role) == expected
    assert len(calls) < len(instance.scoring_options(role, instance.items[1]))


def test_metric_roll_lane_falls_back_when_highest_grade_is_damage_capped():
    from tracker.gear.models import CombatTarget

    args = scenario("magic")
    args[2].items[3] = args[2].items[3].model_copy(update={"powered_attack_base_max_hit": 65})
    role = (
        args[1]
        .roles[0]
        .model_copy(
            update={
                "target": CombatTarget(damage_cap=65),
                "combat_options": args[1]
                .roles[0]
                .combat_options.model_copy(update={"spells": ("powered:3",)}),
            }
        )
    )
    request = args[1].model_copy(
        update={"roles": (role,), "secondary_priority": "magic_defence_roll"}
    )
    instance = search((args[0], request, *args[2:]))
    instance.metric_first = True
    instance.performance_cache = {}
    instance.option_cache = {}
    expected, _, ids = reference(instance, role, {"weapon": 3})
    assert "augury" not in ids
    assert instance.performance({"weapon": 3}, role) == expected
    assert instance.selected_prayers({"weapon": 3}, role) == list(ids)


@pytest.mark.parametrize(
    "metric",
    [
        "slash_defence_roll",
        "magic_defence_roll",
        "balanced_defence_roll",
        "magic_ranged_defence_roll",
    ],
)
@pytest.mark.parametrize("bonus", [-100, -64, -63, 0, 100])
def test_metric_grade_ordering_preserves_negative_equipment_and_clamped_rolls(metric, bonus):
    from tracker.gear.models import EquipmentBonuses

    args = scenario("slash")
    args[2].items[1] = (
        args[2]
        .items[1]
        .model_copy(
            update={
                "bonuses": EquipmentBonuses(
                    melee_strength=20, defence_slash=bonus, defence_magic=bonus
                )
            }
        )
    )
    request = args[1].model_copy(update={"secondary_priority": metric})
    instance = search((args[0], request, *args[2:]))
    instance.metric_first = True
    instance.performance_cache = {}
    instance.option_cache = {}
    expected, _, ids = reference(instance, request.roles[0], {"weapon": 1})
    assert instance.performance({"weapon": 1}, request.roles[0]) == expected
    assert instance.selected_prayers({"weapon": 1}, request.roles[0]) == list(ids)
