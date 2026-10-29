"""Shared content builders and frozen-account searches for factual gear tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from functools import cache
from typing import Any

import pytest

from tools.benchmark_gear_search_quality import benchmark_case
from tracker.content.loader import Content
from tracker.content.schema import Item, Quest, Skill
from tracker.gear.optimizer import optimize

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


@pytest.fixture(scope="session")
def frozen_account_result() -> Callable[..., dict[str, Any]]:
    """Reuse unmodified frozen searches per worker, isolating each test's response."""

    @cache
    def run(name: str, thorough: bool) -> dict[str, Any]:
        case = benchmark_case(name)
        return optimize(
            case.snapshot,
            case.request,
            case.catalog,
            case.content,
            case.prices,
            case.at,
            local_refinement=thorough,
        )

    def result(name: str, *, thorough: bool = False) -> dict[str, Any]:
        return deepcopy(run(name, thorough))

    return result


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
            items={item.id: item for item in items},
            skills={skill_id: Skill(id=skill_id, name=skill_id.title()) for skill_id in skills},
            quests={
                quest_id: Quest(id=quest_id, name=name) for quest_id, name in (quests or {}).items()
            },
        )

    return build
