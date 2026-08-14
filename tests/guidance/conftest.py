"""Builders for the §21.2 context-assembly tests.

Synthetic corpora throughout, for the reason ``tests/estimation/conftest.py`` gives: the
shipped content is enough to demonstrate the feature and not enough to *test* it. The
interesting cases here — a twenty-three-skill account whose task names two skills, a method
whose band does not overlap, an account whose type nobody has recorded — either do not occur
in ``content/`` or occur only by accident and would stop occurring the moment it is edited.

Builders are fixtures returning callables, matching every other directory: ``tests/`` has no
``__init__.py``, so sibling conftests share one flat module namespace and an importable
helper here could collide with another step's.
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
    Candidate,
    Item,
    KappaPresets,
    LevelRange,
    MethodDetail,
    Quest,
    Roadmap,
    ScoringProfile,
    ScoringWeights,
    Skill,
    TrainingMethod,
)
from tracker.domain.types import (
    AccountType,
    BandEstimate,
    CandidateKind,
    Confidence,
    Consequences,
    Estimate,
    LeafRef,
    PlayerState,
    QuestStatus,
    Recommendation,
    RoadmapSelection,
    SkillState,
    Source,
    UnlockState,
)

#: A fixed observation time. Nothing in §21.2 reads a clock, but ``SkillState`` requires one.
OBSERVED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

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

#: The twenty-three OSRS skills, so a test can assert that a task naming two of them does not
#: put the other twenty-one in the prompt. The point of §21.2 is the *slice*.
ALL_SKILLS: tuple[str, ...] = (
    "attack",
    "strength",
    "defence",
    "ranged",
    "prayer",
    "magic",
    "runecraft",
    "construction",
    "hitpoints",
    "agility",
    "herblore",
    "thieving",
    "crafting",
    "fletching",
    "slayer",
    "hunter",
    "mining",
    "smithing",
    "fishing",
    "cooking",
    "firemaking",
    "woodcutting",
    "farming",
)


@pytest.fixture
def observed_at() -> datetime:
    """The fixed clock, as a fixture — sibling conftests may not be imported directly."""
    return OBSERVED_AT


@pytest.fixture
def requirement() -> Callable[..., Requirement]:
    """Parse a §10.2 requirement from its YAML mapping form."""

    def build(raw: Any) -> Requirement:
        return parse_requirement(raw)

    return build


@pytest.fixture
def make_skill_state() -> Callable[..., SkillState]:
    def build(level: int, *, xp: int | None = 0, source: Source = Source.RUNELITE) -> SkillState:
        return SkillState(level=level, xp=xp, source=source, observed_at=OBSERVED_AT)

    return build


@pytest.fixture
def make_player_state(make_skill_state: Callable[..., SkillState]) -> Callable[..., PlayerState]:
    """A player state whose defaults are the *unobserved* ones (§4.5).

    ``account_type`` and ``members`` default to ``None`` and ``container_scans`` to empty on
    purpose: those are the states the rendering must not collapse, so they are what a test
    gets unless it asks for something else.
    """

    def build(
        *,
        player_id: int = 1,
        skills: Mapping[str, int] | None = None,
        unranked: Sequence[str] = (),
        quests: Mapping[str, QuestStatus] | None = None,
        unlocks: Mapping[str, UnlockState] | None = None,
        account_type: AccountType | None = None,
        members: bool | None = None,
        combat_level: int | None = None,
        quest_points: int | None = None,
        **kwargs: Any,
    ) -> PlayerState:
        levels = dict(skills or {})
        built = {
            skill_id: make_skill_state(level, xp=None if skill_id in unranked else level * 100)
            for skill_id, level in levels.items()
        }
        return PlayerState(
            player_id=player_id,
            skills=built,
            quests=dict(quests or {}),
            unlocks=dict(unlocks or {}),
            account_type=account_type,
            members=members,
            combat_level=combat_level,
            quest_points=quest_points,
            **kwargs,
        )

    return build


@pytest.fixture
def make_method() -> Callable[..., TrainingMethod]:
    def build(
        method_id: str,
        *,
        skill: str,
        from_level: int = 1,
        to_level: int = 99,
        xp_per_hour: int = 10_000,
        cost_per_hour_gp: int = 0,
        name: str | None = None,
        requires: Requirement | None = None,
        detail: MethodDetail | None = None,
    ) -> TrainingMethod:
        return TrainingMethod(
            id=method_id,
            name=name or method_id.replace("_", " ").title(),
            skill=skill,
            xp_per_hour=xp_per_hour,
            cost_per_hour_gp=cost_per_hour_gp,
            level_range=LevelRange(min=from_level, max=to_level),
            requires=requires,
            detail=detail or MethodDetail(),
        )

    return build


@pytest.fixture
def make_candidate(requirement: Callable[..., Requirement]) -> Callable[..., Candidate]:
    def build(
        candidate_id: str,
        *,
        name: str | None = None,
        kind: CandidateKind = CandidateKind.SKILL_TRAINING,
        completion: Any = None,
        requires: Any = None,
        grants_facts: Any = None,
    ) -> Candidate:
        return Candidate(
            id=candidate_id,
            name=name or candidate_id.replace("_", " ").title(),
            kind=kind,
            completion=requirement(completion or {"skill": {"slayer": 10}}),
            requires=requirement(requires) if requires is not None else None,
            grants_facts=requirement(grants_facts) if grants_facts is not None else None,
        )

    return build


@pytest.fixture
def make_content() -> Callable[..., Content]:
    def build(
        *,
        candidates: Sequence[Candidate] = (),
        methods: Sequence[TrainingMethod] = (),
        skills: Sequence[str] = ALL_SKILLS,
        quests: Mapping[str, str] | None = None,
        roadmaps: Mapping[str, str] | None = None,
        items: Sequence[Item] = (),
    ) -> Content:
        return Content(
            profile=PROFILE,
            items={item.id: item for item in items},
            skills={skill_id: Skill(id=skill_id, name=skill_id.title()) for skill_id in skills},
            quests={
                quest_id: Quest(id=quest_id, name=name) for quest_id, name in (quests or {}).items()
            },
            candidates={candidate.id: candidate for candidate in candidates},
            training_methods={method.id: method for method in methods},
            roadmaps={
                roadmap_id: Roadmap(id=roadmap_id, name=name, capabilities={"ice_barrage_nh": 1.0})
                for roadmap_id, name in (roadmaps or {}).items()
            },
        )

    return build


@pytest.fixture
def make_recommendation() -> Callable[..., Recommendation]:
    def build(
        candidate_id: str = "train_slayer_10",
        *,
        name: str = "Train Slayer to 10",
        kind: CandidateKind = CandidateKind.SKILL_TRAINING,
        score: float = 0.5,
        reason: str = "quick to finish",
        hours: float | None = 2.0,
        gp: int | None = 0,
        confidence: Confidence = Confidence.MEDIUM,
        bands: Sequence[BandEstimate] = (),
        blocked: bool = False,
        unknown_gate: bool = False,
        blockers: Sequence[LeafRef] = (),
        consequences: Consequences | None = None,
    ) -> Recommendation:
        estimate = (
            None
            if hours is None and gp is None and not bands
            else Estimate(hours=hours, gp=gp, confidence=confidence, bands=tuple(bands))
        )
        return Recommendation(
            candidate_id=candidate_id,
            name=name,
            kind=kind,
            score=score,
            reason=reason,
            estimate=estimate,
            blocked=blocked,
            unknown_gate=unknown_gate,
            blockers=tuple(blockers),
            consequences=consequences or Consequences(),
        )

    return build


@pytest.fixture
def no_roadmaps() -> RoadmapSelection:
    return RoadmapSelection()
