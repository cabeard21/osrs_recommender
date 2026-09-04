from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import AllOf, QuestLeaf, SkillLeaf
from tracker.content.schema import (
    KappaPresets,
    Quest,
    RoadmapGuide,
    ScoringProfile,
    ScoringWeights,
    Skill,
)
from tracker.domain.types import PlayerState, QuestStatus, SkillState, Source
from tracker.ui.bossing_read_model import BossingStatus, project_bossing_guide


def _content() -> Content:
    return Content(
        profile=ScoringProfile(
            version=1,
            kappa_gp=KappaPresets(high=1, normal=2, low=3),
            weights=ScoringWeights(
                pvp_value=0,
                leverage=0,
                proximity=0,
                effort_decay=0,
                cost_decay=0,
                method_unlock=0,
            ),
        ),
        skills={"attack": Skill(id="attack", name="Attack", is_combat=True)},
        quests={"access": Quest(id="access", name="Access Quest")},
    )


def _skill(level: int) -> SkillState:
    return SkillState(level=level, xp=0, source=Source.RUNELITE, observed_at=datetime.now(UTC))


def _encounter(
    encounter_id: str,
    *,
    access: object | None = None,
    recommendations: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=encounter_id,
        name=encounter_id.title(),
        access_requirements=access,
        recommended_requirements=recommendations,
        mechanics=("Move away",),
        rewards=("Loot",),
        wiki_url=f"https://example.com/{encounter_id}",
    )


def _guide(*tiers: SimpleNamespace) -> RoadmapGuide:
    return cast(RoadmapGuide, SimpleNamespace(id="bossing", name="Bossing", tiers=tiers))


def _tier(tier_id: str, encounters: tuple[SimpleNamespace, ...]) -> SimpleNamespace:
    return SimpleNamespace(id=tier_id, name=tier_id.title(), preparation=(), encounters=encounters)


def test_encounter_states_keep_access_and_recommendation_evidence_separate() -> None:
    access = QuestLeaf(quest_id="access")
    recommendations = AllOf(
        children=(SkillLeaf(skill="attack", level=60), SkillLeaf(skill="attack", level=70))
    )
    guide = _guide(
        _tier("easy", (_encounter("giant", access=access, recommendations=recommendations),))
    )
    state = PlayerState(
        player_id=1,
        quests={"access": QuestStatus.NOT_STARTED},
        skills={"attack": _skill(65)},
    )

    row = project_bossing_guide(guide, state, _content()).tiers[0].encounters[0]

    assert row.status is BossingStatus.LOCKED
    assert [item.description for item in row.access_blockers] == ["Access Quest"]
    assert [item.description for item in row.recommendation_blockers] == ["70 Attack"]
    assert row.access_unknowns == row.recommendation_unknowns == ()
    assert row.readiness_fraction == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (PlayerState(player_id=1), BossingStatus.SYNC_NEEDED),
        (
            PlayerState(
                player_id=1,
                quests={"access": QuestStatus.COMPLETE},
                skills={"attack": _skill(59)},
            ),
            BossingStatus.BUILDING_TOWARD,
        ),
        (
            PlayerState(
                player_id=1,
                quests={"access": QuestStatus.COMPLETE},
                skills={"attack": _skill(60)},
            ),
            BossingStatus.READY,
        ),
    ],
)
def test_status_distinguishes_unknown_building_and_ready(
    state: PlayerState, expected: BossingStatus
) -> None:
    guide = _guide(
        _tier(
            "easy",
            (
                _encounter(
                    "giant",
                    access=QuestLeaf(quest_id="access"),
                    recommendations=SkillLeaf(skill="attack", level=60),
                ),
            ),
        )
    )
    assert project_bossing_guide(guide, state, _content()).tiers[0].encounters[0].status is expected


def test_summary_closest_next_and_default_tier_are_deterministic() -> None:
    guide = _guide(
        _tier(
            "easy",
            (
                _encounter("first", recommendations=SkillLeaf(skill="attack", level=80)),
                _encounter("second", recommendations=SkillLeaf(skill="attack", level=80)),
            ),
        ),
        _tier("hard", (_encounter("ready", recommendations=SkillLeaf(skill="attack", level=60)),)),
        _tier("elite", (_encounter("unknown", access=QuestLeaf(quest_id="access")),)),
    )
    state = PlayerState(
        player_id=1,
        skills={"attack": _skill(70)},
        last_sync_at=datetime.now(UTC),
    )

    view = project_bossing_guide(guide, state, _content())

    assert view.ready_count == 1
    assert view.building_toward_count == 2
    assert view.closest_next is view.tiers[0].encounters[0]
    assert view.default_expanded_tier_id == "hard"


def test_preparation_uses_the_same_status_language_and_models_are_immutable() -> None:
    prep = SimpleNamespace(
        id="train",
        name="Train Attack",
        requirements=SkillLeaf(skill="attack", level=60),
        candidate_id="train_attack_60",
        informational=False,
    )
    guide = cast(
        RoadmapGuide,
        SimpleNamespace(
            id="bossing",
            name="Bossing",
            tiers=(SimpleNamespace(id="easy", name="Easy", preparation=(prep,), encounters=()),),
        ),
    )
    view = project_bossing_guide(guide, PlayerState(player_id=1), _content())

    assert view.tiers[0].preparation[0].status is BossingStatus.SYNC_NEEDED
    with pytest.raises(AttributeError):
        view.ready_count = 2  # type: ignore[misc]
