"""Invariants shared by factual account, requirement, and price services."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tracker.domain.types import (
    AccountType,
    Confidence,
    Container,
    GpSensitivity,
    PriceSourceLayer,
    QuestStatus,
    SkillState,
    Source,
    Tri,
    UnlockState,
)


@pytest.mark.parametrize("value", list(Tri))
def test_tri_cannot_be_coerced_to_boolean(value: Tri) -> None:
    with pytest.raises(TypeError, match="no truth value"):
        bool(value)


def test_fact_states_preserve_unknown_and_available() -> None:
    assert Tri.from_bool(True) is Tri.SATISFIED
    assert Tri.from_bool(False) is Tri.UNSATISFIED
    assert UnlockState.UNKNOWN is not UnlockState.AVAILABLE
    assert QuestStatus.UNKNOWN is not QuestStatus.NOT_STARTED
    assert Container.BANK is not Container.INVENTORY


def test_price_confidence_and_provenance_are_distinct() -> None:
    assert Confidence.LOW < Confidence.MEDIUM < Confidence.HIGH
    assert PriceSourceLayer.UNKNOWN is not PriceSourceLayer.CACHED


def test_retained_account_preference_and_skill_fact() -> None:
    assert GpSensitivity.NORMAL.value == "normal"
    assert AccountType.IRONMAN.value == "ironman"
    observed = datetime(2026, 8, 4, tzinfo=UTC)
    skill = SkillState(level=70, xp=None, source=Source.RUNELITE, observed_at=observed)
    assert skill.xp is None
    assert skill.observed_at == observed
