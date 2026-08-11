"""Builders for the progression tests.

Most of these tests want a corpus containing exactly one capability and nothing else, so
that a failure names the rule it broke rather than an interaction three files away. The
shipped corpus is available too, as ``seed_content``, for the tests that assert §4.4's
worked examples come out of the real content.

The builders are handed out as **fixtures returning callables** rather than as importable
module functions. Sibling test directories belong to other steps, and a
``from conftest import ...`` resolves through one flat module namespace shared with every
one of them; a fixture is looked up per directory and cannot collide.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tracker.content.loader import Content
from tracker.content.schema import (
    Capability,
    Item,
    KappaPresets,
    Milestone,
    Quest,
    ScoringProfile,
    ScoringWeights,
    Skill,
)
from tracker.content.validate import load_and_validate
from tracker.domain.types import (
    Container,
    ItemObservation,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    SkillState,
    Source,
    Tri,
)

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: A fixed clock. Every age in these tests is expressed as ``NOW - timedelta(...)``, so no
#: test depends on when it runs — the engine takes ``now`` as an argument (§16.1).
NOW = datetime(2026, 8, 4, tzinfo=UTC)

PROFILE = ScoringProfile(
    version=1,
    kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
    weights=ScoringWeights(
        pvp_value=1.0,
        leverage=0.8,
        proximity=0.6,
        effort_decay=0.7,
        cost_decay=0.5,
        method_unlock=0.0,
    ),
)


def _index(objects: Iterable[Any]) -> dict[str, Any]:
    return {obj.id: obj for obj in objects}


def _build_content(
    *,
    capabilities: Sequence[Capability] = (),
    skills: Sequence[Skill] = (),
    quests: Sequence[Quest] = (),
    items: Sequence[Item] = (),
    milestones: Sequence[Milestone] = (),
    profile: ScoringProfile = PROFILE,
) -> Content:
    return Content(
        profile=profile,
        capabilities=_index(capabilities),
        skills=_index(skills),
        quests=_index(quests),
        items=_index(items),
        milestones=_index(milestones),
    )


def _skill_at(level: int, *, observed_at: datetime = NOW) -> SkillState:
    return SkillState(level=level, xp=None, source=Source.RUNELITE, observed_at=observed_at)


def _owned(
    item_id: int,
    *,
    containers: Iterable[Container] = (Container.BANK,),
    observed_at: datetime = NOW,
) -> ItemObservation:
    return ItemObservation(
        item_id=item_id, quantity=1, containers=frozenset(containers), observed_at=observed_at
    )


def _scans(
    *, days_ago: int = 0, containers: Iterable[Container] = tuple(Container)
) -> dict[Container, datetime]:
    return {container: NOW - timedelta(days=days_ago) for container in containers}


def _milestone_state(
    key: str,
    *,
    achieved: bool = True,
    attested: Tri = Tri.SATISFIED,
    kind: MilestoneKind = MilestoneKind.SELF_ATTESTED,
    class_: MilestoneClass = MilestoneClass.EXECUTION,
    practiced_days_ago: int | None = 0,
) -> MilestoneState:
    return MilestoneState(
        key=key,
        achieved=achieved,
        attested=attested,
        kind=kind,
        class_=class_,
        last_practiced_at=(
            None if practiced_days_ago is None else NOW - timedelta(days=practiced_days_ago)
        ),
    )


@pytest.fixture
def build_content() -> Callable[..., Content]:
    """Assemble a :class:`Content` from just the objects a test names."""
    return _build_content


@pytest.fixture(scope="session")
def seed_content() -> Content:
    """The real ``content/`` corpus — the fixture every downstream engine test runs on."""
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def profile() -> ScoringProfile:
    return PROFILE


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def skill_at() -> Callable[..., SkillState]:
    return _skill_at


@pytest.fixture
def owned() -> Callable[..., ItemObservation]:
    """An observation of one item, in the bank unless told otherwise."""
    return _owned


@pytest.fixture
def scans() -> Callable[..., dict[Container, datetime]]:
    """Container scans — all three containers unless told otherwise (§6.5)."""
    return _scans


@pytest.fixture
def milestone_state() -> Callable[..., MilestoneState]:
    return _milestone_state
