"""Equipment-only objectives reuse option winners without changing Pareto exploration."""

import pytest

from tests.gear.test_auto_disciplines import without_timings
from tests.gear.test_optimizer import run, weapon
from tracker.gear import frontier, optimizer
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig
from tracker.gear.priorities import EQUIPMENT_BONUS_PRIORITIES


def scenario(priority):
    return run(
        [
            weapon(
                1,
                "ranged",
                25,
                attack_profiles=(
                    ("ranged", "accurate"),
                    ("ranged", "rapid"),
                    ("ranged", "longrange"),
                ),
            ),
            EquipmentDefinition(
                id=2,
                name="Defensive body",
                slot="body",
                requirements_complete=True,
                bonuses=EquipmentBonuses(ranged=-10, defence_ranged=60, defence_magic=25),
            ),
            EquipmentDefinition(
                id=3,
                name="Offensive body",
                slot="body",
                requirements_complete=True,
                bonuses=EquipmentBonuses(ranged=20, ranged_strength=5),
            ),
        ],
        (
            RoleConfig(
                id="ranged",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("light",), stances=("accurate", "rapid", "longrange"), spells=()
                ),
            ),
        ),
        secondary_priority=priority,
        max_swaps=2,
    )


@pytest.mark.parametrize("priority", sorted(EQUIPMENT_BONUS_PRIORITIES))
def test_bonus_metric_reuses_winners_with_identical_complete_frontiers(monkeypatch, priority):
    original = optimizer.evaluate_prepared_score
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "evaluate_prepared_score", counted)
    reused = scenario(priority)
    reused_calls = len(calls)
    # Control runs the same searches and budgets with isolated metric winners.
    monkeypatch.setattr(frontier, "EQUIPMENT_BONUS_PRIORITIES", frozenset(), raising=False)
    calls.clear()
    isolated = scenario(priority)
    assert without_timings(reused) == without_timings(isolated)
    assert reused_calls < len(calls)


@pytest.mark.parametrize("priority", ["accuracy", "ranged_defence_roll", "balanced_defence_roll"])
def test_option_dependent_metric_keeps_independent_winner_caches(monkeypatch, priority):
    original = optimizer._Search.loadouts
    independent = []

    def measured(search, roles):
        if getattr(search, "metric_first", False):
            independent.append(not search.performance_cache and not search.option_cache)
        return original(search, roles)

    monkeypatch.setattr(optimizer._Search, "loadouts", measured)
    result = scenario(priority)
    assert result["selected_solution"]
    assert independent == [True]


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
@pytest.mark.parametrize("priority", ["balanced_defence", "magic_ranged_defence", "prayer_bonus"])
@pytest.mark.parametrize("joint", [False, True])
def test_reuse_preserves_prayer_potion_and_running_cost_archives(
    monkeypatch, style, priority, joint
):
    from tests.gear.test_prayer_search_efficiency import scenario as prayer_scenario
    from tracker.gear.potions import PotionPolicy
    from tracker.gear.prayers import PrayerPolicy

    args = list(
        prayer_scenario(
            style,
            PrayerPolicy(
                mode="optimize", allowed_ids=("steel_skin", "eagle_eye", "ultimate_strength")
            ),
        )
    )
    if style == "magic":
        role = args[1].roles[0]
        args[1] = args[1].model_copy(
            update={
                "roles": (
                    role.model_copy(
                        update={
                            "combat_options": role.combat_options.model_copy(
                                update={"spells": ("powered:3",)}
                            )
                        }
                    ),
                )
            }
        )
    if joint:
        role = args[1].roles[0]
        args[1] = args[1].model_copy(
            update={
                "roles": (
                    role,
                    role.model_copy(update={"id": "second", "style": "ranged"}),
                )
            }
        )
    args[1] = args[1].model_copy(
        update={
            "secondary_priority": priority,
            "potions": PotionPolicy(mode="optimize", allowed_ids=("super_defence",)),
        }
    )
    reused = optimizer.optimize(*args, _complete_frontiers=True)
    monkeypatch.setattr(frontier, "EQUIPMENT_BONUS_PRIORITIES", frozenset())
    isolated = optimizer.optimize(*args, _complete_frontiers=True)
    assert reused["secondary_frontiers"] and not reused["running_cost_frontiers"]
    assert without_timings(reused) == without_timings(isolated)
