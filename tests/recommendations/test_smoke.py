"""The retained recommendations page still receives a usable sync result."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tracker.content.validate import load_and_validate
from tracker.domain.types import PlayerState, RoadmapSelection, SkillState, Source
from tracker.recommendations.engine import recommend_run


def test_shipped_content_produces_a_deterministic_recommendation_run() -> None:
    content = load_and_validate(Path(__file__).parents[2] / "content")
    now = datetime(2026, 8, 4, tzinfo=UTC)
    state = PlayerState(
        player_id=1,
        skills={"magic": SkillState(level=87, xp=None, source=Source.RUNELITE, observed_at=now)},
        last_sync_at=now,
    )
    selection = RoadmapSelection(weights={"main_nh": 1.0})

    first = recommend_run(state, selection, content, content.profile, now=now)
    second = recommend_run(state, selection, content, content.profile, now=now)

    assert first.primary
    assert first == second
    assert all(entry.estimate is not None for entry in first.primary)
