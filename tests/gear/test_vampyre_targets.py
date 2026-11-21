"""Ordinary vampyre profiles, canonical tier, access and encounter boundaries."""

from types import SimpleNamespace

import pytest

from tracker.domain.types import QuestStatus
from tracker.gear.evaluation import validate_request_context
from tracker.gear.models import CombatTarget
from tracker.gear.npcs import discipline_problem, npc_catalog, resolve_target
from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def profile(npc_id):
    return next(row for row in npc_catalog().entries.values() if row["npc_id"] == npc_id)


def role(npc_id, **settings):
    return RoleConfig(
        id="vyre",
        style="ranged",
        target_selection={
            "key": profile(npc_id)["key"],
            "catalog_revision": npc_catalog().revision,
        },
        **settings,
    )


@pytest.mark.parametrize(
    "npc_id,tier,susceptibility",
    [
        (3237, 1, "susceptible"),
        (5641, 1, "susceptible"),
        (4436, 1, "immune"),
        (9560, 1, "immune"),
        (4427, 2, "immune"),
        (5635, 2, "immune"),
        (3709, 3, "immune"),
        *((i, 3, "immune") for i in range(9756, 9764)),
        *((i, 3, "immune") for i in range(15765, 15771)),
        (16231, 3, "susceptible"),
    ],
)
def test_reviewed_variants(npc_id, tier, susceptibility):
    entry = profile(npc_id)
    assert entry["support_status"] == "supported"
    target = resolve_target(role(npc_id)).target
    assert target.traits == (f"vampyre{tier}",)
    assert target.poison_susceptibility == target.venom_susceptibility == susceptibility
    assert f"Tier {tier}" in entry["limitations"][0]


@pytest.mark.parametrize(
    "npc_id,note",
    [
        (4427, "retreat"),
        (4436, "retreat"),
        (9560, "scripted"),
        (15765, "30 Stymphike"),
        (15770, "Bigger and Badder"),
    ],
)
def test_reviewed_target_limitations(npc_id, note):
    assert note in " ".join(profile(npc_id)["limitations"])


@pytest.mark.parametrize("npc_id", [3481, 6393, 8252, 9561, 3734, 4442, 16204, 16213, 16212])
def test_scripted_profiles_have_named_reason(npc_id):
    entry = profile(npc_id)
    assert entry["support_status"] == "unsupported"
    assert entry["name"] in " ".join(entry["reasons"])


def test_review_does_not_extend_to_new_variants_or_target_traits():
    entry = profile(9756)
    for changed in ({"name": "Another NPC"}, {"version": "New"}, {"attributes": ["vampyre1"]}):
        result = npc_catalog()._entry(
            "new", {**entry["source_record"], **changed}, {"source_url": "test"}
        )
        assert result["support_status"] == "unsupported"
    selected = resolve_target(role(9756))
    with pytest.raises(ValueError, match="cannot be overridden"):
        resolve_target(selected.model_copy(update={"target": CombatTarget(traits=("vampyre1",))}))
    with pytest.raises(ValueError, match="one vampyre tier"):
        CombatTarget(traits=("vampyre1", "vampyre3"))


def test_tier_three_magic_is_blocked_only_for_the_concrete_branch():
    magic = role(9756).model_copy(update={"style": "magic"})
    assert "blisterwood stakes" in discipline_problem(magic)
    with pytest.raises(ValueError, match="Tier 3"):
        resolve_target(magic)
    assert resolve_target(magic.model_copy(update={"allowed_disciplines": ("magic", "ranged")}))
    assert discipline_problem(role(9756)) is None


def validate_access(npc_id, *, quests=None, level=None, on_task=False, **request_settings):
    request = OptimizationRequest(roles=(role(npc_id, on_slayer_task=on_task),), **request_settings)
    snapshot = SimpleNamespace(
        skills={"slayer": SimpleNamespace(level=level)} if level else {},
        quests=quests or {},
    )
    content = SimpleNamespace(
        skills={"slayer"}, quests={"the_blood_moon_rises", "sins_of_the_father"}
    )
    validate_request_context(request, snapshot, {}, content)


def test_venator_access_uses_observed_or_future_player_requirements():
    complete = {"the_blood_moon_rises": QuestStatus.COMPLETE}
    for npc_id in (15765, 15770):
        with pytest.raises(ValueError, match="74 Slayer"):
            validate_access(npc_id, quests=complete, level=73)
        with pytest.raises(ValueError, match="The Blood Moon Rises"):
            validate_access(npc_id, level=74)
        validate_access(npc_id, quests=complete, level=74)
        validate_access(
            npc_id,
            mode="future",
            skill_overrides={"slayer": 74},
            quest_overrides={"the_blood_moon_rises": "complete"},
        )


def test_sentinels_and_ancient_ferals_have_distinct_requirements():
    with pytest.raises(ValueError, match="Sins of the Father"):
        validate_access(9756, quests={"sins_of_the_father": QuestStatus.IN_PROGRESS})
    validate_access(9756, quests={"sins_of_the_father": QuestStatus.COMPLETE})
    with pytest.raises(ValueError, match="The Blood Moon Rises"):
        validate_access(15760)
    with pytest.raises(ValueError, match="Slayer task"):
        validate_access(15760, quests={"the_blood_moon_rises": QuestStatus.COMPLETE}, on_task=True)
    validate_access(15760, quests={"the_blood_moon_rises": QuestStatus.COMPLETE})
    validate_access(3237)


@pytest.mark.parametrize(
    "npc_id,quest,title",
    [
        (9731, "sins_of_the_father", "Sins of the Father"),
        (3694, "darkness_of_hallowvale", "Darkness of Hallowvale"),
    ],
)
def test_city_variants_allow_partial_quest_access(npc_id, quest, title):
    with pytest.raises(ValueError, match=title):
        validate_access(npc_id, quests={quest: QuestStatus.NOT_STARTED})
    validate_access(npc_id, quests={quest: QuestStatus.IN_PROGRESS})


def test_kroy_uses_base_combat_stats_without_quest_progress():
    selected = resolve_target(role(9560))
    assert selected.target.hitpoints == 209
    assert selected.target.defence_level == selected.target.magic_level == 80
    assert all("Sins of the Father" not in note for note in profile(9560)["limitations"])
    validate_access(9560)
    validate_access(9560, quests={"sins_of_the_father": QuestStatus.NOT_STARTED}, on_task=True)


def test_vanstrom_quest_profile_and_access():
    entry = profile(9567)
    assert entry["support_status"] == "supported"
    assert entry["variant"] == "Sins of the Father"
    crush = role(9567).model_copy(update={"style": "crush"})
    resolved = resolve_target(crush)
    assert resolved.target.hitpoints == 750
    assert resolved.target.defence_level == 180
    assert resolved.target.poison_susceptibility == resolved.target.venom_susceptibility == "immune"
    with pytest.raises(ValueError, match="cannot be overridden"):
        resolve_target(
            resolved.model_copy(
                update={"target": resolved.target.model_copy(update={"traits": ("vampyre3",)})}
            )
        )
    for style in ("ranged", "magic"):
        with pytest.raises(ValueError, match="Blisterwood flail"):
            resolve_target(crush.model_copy(update={"style": style}))
    with pytest.raises(ValueError, match="Sins of the Father"):
        validate_access(9567)
    validate_access(9567, quests={"sins_of_the_father": QuestStatus.IN_PROGRESS}, on_task=True)
