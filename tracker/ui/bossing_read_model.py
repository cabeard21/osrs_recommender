"""Pure player-facing projection of the authored PvM bossing guide."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from tracker.content.loader import Content
from tracker.content.schema import RoadmapGuide
from tracker.domain.types import LeafRef, PlayerState, Tri
from tracker.progression.evaluate import EvalResult, Evaluator


class BossingStatus(StrEnum):
    """The four actions an account can take on a guide entry."""

    LOCKED = "locked"
    BUILDING_TOWARD = "building_toward"
    READY = "ready"
    SYNC_NEEDED = "sync_needed"


@dataclass(frozen=True, slots=True)
class BossingPreparationRow:
    id: str
    name: str
    status: BossingStatus
    blockers: tuple[LeafRef, ...]
    unknowns: tuple[LeafRef, ...]
    candidate_ids: tuple[str, ...]
    informational: bool


@dataclass(frozen=True, slots=True)
class BossingEncounterRow:
    id: str
    name: str
    status: BossingStatus
    readiness_fraction: float
    access_blockers: tuple[LeafRef, ...]
    access_unknowns: tuple[LeafRef, ...]
    recommendation_blockers: tuple[LeafRef, ...]
    recommendation_unknowns: tuple[LeafRef, ...]
    mechanics: tuple[str, ...]
    rewards: tuple[str, ...]
    wiki_url: str
    tier_id: str
    tier_order: int
    source_order: int


@dataclass(frozen=True, slots=True)
class BossingTierRow:
    id: str
    name: str
    preparation: tuple[BossingPreparationRow, ...]
    encounters: tuple[BossingEncounterRow, ...]
    ready_count: int
    building_toward_count: int


@dataclass(frozen=True, slots=True)
class BossingGuideView:
    id: str
    name: str
    tiers: tuple[BossingTierRow, ...]
    ready_count: int
    building_toward_count: int
    closest_next: BossingEncounterRow | None
    default_expanded_tier_id: str | None


def project_bossing_guide(
    guide: RoadmapGuide, state: PlayerState, content: Content
) -> BossingGuideView:
    """Evaluate a guide without database access, mutation, ranking, or clock reads."""
    evaluator = Evaluator(state, content)
    tiers = tuple(
        _project_tier(tier, tier_order, evaluator) for tier_order, tier in enumerate(guide.tiers)
    )
    encounters = tuple(encounter for tier in tiers for encounter in tier.encounters)
    # A sync-needed row is not actionable yet; presenting it as the next boss merely
    # because it has no authored recommendations would turn missing evidence into advice.
    pending = tuple(
        row
        for row in encounters
        if row.status in (BossingStatus.LOCKED, BossingStatus.BUILDING_TOWARD)
    )
    closest = min(
        pending,
        key=lambda row: (-row.readiness_fraction, row.tier_order, row.source_order),
        default=None,
    )
    ready_tiers = tuple(tier for tier in tiers if tier.ready_count)
    default_tier = ready_tiers[-1].id if ready_tiers else (tiers[0].id if tiers else None)
    return BossingGuideView(
        id=guide.id,
        name=guide.name,
        tiers=tiers,
        ready_count=sum(tier.ready_count for tier in tiers),
        building_toward_count=sum(tier.building_toward_count for tier in tiers),
        closest_next=closest,
        default_expanded_tier_id=default_tier,
    )


def _project_tier(tier: Any, tier_order: int, evaluator: Evaluator) -> BossingTierRow:
    preparation = tuple(_project_preparation(step, evaluator) for step in tier.preparation)
    encounters = tuple(
        _project_encounter(encounter, tier.id, tier_order, source_order, evaluator)
        for source_order, encounter in enumerate(tier.encounters)
    )
    return BossingTierRow(
        id=tier.id,
        name=tier.name,
        preparation=preparation,
        encounters=encounters,
        ready_count=sum(row.status is BossingStatus.READY for row in encounters),
        building_toward_count=sum(
            row.status is BossingStatus.BUILDING_TOWARD for row in encounters
        ),
    )


def _project_preparation(step: Any, evaluator: Evaluator) -> BossingPreparationRow:
    requirement = _first_attr(step, "completion", "requirements", "requires")
    result = _evaluate_optional(requirement, evaluator)
    return BossingPreparationRow(
        id=step.id,
        name=getattr(step, "label", getattr(step, "name", step.id)),
        status=_single_status(result),
        blockers=result.blockers,
        unknowns=result.unknowns,
        candidate_ids=tuple(getattr(step, "candidate_ids", ())),
        informational=bool(getattr(step, "informational", requirement is None)),
    )


def _project_encounter(
    encounter: Any,
    tier_id: str,
    tier_order: int,
    source_order: int,
    evaluator: Evaluator,
) -> BossingEncounterRow:
    access = _evaluate_optional(
        _first_attr(encounter, "access_requirements", "access", "requires"), evaluator
    )
    recommendations = _evaluate_optional(
        _first_attr(
            encounter,
            "recommended_requirements",
            "recommendations",
            "recommended",
        ),
        evaluator,
    )
    return BossingEncounterRow(
        id=encounter.id,
        name=encounter.name,
        status=_encounter_status(access, recommendations),
        readiness_fraction=(
            1.0 if recommendations.total_leaves == 0 else recommendations.unlock_fraction
        ),
        access_blockers=access.blockers,
        access_unknowns=access.unknowns,
        recommendation_blockers=recommendations.blockers,
        recommendation_unknowns=recommendations.unknowns,
        mechanics=tuple(getattr(encounter, "mechanics", ())),
        rewards=tuple(getattr(encounter, "rewards", ())),
        wiki_url=getattr(encounter, "wiki_url", ""),
        tier_id=tier_id,
        tier_order=tier_order,
        source_order=source_order,
    )


def _evaluate_optional(requirement: Any | None, evaluator: Evaluator) -> EvalResult:
    if requirement is None:
        return EvalResult(value=Tri.SATISFIED)
    return evaluator.evaluate(requirement)


def _single_status(result: EvalResult) -> BossingStatus:
    if result.value is Tri.SATISFIED:
        return BossingStatus.READY
    if result.value is Tri.UNSATISFIED:
        return BossingStatus.BUILDING_TOWARD
    return BossingStatus.SYNC_NEEDED


def _encounter_status(access: EvalResult, recommendations: EvalResult) -> BossingStatus:
    if access.value is Tri.UNSATISFIED:
        return BossingStatus.LOCKED
    if access.value is Tri.UNKNOWN:
        return BossingStatus.SYNC_NEEDED
    if recommendations.value is Tri.UNSATISFIED:
        return BossingStatus.BUILDING_TOWARD
    if recommendations.value is Tri.UNKNOWN:
        return BossingStatus.SYNC_NEEDED
    return BossingStatus.READY


def _first_attr(value: Any, *names: str) -> Any | None:
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


__all__ = [
    "BossingEncounterRow",
    "BossingGuideView",
    "BossingPreparationRow",
    "BossingStatus",
    "BossingTierRow",
    "project_bossing_guide",
]
