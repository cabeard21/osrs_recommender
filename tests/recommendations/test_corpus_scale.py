"""What one scoring pass costs as the corpus grows past hand-authored size.

§9.4's ``method_unlock`` (A30) asks an O(n²) question — *"how long would Y take, if X were
done?"* for every ordered pair — and :class:`~tracker.recommendations.facts.EstimateOracle`
answers it with two memo layers rather than by asking less. That trade was sized against a
corpus of eight candidates. Generated quest, diary and skill-band content takes it to a few
hundred, so the quadratic is worth a measurement rather than an assumption.

Measured while writing this: ~0.2s at 200 candidates, ~0.7s at 400, ~2.8s at 800. Quadratic,
with a constant small enough that the realistic corpus is comfortable, and a run happens once
per sync rather than once per page view.

**The assertion counts §8 sizings, not seconds.** A wall-clock budget was tried first and was
wrong for this job: it passed alone and failed inside the full suite purely because another
build was running, which is how a guard becomes noise and then gets muted. The claim actually
worth defending is :class:`EstimateOracle`'s own — *"``(n + 1)`` worlds and at most ``n·(n + 1)``
sizings"* — and that is a property of the algorithm, identical on every machine.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest

import tracker.recommendations.facts as facts
from tracker.content.loader import Content
from tracker.content.schema import Candidate, ScoringProfile
from tracker.domain.types import PlayerState, RoadmapSelection
from tracker.recommendations.engine import recommend_run

#: The size a generated corpus is expected to reach: ~211 quests, ~140 skill bands, ~50
#: diaries. Measuring at the target rather than at a round number keeps the guard honest.
TARGET_CORPUS = 400

#: Half the corpus grants facts, so it opens a counterfactual world; half is merely sizeable.
GRANTING = TARGET_CORPUS // 2


def _granting(index: int) -> Candidate:
    """A quest-shaped candidate: it grants facts, so it opens a world of its own."""
    return Candidate.model_validate(
        {
            "id": f"scale_quest_{index:03d}",
            "name": f"Quest {index}",
            "kind": "quest",
            "advances": {},
            "completion": {"quest": "desert_treasure_i"},
            "grants_facts": {"skill": {"woodcutting": 2 + index % 90}},
        }
    )


def _sized(index: int) -> Candidate:
    """A band-shaped candidate: it grants nothing, but §8 can size it, so it is a real
    subject for every other candidate's counterfactual."""
    return Candidate.model_validate(
        {
            "id": f"scale_band_{index:03d}",
            "name": f"Band {index}",
            "kind": "skill_training",
            "advances": {},
            "completion": {"skill": {"magic": 2 + index % 97}},
        }
    )


@pytest.fixture
def target_content(seed_content: Content) -> Content:
    candidates = [_granting(index) for index in range(GRANTING)]
    candidates += [_sized(index) for index in range(TARGET_CORPUS - GRANTING)]
    return dataclasses.replace(
        seed_content, candidates={candidate.id: candidate for candidate in candidates}
    )


@pytest.fixture
def sizings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], int]]:
    """Counts real §8 estimates — the work both of the oracle's memo layers exist to avoid.

    Patched at ``facts.estimate`` rather than at its definition so only the oracle's calls are
    counted, and so the count is of *cache misses*: a memoized answer never reaches here.
    """
    calls = 0
    original = facts.estimate

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(facts, "estimate", counting)
    yield lambda: calls


def test_a_generated_sized_corpus_stays_inside_the_oracles_bound(
    target_content: Content,
    profile: ScoringProfile,
    player: Callable[..., PlayerState],
    seed_content: Content,
    sizings: Callable[[], int],
    now: datetime,
) -> None:
    state = player(skills={"magic": 1, "woodcutting": 1})
    selection = RoadmapSelection(weights=dict.fromkeys(seed_content.roadmaps, 1.0))

    run = recommend_run(state, selection, target_content, profile, now=now)

    # One world per distinct grants_facts tree, plus the baseline world (§9.4, A30).
    bound = (GRANTING + 1) * TARGET_CORPUS
    assert len(run.primary) == profile.max_primary_entries
    assert sizings() <= bound, (
        f"{TARGET_CORPUS} candidates needed {sizings()} §8 sizings, past EstimateOracle's "
        f"documented ceiling of {bound}. A memo layer is missing or its key no longer "
        "collapses the repeats it was written to collapse."
    )

    # The ceiling alone would also be satisfied by an implementation that quietly got much
    # worse, so the second half asserts the memo layers are earning their keep: naively every
    # ordered pair is a sizing (n²), and the measured figure is a quarter of that — 40,400 for
    # 400 candidates, stable as a fraction across 100, 200 and 400.
    assert sizings() < TARGET_CORPUS * TARGET_CORPUS / 2
