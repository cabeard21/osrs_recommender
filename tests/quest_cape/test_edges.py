import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.generate_quest_cape import generate
from tracker.content.requirements import parse
from tracker.domain.types import QuestStatus, SkillState, Source
from tracker.quest_cape.catalog import QuestCatalog, load_catalog
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


def test_action_pages_and_filters_cover_every_action(service, snapshot):
    all_actions = service.get_available_actions(snapshot)
    assert all_actions.actions_total == 3
    assert all_actions.next_action_offset is None

    first = service.get_available_actions(snapshot, action_limit=1)
    second = service.get_available_actions(snapshot, action_offset=1, action_limit=1)
    third = service.get_available_actions(snapshot, action_offset=2, action_limit=1)
    assert [a.quest for a in first.quest_actions] == ["a"]
    assert [a.target_level for a in second.skill_actions] == [68]
    assert [a.target_level for a in third.skill_actions] == [70]
    assert [page.actions_total for page in (first, second, third)] == [3, 3, 3]
    assert [page.next_action_offset for page in (first, second, third)] == [1, 2, None]

    skills = service.get_available_actions(snapshot, action_type="train_skill", action_limit=1)
    assert not skills.quest_actions
    assert skills.actions_total == 2
    assert skills.next_action_offset == 1
    quests = service.get_available_actions(snapshot, action_type="complete_quest")
    assert [a.quest for a in quests.quest_actions] == ["a"]
    assert quests.actions_total == 1
    filtered = service.get_available_actions(snapshot, skill="agility", action_offset=1)
    assert not filtered.quest_actions
    assert [a.target_level for a in filtered.skill_actions] == [70]
    assert filtered.actions_total == 2
    assert filtered.next_action_offset is None
    missing = service.get_available_actions(snapshot, skill="runecraft")
    assert missing.actions_total == 0
    assert missing.next_action_offset is None
    assert not missing.skill_actions


def test_available_quest_actions_mark_cape_counting_without_changing_pagination(snapshot):
    catalog = QuestCatalog.model_validate(
        {
            "version": "action-counting-fixture",
            "source": "fixture",
            "quests": [
                {
                    "id": "miniquest",
                    "name": "A prerequisite miniquest",
                    "counts_for_cape": False,
                    "requirements_verified": True,
                    "wiki_url": "https://example.test/miniquest",
                },
                {
                    "id": "cape_quest",
                    "name": "B Cape quest",
                    "counts_for_cape": True,
                    "requires": {"quest": "miniquest"},
                    "requirements_verified": True,
                    "wiki_url": "https://example.test/cape-quest",
                },
                {
                    "id": "available_cape_quest",
                    "name": "C available Cape quest",
                    "counts_for_cape": True,
                    "requirements_verified": True,
                    "wiki_url": "https://example.test/available-cape-quest",
                },
            ],
        }
    )
    account = replace(
        snapshot,
        quests=dict.fromkeys(
            ("miniquest", "cape_quest", "available_cape_quest"), QuestStatus.NOT_STARTED
        ),
    )
    service = QuestCapeService(catalog)
    assert service.get_goal_status(account, quest_ids=[]).available_now == 1
    first = service.get_available_actions(account, action_type="complete_quest", action_limit=1)
    second = service.get_available_actions(
        account, action_type="complete_quest", action_offset=1, action_limit=1
    )
    assert [(action.quest, action.counts_for_cape) for action in first.quest_actions] == [
        ("miniquest", False)
    ]
    assert [(action.quest, action.counts_for_cape) for action in second.quest_actions] == [
        ("available_cape_quest", True)
    ]
    assert [page.actions_total for page in (first, second)] == [2, 2]
    assert [page.next_action_offset for page in (first, second)] == [1, None]
    assert service.get_available_actions(account).actions_total == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action_offset": -1},
        {"action_limit": 0},
        {"action_limit": 101},
        {"action_type": "unknown"},
        {"action_type": "complete_quest", "skill": "agility"},
    ],
)
def test_invalid_action_discovery_inputs(service, snapshot, kwargs):
    with pytest.raises(ValueError):
        service.get_available_actions(snapshot, **kwargs)


def test_goal_summary_and_freshness_on_all_goal_results(service, snapshot):
    summary = service.get_goal_status(snapshot, quest_ids=[])
    assert not summary.quests
    assert summary.total == 5
    assert summary.skill_blockers
    assert summary.last_sync_at == snapshot.last_sync_at
    assert service.get_available_actions(snapshot).last_sync_at == snapshot.last_sync_at
    evaluation = service.evaluate_action(snapshot, CompleteQuest(type="complete_quest", quest="a"))
    assert evaluation.last_sync_at == snapshot.last_sync_at
    assert evaluation.snapshot_id == snapshot.fingerprint
    unsynced = replace(snapshot, last_sync_at=None)
    assert service.get_goal_status(unsynced, quest_ids=[]).last_sync_at is None
    assert service.get_available_actions(unsynced).last_sync_at is None
    assert (
        service.evaluate_action(
            unsynced, CompleteQuest(type="complete_quest", quest="a")
        ).last_sync_at
        is None
    )


def test_default_action_discovery_is_a_page_of_the_catalog(snapshot):
    catalog = load_catalog(Path("content/quest_cape/catalog.json"))
    service = QuestCapeService(catalog)
    account = replace(
        snapshot,
        quests={q.id: QuestStatus.NOT_STARTED for q in catalog.quests},
        skills={},
    )
    blockers = service.get_goal_status(account, quest_ids=[]).skill_blockers
    account = replace(
        account,
        skills={
            b.skill: SkillState(1, None, Source.RUNELITE, snapshot.last_sync_at) for b in blockers
        },
    )
    first = service.get_available_actions(account)
    assert len(first.quest_actions) + len(first.skill_actions) == 50
    assert first.actions_total > 50
    assert first.next_action_offset == 50
    seen: set[tuple[str, str, int | None]] = set()
    offset = 0
    while True:
        page = service.get_available_actions(account, action_offset=offset)
        assert page.actions_total == first.actions_total
        for action in (*page.quest_actions, *page.skill_actions):
            key = (
                action.type,
                action.quest if action.type == "complete_quest" else action.skill,
                None if action.type == "complete_quest" else action.target_level,
            )
            assert key not in seen
            seen.add(key)
        if page.next_action_offset is None:
            break
        offset = page.next_action_offset
    assert len(seen) == first.actions_total


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
