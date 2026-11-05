"""Exact prayer-equivalence grouping avoids repeated ordinary combat scoring."""

import json
from dataclasses import replace

import pytest

from tests.gear.test_auto_disciplines import OPTIONS, context
from tracker.domain.types import SkillState, Source, UnlockState
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search, optimize
from tracker.gear.potions import PotionPolicy
from tracker.gear.prayers import PrayerPolicy, catalog, effects, setups


def scenario(style="ranged", policy=None):
    snapshot, _, equipment, content, prices, now = context()
    snapshot = replace(
        snapshot,
        skills={
            k: SkillState(99, None, Source.MANUAL, now)
            for k in ("attack", "strength", "defence", "ranged", "magic", "prayer")
        },
        unlocks=dict.fromkeys(
            ("knight_waves", "rigour", "augury", "deadeye", "mystic_vigour", "zeal"),
            UnlockState.UNLOCKED,
        ),
    )
    policy = policy or PrayerPolicy(mode="optimize", allowed_ids=tuple(p["id"] for p in catalog()))
    role = RoleConfig(id="a", style=style, combat_options=OPTIONS, prayers=policy)
    request = OptimizationRequest(roles=(role,), mode="owned", max_swaps=1)
    return snapshot, request, equipment, content, prices, now


def search(args):
    snap, request, equipment, content, prices, now = args
    facts = {
        i: equipment_fact(snap, item, content, prices, now) for i, item in equipment.items.items()
    }
    return _Search(snap, request, equipment.items, facts, None)


def test_request_validation_does_not_enumerate_optimized_setups(monkeypatch):
    import tracker.gear.prayers as prayers
    from tracker.gear.evaluation import validate_request_context

    args = scenario()

    def unexpected(*args):
        pytest.fail("Optimize eligibility is filtered during search, not request validation")

    monkeypatch.setattr(prayers, "setups", unexpected)
    validate_request_context(args[1], args[0], args[2].items, args[3])


def signature(ids, style):
    modifiers = effects(ids)
    fields = {
        "slash": ("attack", "strength"),
        "ranged": ("ranged_accuracy", "ranged_strength"),
        "magic": ("magic_accuracy", "magic_damage"),
    }[style]
    return tuple(getattr(modifiers, f) for f in (*fields, "defence", "magic_defence"))


