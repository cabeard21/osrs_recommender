"""§9.7's ``max_primary_entries`` — the primary list's tail cut.

The cut exists because §9.8 describes a *list* and the corpus is about to stop being eight
candidates. Everything here is about proving it is only ever a tail cut: it must not
reorder, must not promote, must not reach the deferred or blocked collections, and must not
be visible to anything that scores.

The synthetic corpus swaps ``Content.candidates`` and keeps every other part of the shipped
corpus, so capabilities, roadmaps and training methods are the real ones. A ranking test
needs real weights to rank against.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime

import pytest

from tracker.content.loader import Content
from tracker.content.schema import Candidate, ScoringProfile
from tracker.domain.types import MilestoneState, PlayerState, RoadmapSelection
from tracker.recommendations.engine import recommend_run

#: Comfortably past any cap under test, so "the corpus is bigger than the list" is the
#: situation being exercised rather than an accident of size.
CORPUS_SIZE = 200


def _woodcutting_band(index: int) -> Candidate:
    """One open candidate with a real §8 estimate and a score of its own.

    Woodcutting because the shipped corpus authors no method for it: every band falls back
    to §8.2's conservative default, so the estimates differ only by the target level and the
    resulting ranking is a clean function of the index.
    """
    target = 2 + index % 97
    return Candidate.model_validate(
        {
            "id": f"synthetic_woodcutting_{index:03d}",
            "name": f"Train Woodcutting to {target} (#{index})",
            "kind": "skill_training",
            "advances": {},
            "completion": {"skill": {"woodcutting": target}},
        }
    )


@pytest.fixture
def big_content(seed_content: Content) -> Content:
    """The shipped corpus with its candidates replaced by ``CORPUS_SIZE`` synthetic ones."""
    candidates = {
        candidate.id: candidate for candidate in map(_woodcutting_band, range(CORPUS_SIZE))
    }
    return dataclasses.replace(seed_content, candidates=candidates)


@pytest.fixture
def selection(seed_content: Content) -> RoadmapSelection:
    return RoadmapSelection(weights=dict.fromkeys(seed_content.roadmaps, 1.0))


@pytest.fixture
def state(player: Callable[..., PlayerState]) -> PlayerState:
    return player(skills={"woodcutting": 1})


def _capped(profile: ScoringProfile, limit: int) -> ScoringProfile:
    return profile.model_copy(update={"max_primary_entries": limit})


def test_primary_list_is_capped(
    big_content: Content,
    profile: ScoringProfile,
    state: PlayerState,
    selection: RoadmapSelection,
    now: datetime,
) -> None:
    run = recommend_run(state, selection, big_content, _capped(profile, 12), now=now)

    assert len(run.primary) == 12


def test_cap_only_removes_the_tail(
    big_content: Content,
    profile: ScoringProfile,
    state: PlayerState,
    selection: RoadmapSelection,
    now: datetime,
) -> None:
    """The capped list is a prefix of the uncapped one — never a reordering of it.

    This is the invariant that keeps the cut out of the scoring layer. If truncation ever
    moved earlier in the pipeline, a candidate's presence would start to depend on how many
    others there were rather than on its own score, and this comparison would break.
    """
    uncapped = recommend_run(
        state, selection, big_content, _capped(profile, CORPUS_SIZE), now=now
    ).primary
    capped = recommend_run(state, selection, big_content, _capped(profile, 5), now=now).primary

    assert [entry.candidate_id for entry in capped] == [
        entry.candidate_id for entry in uncapped[:5]
    ]


def test_cap_does_not_change_the_scores_it_keeps(
    big_content: Content,
    profile: ScoringProfile,
    state: PlayerState,
    selection: RoadmapSelection,
    now: datetime,
) -> None:
    """A survivor's score is what it would have been in an uncapped run.

    ``leverage`` and ``method_unlock`` are normalized across the candidate set (§10.6), so a
    cut applied before scoring would silently renormalize both. Comparing the numbers, not
    just the order, is what detects that.
    """
    uncapped = recommend_run(
        state, selection, big_content, _capped(profile, CORPUS_SIZE), now=now
    ).primary
    capped = recommend_run(state, selection, big_content, _capped(profile, 5), now=now).primary

    assert [entry.score for entry in capped] == [entry.score for entry in uncapped[:5]]


def test_cap_does_not_reach_blocked_entries(
    seed_content: Content,
    profile: ScoringProfile,
    player: Callable[..., PlayerState],
    selection: RoadmapSelection,
    now: datetime,
) -> None:
    """§16.2's *"surfaced separately"* list is not part of §9.8's list, so the cut misses it.

    A fresh account blocks most of the shipped corpus, which is what makes this observable
    at a cap of one.
    """
    state = player(skills={"attack": 1}, scanned=False, synced=False)

    one = recommend_run(state, selection, seed_content, _capped(profile, 1), now=now)
    many = recommend_run(state, selection, seed_content, _capped(profile, 99), now=now)

    assert len(one.primary) <= 1
    assert one.blocked == many.blocked
    assert one.deferred_refreshers == many.deferred_refreshers


def test_cap_runs_after_the_refresher_policy(
    seed_content: Content,
    profile: ScoringProfile,
    player: Callable[..., PlayerState],
    milestone_state: Callable[..., MilestoneState],
    selection: RoadmapSelection,
    now: datetime,
) -> None:
    """A refresher deferred by §9.8 stays deferred, and is never resurrected by the cut.

    The two rules compose in one direction only: the list policy decides *which* entries the
    primary list may hold, and the cut then shortens what is left. Running them the other way
    round would let a small cap change how many refreshers the Practice view receives.
    """
    stale = [
        milestone_state(milestone.id, practiced_days_ago=400)
        for milestone in seed_content.milestones.values()
        if milestone.practice_group
    ]
    state = player(skills={"attack": 99}, milestones=stale)

    one = recommend_run(state, selection, seed_content, _capped(profile, 1), now=now)
    many = recommend_run(state, selection, seed_content, _capped(profile, 99), now=now)

    assert one.deferred_refreshers == many.deferred_refreshers
