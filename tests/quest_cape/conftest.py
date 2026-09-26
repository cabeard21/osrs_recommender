from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import QuestStatus, SkillState, Source
from tracker.quest_cape.catalog import QuestCatalog
from tracker.quest_cape.service import QuestCapeService

NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def catalog() -> QuestCatalog:
    rows = [
        {"id": "a", "name": "A", "quest_points": 2},
        {
            "id": "b",
            "name": "B",
            "requires": {"all_of": [{"quest": "a"}, {"skill": {"agility": 68}}]},
            "quest_points": 1,
        },
        {
            "id": "c",
            "name": "C",
            "requires": {"all_of": [{"quest": "b"}, {"skill": {"agility": 70}}]},
            "quest_points": 1,
        },
        {"id": "d", "name": "D", "requires": {"skill": {"agility": 68}}, "quest_points": 1},
        {"id": "e", "name": "E", "requires": {"quest_points": 12}, "quest_points": 1},
    ]
    return QuestCatalog.model_validate(
        {
            "version": "fixture",
            "source": "fixture",
            "quests": [
                {
                    "counts_for_cape": True,
                    "requirements_verified": True,
                    "wiki_url": "https://example.test/quest",
                    **row,
                }
                for row in rows
            ],
        }
    )


@pytest.fixture
def snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        player_id=1,
        username="fixture",
        last_sync_at=NOW,
        quest_points=10,
        skills={"agility": SkillState(66, None, Source.RUNELITE, NOW)},
        quests=dict.fromkeys("abcde", QuestStatus.NOT_STARTED),
    )


@pytest.fixture
def service(catalog: QuestCatalog) -> QuestCapeService:
    return QuestCapeService(catalog)