def test_legal_setups_generated_once_per_role_across_weapons_and_attacks(monkeypatch):
    import tracker.gear.optimizer as module

    original = module.prayer_setups
    calls = []

    def counted(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(module, "prayer_setups", counted)
    args = scenario("slash")
    instance = search(args)
    role = args[1].roles[0]
    for weapon in [None, *args[2].items.values()]:
        instance.configured_options(role, weapon)
    assert len(calls) == 1
    # A new frozen request cannot inherit eligibility from another snapshot.
    search(args)
    assert len(calls) == 2


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_exact_equivalence_preserves_defence_and_existing_prayer_tie_winner(style):
    args = scenario(style)
    instance = search(args)
    role = args[1].roles[0]
    actual = instance.prayer_options(role, style)
    full = setups(role.prayers, args[0], {k: v.level for k, v in args[0].skills.items()})
    expected = {}
    frontier_expected = {}
    for ids in full:
        key = signature(ids, style)
        previous = expected.get(key)
        if previous is None or (-len(ids), tuple(reversed(ids))) > (
            -len(previous),
            tuple(reversed(previous)),
        ):
            expected[key] = ids
        frontier_previous = frontier_expected.get(key)
        if frontier_previous is None or json.dumps(list(ids)) < json.dumps(list(frontier_previous)):
            frontier_expected[key] = ids
    retained = set(expected.values()) | set(frontier_expected.values())
    assert actual == tuple(ids for ids in full if ids in retained)
    assert len(actual) < len(full)
    assert {signature(ids, style) for ids in actual} == {signature(ids, style) for ids in full}


def test_fixed_prayers_keep_explicit_setup_even_when_irrelevant_to_attack():
    args = scenario("ranged", PrayerPolicy(mode="fixed", selected_ids=("ultimate_strength",)))
    instance = search(args)
    assert instance.prayer_options(args[1].roles[0], "ranged") == (("ultimate_strength",),)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_grouped_search_matches_exhaustive_prayers_with_fewer_evaluations(monkeypatch, style):
    import tracker.gear.optimizer as module

    args = scenario(style)
    # Include magic's powered attack in the available filters.
    role = args[1].roles[0]
    if style == "magic":
        role = role.model_copy(
            update={"combat_options": OPTIONS.model_copy(update={"spells": ("powered:3",)})}
        )
        args = (args[0], args[1].model_copy(update={"roles": (role,)}), *args[2:])
    original = module.evaluate_prepared_score
    calls = []

    def counted(*values, **kwargs):
        calls.append(1)
        return original(*values, **kwargs)

    monkeypatch.setattr(module, "evaluate_prepared_score", counted)
    grouped = optimize(*args)
    count = len(calls)

    def ungrouped(self, role, style):
        return setups(
            role.prayers, self.snapshot, {k: v.level for k, v in self.snapshot.skills.items()}
        )

    monkeypatch.setattr(_Search, "prayer_options", ungrouped)
    monkeypatch.setattr(
        _Search, "scoring_options", lambda self, role, weapon: self.configured_options(role, weapon)
    )
    calls.clear()
    exhaustive = optimize(*args)
    assert grouped["selected_solution"] == exhaustive["selected_solution"]
    assert grouped["curve"] == exhaustive["curve"]
    assert count < len(calls)


@pytest.mark.parametrize("mode", ["single", "auto", "joint"])
def test_grouped_composed_modes_and_frontiers_match_exhaustive(monkeypatch, mode):
    args = scenario("ranged")
    role = args[1].roles[0]
    roles = (role,)
    if mode == "auto":
        roles = (
            role.model_copy(
                update={
                    "allowed_disciplines": ("melee", "ranged", "magic"),
                    "combat_options": OPTIONS.model_copy(update={"spells": ("powered:3",)}),
                }
            ),
        )
    elif mode == "joint":
        roles = (role, role.model_copy(update={"id": "b", "style": "slash"}))
    request = args[1].model_copy(
        update={
            "roles": roles,
            "max_swaps": 2,
            "secondary_priority": "balanced_defence_roll",
            "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",)),
        }
    )
    grouped = optimize(args[0], request, *args[2:])

    def ungrouped(self, role, style):
        return setups(
            role.prayers, self.snapshot, {k: v.level for k, v in self.snapshot.skills.items()}
        )

    monkeypatch.setattr(_Search, "prayer_options", ungrouped)
    monkeypatch.setattr(_Search, "scoring_batches", lambda self, prepared, options: (options,))
    exhaustive = optimize(args[0], request, *args[2:])
    assert grouped["selected_solution"] == exhaustive["selected_solution"]
    assert grouped["secondary_frontiers"] == exhaustive["secondary_frontiers"]
    assert grouped["running_cost_frontiers"] == exhaustive["running_cost_frontiers"]


def test_equivalent_irrelevant_prayers_preserve_frontier_tie_identity(monkeypatch):
    args = scenario(
        "ranged",
        PrayerPolicy(
            mode="optimize", allowed_ids=("burst_of_strength", "clarity_of_thought", "steel_skin")
        ),
    )
    request = args[1].model_copy(update={"secondary_priority": "balanced_defence_roll"})
    grouped = optimize(args[0], request, *args[2:])

    def ungrouped(self, role, style):
        return setups(
            role.prayers, self.snapshot, {k: v.level for k, v in self.snapshot.skills.items()}
        )

    monkeypatch.setattr(_Search, "prayer_options", ungrouped)
    exhaustive = optimize(args[0], request, *args[2:])
    assert grouped["secondary_frontiers"] == exhaustive["secondary_frontiers"]
    assert grouped["running_cost_frontiers"] == exhaustive["running_cost_frontiers"]
