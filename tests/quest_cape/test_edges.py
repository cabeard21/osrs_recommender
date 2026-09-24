import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.generate_quest_cape import generate
from tracker.content.requirements import parse
from tracker.domain.types import QuestStatus, SkillState, Source
from tracker.quest_cape.catalog import load_catalog
from tracker.quest_cape.service import CompleteQuest, QuestCapeService, TrainSkill


def test_detail_pages_keep_global_counts(service, snapshot):
    first = service.get_goal_status(snapshot, quest_limit=2)
    second = service.get_goal_status(snapshot, quest_offset=2, quest_limit=2)
    assert (first.total, first.blocked, first.skill_blockers) == (
        second.total,
        second.blocked,
        second.skill_blockers,
    )
    assert [q.id for q in first.quests] == ["a", "b"]
    assert first.next_quest_offset == 2
    assert [q.id for q in second.quests] == ["c", "d"]
    selected = service.get_goal_status(snapshot, quest_ids=["e"])
    assert selected.quest_details_total == 1
    assert selected.total == 5
    assert selected.next_quest_offset is None
    for kwargs in ({"quest_limit": 0}, {"quest_offset": -1}, {"quest_ids": ["not_a_quest"]}):
        with pytest.raises(ValueError):
            service.get_goal_status(snapshot, **kwargs)


def test_final_rfd_chapter_counts_parent_once(snapshot):
    catalog = load_catalog(Path("content/quest_cape/catalog.json"))
    service = QuestCapeService(catalog)
    account = replace(snapshot, quests={q.id: QuestStatus.IN_PROGRESS for q in catalog.quests})
    result = service.evaluate_action(
        account, CompleteQuest(type="complete_quest", quest="recipe_for_disaster_culinaromancer")
    )
    assert result.completion_delta == 1
    assert snapshot.quests == dict.fromkeys("abcde", QuestStatus.NOT_STARTED)


def test_unknown_rewards_do_not_guess_zero(catalog, snapshot):
    quests = (catalog.quests[0].model_copy(update={"quest_points": None}), *catalog.quests[1:])
    service = QuestCapeService(catalog.model_copy(update={"quests": quests}))
    result = service.evaluate_action(snapshot, CompleteQuest(type="complete_quest", quest="a"))
    assert "e" not in result.quests_newly_available
    change = next(c for c in result.blocker_changes if c.quest == "e")
    assert change.after[0].current is None


def test_combat_training_recomputes_from_levels(catalog, snapshot):
    quest = catalog.quests[0].model_copy(update={"requires": parse({"combat_level": 126})})
    service = QuestCapeService(catalog.model_copy(update={"quests": (quest,)}))
    skills = {
        key: SkillState(99, None, Source.RUNELITE, snapshot.last_sync_at)
        for key in ("attack", "strength", "defence", "hitpoints", "prayer", "ranged", "magic")
    }
    skills["defence"] = replace(skills["defence"], level=98)
    account = replace(snapshot, skills=skills, combat_level=125)
    result = service.evaluate_action(
        account, TrainSkill(type="train_skill", skill="defence", target_level=99)
    )
    assert result.quests_newly_available == ("a",)
    assert account.combat_level == 125
    incomplete = replace(account, skills={"defence": skills["defence"]})
    result = service.evaluate_action(
        incomplete, TrainSkill(type="train_skill", skill="defence", target_level=99)
    )
    assert not result.quests_newly_available
    assert any("Combat level is unknown" in limitation for limitation in result.limitations)


def test_generation_is_reproducible_and_preserves_unmodeled_requirements():
    source = json.loads(Path("tools/data/quest_cape_source.json").read_text())
    assert generate(source) == json.loads(Path("content/quest_cape/catalog.json").read_text())
    generated = {q["id"]: q for q in generate(source)["quests"]}
    assert generated["bone_voyage"]["unmodeled"] == ["*100 [[Kudos]]"]
    assert generated["dragon_slayer_ii"]["unmodeled"]
    assert generated["rag_and_bone_man_ii"]["quest_points"] == 1
    assert generated["recipe_for_disaster_another_cooks_quest"]["quest_points"] == 1
    # Sailing requirements survive even though legacy sync sources may omit that skill.
    assert any("sailing" in json.dumps(q["requires"]) for q in generated.values())


def test_completed_cape_does_not_generate_prerequisite_actions(snapshot):
    catalog = load_catalog(Path("content/quest_cape/catalog.json"))
    # Older or incomplete plugin observations of chapters/miniquests must not cause
    # training proposals once every actual Cape quest is confirmed complete.
    account = replace(
        snapshot,
        quests={
            q.id: QuestStatus.COMPLETE if q.counts_for_cape else QuestStatus.NOT_STARTED
            for q in catalog.quests
        },
    )
    service = QuestCapeService(catalog)
    actions = service.get_available_actions(account)
    assert not actions.quest_actions
    assert not actions.skill_actions
    assert not service.get_goal_status(account).skill_blockers
