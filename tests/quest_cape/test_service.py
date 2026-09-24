import ast
from dataclasses import replace
from pathlib import Path

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.requirements import parse
from tracker.domain.types import QuestStatus, Tri
from tracker.quest_cape.catalog import QuestCatalog, load_catalog
from tracker.quest_cape.requirements import evaluate_requirement
from tracker.quest_cape.service import (
    ACTION_ADAPTER,
    CompleteQuest,
    QuestCapeService,
    TrainSkill,
)


@pytest.mark.parametrize(
    ("requirement", "status"),
    [
        ({"skill": {"agility": 60}}, Tri.SATISFIED),
        ({"skill": {"agility": 70}}, Tri.UNSATISFIED),
        ({"skill": {"magic": 70}}, Tri.UNKNOWN),
        ({"quest": "a"}, Tri.UNSATISFIED),
        ({"quest": "missing"}, Tri.UNKNOWN),
        ({"any_of": [{"skill": {"agility": 60}}, {"quest": "missing"}]}, Tri.SATISFIED),
        ({"at_least": {"n": 1, "of": [{"skill": {"agility": 60}}]}}, Tri.SATISFIED),
    ],
)
def test_requirement(snapshot, requirement, status):
    assert evaluate_requirement(snapshot, parse(requirement)).status is status


def test_status_and_thresholds(service, snapshot):
    result = service.get_goal_status(snapshot)
    assert (result.total, result.completed, result.remaining) == (5, 0, 5)
    assert (result.available_now, result.blocked, result.unknown) == (1, 4, 0)
    assert result.skill_blockers[0].thresholds == (68, 70)
    b = next(q for q in result.quests if q.id == "b")
    assert len(b.blockers) == 2
    actions = service.get_available_actions(snapshot)
    assert [q.quest for q in actions.quest_actions] == ["a"]
    assert [a.target_level for a in actions.skill_actions] == [68, 70]


def test_completion_and_missing_data(service, snapshot):
    observed = replace(snapshot, quests={"a": QuestStatus.COMPLETE})
    result = service.get_goal_status(observed)
    assert result.completed == 1
    assert result.unknown == 4
    assert not service.get_available_actions(observed).quest_actions
    assert evaluate_requirement(observed, parse({"quest": "a"})).status is Tri.SATISFIED
    empty = AccountSnapshot(player_id=1, username="empty")
    assert not service.get_available_actions(empty).skill_actions
    assert service.get_goal_status(empty).unknown == 5


def test_training_unlocks_and_partially_helps_without_mutation(service, snapshot):
    before = snapshot.summary()
    result = service.evaluate_action(
        snapshot, TrainSkill(type="train_skill", skill="agility", target_level=70)
    )
    assert result.requirements_newly_satisfied == 3
    assert result.quests_newly_available == ("d",)
    assert result.quests_helped_but_still_blocked == ("b", "c")
    assert result.completion_delta == 0
    assert snapshot.summary() == before


def test_completion_unlocks_quest_points_and_chains(service, snapshot):
    snapshot = replace(snapshot, skills={"agility": replace(snapshot.skills["agility"], level=70)})
    result = service.evaluate_action(snapshot, CompleteQuest(type="complete_quest", quest="a"))
    assert result.completion_delta == 1
    assert result.quests_newly_available == ("b", "e")
    assert result.downstream_quests == ("b", "c")
    assert snapshot.quests["a"] is QuestStatus.NOT_STARTED


def test_blocked_completion_is_explicitly_conditional(service, snapshot):
    result = service.evaluate_action(snapshot, CompleteQuest(type="complete_quest", quest="b"))
    assert len(result.preconditions) == 2
    assert result.completion_delta == 1
    assert "c" in result.quests_helped_but_still_blocked


@pytest.mark.parametrize(
    "action",
    [
        {"type": "train_skill", "skill": "agility", "target_level": 66},
        {"type": "train_skill", "skill": "unknown", "target_level": 70},
        {"type": "train_skill", "skill": "agility", "target_level": True},
        {"type": "train_skill", "skill": "agility", "target_level": 100},
        {"type": "complete_quest", "quest": "missing"},
        {"type": "complete_quest", "quest": "a", "player_id": 2},
    ],
)
def test_invalid_actions_do_not_mutate(service, snapshot, action):
    before = snapshot.fingerprint
    with pytest.raises(ValueError):
        service.evaluate_action(snapshot, ACTION_ADAPTER.validate_python(action))
    assert before == snapshot.fingerprint


def test_stale_and_unsupported_inputs(service, snapshot):
    with pytest.raises(ValueError, match="snapshot_changed"):
        service.evaluate_action(
            snapshot, CompleteQuest(type="complete_quest", quest="a"), expected_snapshot_id="old"
        )
    with pytest.raises(ValueError, match="Only goal"):
        service.get_goal_status(snapshot, "fire_cape")
    with pytest.raises(ValueError, match="already complete"):
        service.evaluate_action(
            replace(snapshot, quests={"a": QuestStatus.COMPLETE}),
            CompleteQuest(type="complete_quest", quest="a"),
        )


def test_mappings_detached_and_immutable(snapshot):
    source = {"a": QuestStatus.NOT_STARTED}
    account = replace(snapshot, quests=source)
    source["a"] = QuestStatus.COMPLETE
    assert account.quests["a"] is QuestStatus.NOT_STARTED
    with pytest.raises(TypeError):
        account.quests["a"] = QuestStatus.COMPLETE


def test_metadata_gaps_and_alternatives(catalog, snapshot):
    a = catalog.quests[0].model_copy(update={"unmodeled": ("100 Kudos",)})
    alternate = parse({"any_of": [{"skill": {"agility": 60}}, {"skill": {"agility": 99}}]})
    b = catalog.quests[1].model_copy(update={"requires": alternate})
    service = QuestCapeService(catalog.model_copy(update={"quests": (a, b)}))
    status = service.get_goal_status(snapshot)
    assert status.quests[0].availability == "unknown"
    assert not status.skill_blockers


def test_catalog_rejects_missing_prerequisite_and_cycle(catalog):
    data = catalog.model_dump(mode="json")
    data["quests"][0]["requires"] = {"quest": "missing"}
    with pytest.raises(ValueError, match="unresolved"):
        QuestCatalog.model_validate(data)
    data["quests"][0]["requires"] = {"quest": "c"}
    with pytest.raises(ValueError, match="cycle"):
        QuestCatalog.model_validate(data)


def test_shipped_catalog_counts_and_rfd():
    catalog = load_catalog(Path("content/quest_cape/catalog.json"))
    index = catalog.index()
    assert not index["alfred_grimhands_barcrawl"].counts_for_cape
    assert "alfred_grimhands_barcrawl" in catalog.relevant_ids()
    assert index["recipe_for_disaster"].counts_for_cape
    assert not index["recipe_for_disaster_culinaromancer"].counts_for_cape
    assert index["recipe_for_disaster_culinaromancer"].completes_parent == "recipe_for_disaster"
    assert index["regicide"].quest_points == 3
    assert index["cooks_assistant"].requirements_verified
    assert index["cooks_assistant"].requires is None
    assert "underground_pass" in index["regicide"].prerequisites


def test_new_domain_does_not_import_recommendation_models():
    for directory in (Path("tracker/accounts"), Path("tracker/quest_cape")):
        for path in directory.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(
                        ("tracker.recommendations", "tracker.advisor")
                    )
                    assert not {n.name for n in node.names} & {
                        "PlayerState",
                        "Candidate",
                        "Content",
                        "AdvisorSnapshot",
                    }
