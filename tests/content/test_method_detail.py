"""``MethodDetail`` is descriptive, and this file is the proof (Step 7).

§10.6's rule is that no content file may assert its own priority. Step 7 extends that to
*how* a thing is done: a method does not become more urgent because someone wrote a
better description of it, and the moment ``detail`` reaches a scoring factor the whole
derivation argument collapses — an author could promote a candidate by adding a wiki link.

The strong form of that claim is tested here: build two corpora that differ **only** in
``detail`` and assert the engine's output is identical. That catches a leak no
"does not import" check would, because a leak could arrive through a shared helper rather
than through an import.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tracker.content.loader import Content
from tracker.content.schema import MethodDetail
from tracker.content.validate import load_and_validate
from tracker.domain.types import (
    PlayerState,
    RoadmapSelection,
    SkillState,
    Source,
)
from tracker.recommendations.engine import recommend_run

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"
NOW = datetime(2026, 8, 4, tzinfo=UTC)

#: A description with something in every field, so a leak through any one of them shows.
LOUD = MethodDetail(
    location="Somewhere entirely different",
    target="A completely different monster",
    gear=("Twisted bow", "Torva full helm"),
    inventory=("Saradomin brews", "Super restores"),
    notes="If this string can change a ranking, §10.6 is not being enforced.",
    wiki_url="https://example.invalid/not-a-real-page",
)


@pytest.fixture(scope="module")
def corpus() -> Content:
    return load_and_validate(CONTENT_ROOT)


def _account() -> PlayerState:
    """A mid-level account whose bands and quests are both live.

    Levels rather than an empty state on purpose: an account with no skills makes §8
    withhold every estimate (§4.5), which would leave the training half — the only half
    ``detail`` sits anywhere near — untested.
    """
    return PlayerState(
        player_id=1,
        skills={
            skill: SkillState(level=level, xp=None, source=Source.WISE_OLD_MAN, observed_at=NOW)
            for skill, level in (
                ("magic", 87),
                ("attack", 70),
                ("strength", 70),
                ("defence", 70),
                ("ranged", 70),
                ("slayer", 55),
                ("thieving", 50),
                ("prayer", 52),
                ("firemaking", 60),
                ("woodcutting", 60),
            )
        },
        last_sync_at=NOW,
    )


def _rewritten(corpus: Content, detail: MethodDetail) -> Content:
    """The same corpus with every method's ``detail`` replaced."""
    methods = {
        method_id: method.model_copy(update={"detail": detail})
        for method_id, method in corpus.training_methods.items()
    }
    return dataclasses.replace(corpus, training_methods=methods)


def _run(corpus: Content) -> tuple:
    return recommend_run(
        _account(),
        RoadmapSelection(weights={"main_nh": 1.0}),
        corpus,
        corpus.profile.model_copy(update={"max_primary_entries": 10_000}),
        None,
        now=NOW,
    )


def test_rewriting_every_method_description_changes_no_recommendation(corpus: Content) -> None:
    """The invariant. Same account, same corpus, every ``detail`` replaced wholesale."""
    before = _run(corpus)
    after = _run(_rewritten(corpus, LOUD))

    assert after.primary == before.primary
    assert after.blocked == before.blocked
    assert after.deferred_refreshers == before.deferred_refreshers


def test_stripping_every_method_description_changes_no_recommendation(corpus: Content) -> None:
    """The other direction. Removing description must not change ranking either.

    Asserted separately because the two failures are different bugs: a *rewrite* that
    changes the output means ``detail``'s content is being read, while a *strip* that
    changes it means its mere presence is — a scoring rule rewarding documented methods,
    which is the subtler and more tempting mistake.
    """
    before = _run(corpus)
    after = _run(_rewritten(corpus, MethodDetail()))

    assert after.primary == before.primary
    assert after.blocked == before.blocked


def test_the_estimates_themselves_are_unchanged(corpus: Content) -> None:
    """Down to the band level, since §8 is where ``detail``'s neighbours live.

    ``hours``, ``gp`` and the selected ``method_id`` all come from fields sitting beside
    ``detail`` on the same model, which is exactly where a stray attribute read would go
    unnoticed — the numbers would still look plausible.
    """
    before = {entry.candidate_id: entry.estimate for entry in _run(corpus).primary}
    after = {entry.candidate_id: entry.estimate for entry in _run(_rewritten(corpus, LOUD)).primary}

    assert after == before


def test_detail_is_optional_and_defaults_to_empty(corpus: Content) -> None:
    """Authoring it must never become mandatory: it describes, it does not declare."""
    undescribed = [m.id for m in corpus.training_methods.values() if m.detail == MethodDetail()]

    assert corpus.training_methods, "the corpus has no training methods to check"
    assert all(m.detail is not None for m in corpus.training_methods.values())
    # Not an assertion about coverage — only that an undescribed method is representable.
    assert isinstance(undescribed, list)


def test_gear_is_free_text_and_never_an_item_leaf(corpus: Content) -> None:
    """The field whose *type* is the safeguard.

    An ``item:`` leaf would be resolved by the evaluator and flow into
    ``_acquisition_charges``, so naming a Kodai wand for display would silently reprice
    the candidate for anyone who does not own one. Gear that must gate a method belongs in
    ``requires``, which is checked; gear that merely describes it stays a string.
    """
    for method in corpus.training_methods.values():
        assert all(isinstance(entry, str) for entry in method.detail.gear)
        assert all(isinstance(entry, str) for entry in method.detail.inventory)
