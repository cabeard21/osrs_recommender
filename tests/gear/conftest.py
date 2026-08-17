"""Builders for §23's gear projection.

Fixtures returning callables, never importable module functions — sibling conftests share
one flat module namespace under ``--import-mode=importlib``, so a module-level ``make_item``
here would collide with one anywhere else in ``tests/``.

**Every default is the unobserved state.** ``make_player_state`` scans no container and
observes no item, so a test that does not say otherwise is testing an account nobody has
looked at. That is the state §4.5 is about, and making it the default is what stops a test
from passing because it quietly granted itself evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import Requirement
from tracker.content.requirements import parse as parse_requirement
from tracker.content.schema import (
    Item,
    KappaPresets,
    Quest,
    ScoringProfile,
    ScoringWeights,
    Skill,
)
from tracker.domain.types import (
    Container,
    ItemObservation,
    PlayerState,
    QuestStatus,
    SkillState,
    Source,
)

#: A fixed observation time. Nothing in §23 reads a clock, but ``SkillState`` requires one.
OBSERVED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

PROFILE = ScoringProfile(
    version=1,
    kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
    weights=ScoringWeights(
        pvp_value=1.0,
        leverage=0.8,
        proximity=0.6,
        effort_decay=0.6,
        cost_decay=0.4,
        method_unlock=0.1,
    ),
)

#: Enough of the skill registry for a gear gate to resolve against.
ALL_SKILLS: tuple[str, ...] = (
    "attack",
    "strength",
    "defence",
    "ranged",
    "prayer",
    "magic",
    "hitpoints",
    "agility",
    "hunter",
)


@pytest.fixture
def requirement() -> Callable[[Any], Requirement]:
    """Parse a §10.2 mapping into a tree, so a test reads the way the corpus is written."""

    def build(raw: Any) -> Requirement:
        return parse_requirement(raw)

    return build


@pytest.fixture
def make_item() -> Callable[..., Item]:
    def build(
        item_id: str,
        *,
        name: str | None = None,
        numeric_id: int | None = None,
        variant_item_ids: tuple[int, ...] = (),
        slot: str = "weapon",
        style: str = "melee",
        tier: int = 1,
        requires: Any = None,
        gate_unknown: bool = False,
        acquisition: str | None = "tradeable",
        acquired_from: str | None = None,
    ) -> Item:
        # `acquisition` defaults to "tradeable" rather than to the unobserved `None` every
        # other field here defaults to, and the exception is deliberate. These fixtures exist
        # to exercise the *gate* and *ownership* axes; leaving acquisition unstated would make
        # every one of them a test of the third axis too, an unrelated assertion riding along
        # in forty cases. A test that means to exercise acquisition says so — which is also
        # what makes those tests readable.
        return Item.model_validate(
            {
                "id": item_id,
                "name": name or item_id.replace("_", " ").capitalize(),
                "item_id": numeric_id,
                "variant_item_ids": variant_item_ids,
                "slot": slot,
                "style": style,
                "tier": tier,
                "requires": requires,
                "gate_unknown": gate_unknown,
                "acquisition": acquisition,
                "acquired_from": acquired_from,
            }
        )

    return build


@pytest.fixture
def make_content() -> Callable[..., Content]:
    def build(
        *,
        items: Sequence[Item] = (),
        skills: Sequence[str] = ALL_SKILLS,
        quests: Mapping[str, str] | None = None,
    ) -> Content:
        return Content(
            profile=PROFILE,
            items={item.id: item for item in items},
            skills={skill_id: Skill(id=skill_id, name=skill_id.title()) for skill_id in skills},
            quests={
                quest_id: Quest(id=quest_id, name=name) for quest_id, name in (quests or {}).items()
            },
        )

    return build


@pytest.fixture
def make_player_state() -> Callable[..., PlayerState]:
    """Defaults are the *unobserved* states: nothing scanned, nothing seen (§4.5)."""

    def build(
        *,
        levels: Mapping[str, int] | None = None,
        holds: Sequence[int] = (),
        scanned: Sequence[Container] = (),
        quests: Mapping[str, QuestStatus] | None = None,
    ) -> PlayerState:
        return PlayerState(
            player_id=1,
            skills={
                skill: SkillState(
                    level=level, xp=None, source=Source.RUNELITE, observed_at=OBSERVED_AT
                )
                for skill, level in (levels or {}).items()
            },
            observed_items={
                numeric_id: ItemObservation(
                    item_id=numeric_id,
                    quantity=1,
                    containers=frozenset({Container.BANK}),
                    observed_at=OBSERVED_AT,
                )
                for numeric_id in holds
            },
            container_scans=dict.fromkeys(scanned, OBSERVED_AT),
            quests=dict(quests or {}),
        )

    return build


@pytest.fixture
def every_container() -> tuple[Container, ...]:
    """The scan state that turns *unknown* into *not held* — and nothing short of it."""
    return tuple(Container)
