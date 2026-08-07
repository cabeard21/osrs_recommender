"""Builders for the recommendation-engine tests.

These run against the **real** ``content/`` corpus rather than a synthetic one, which is a
deliberate departure from ``tests/progression/``. The progression tests assert rules about
requirement trees, and a one-capability corpus makes a failure name the rule it broke. These
assert rules about *rankings*, which only exist when several candidates compete — and
§16.2's judgments ("DT1 outranks buying a Voidwaker while Ancients are still locked") are
stated about the very ids the seed corpus declares.

Builders are fixtures returning callables, not importable module functions: sibling test
directories share one flat module namespace, so ``from conftest import ...`` would resolve
against whichever ``conftest`` was imported first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tracker.content.loader import Content
from tracker.content.schema import (
    KappaPresets,
    RefresherPolicy,
    ScoringProfile,
    ScoringWeights,
)
from tracker.content.validate import load_and_validate
from tracker.domain.types import (
    Container,
    GpSensitivity,
    ItemObservation,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    PlayerState,
    QuestStatus,
    SkillState,
    Source,
    Tri,
    UnlockState,
)

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: A fixed clock. Every age below is ``NOW - timedelta(...)``, so no test depends on when it
#: runs — the engine takes ``now`` as an argument (§16.1).
NOW = datetime(2026, 8, 4, tzinfo=UTC)

#: Numeric OSRS ids for the four items the corpus declares (§10.5). Spelled out because
#: ``PlayerState.observed_items`` is keyed by the numeric id, not by the content id.
VOIDWAKER = 27690
ARMADYL_GODSWORD = 11802
MYSTIC_ROBE_TOP = 4091
AHRIMS_ROBETOP = 4712


def _skill(level: int, xp: int | None = None) -> SkillState:
    return SkillState(level=level, xp=xp, source=Source.RUNELITE, observed_at=NOW)


def _owned(item_id: int) -> ItemObservation:
    return ItemObservation(
        item_id=item_id, quantity=1, containers=frozenset({Container.BANK}), observed_at=NOW
    )


def _milestone(
    key: str,
    *,
    achieved: bool = True,
    class_: MilestoneClass = MilestoneClass.EXECUTION,
    kind: MilestoneKind = MilestoneKind.SELF_ATTESTED,
    practiced_days_ago: int | None = 0,
) -> MilestoneState:
    """One projected milestone. ``practiced_days_ago=None`` means never practiced (G6)."""
    return MilestoneState(
        key=key,
        achieved=achieved,
        attested=Tri.SATISFIED if achieved else Tri.UNSATISFIED,
        kind=kind,
        class_=class_,
        last_practiced_at=(
            None if practiced_days_ago is None else NOW - timedelta(days=practiced_days_ago)
        ),
    )


def _player(
    *,
    skills: dict[str, int] | None = None,
    unlocks: Iterable[str] = (),
    quests: Iterable[str] = (),
    items: Iterable[int] = (),
    milestones: Iterable[MilestoneState] = (),
    scanned: bool = True,
    gp_sensitivity: GpSensitivity = GpSensitivity.NORMAL,
    synced: bool = True,
) -> PlayerState:
    """A player described in positives: what they have, not what they lack.

    ``scanned`` controls whether every container has been observed, which is the difference
    between *"you do not own a Voidwaker"* and *"nobody has looked"* (§6.5). It defaults to
    ``True`` because most ranking tests want definite facts; the tests that care about
    unknowns turn it off explicitly.
    """
    return PlayerState(
        player_id=1,
        skills={name: _skill(level) for name, level in (skills or {}).items()},
        unlocks=dict.fromkeys(unlocks, UnlockState.UNLOCKED),
        quests=dict.fromkeys(quests, QuestStatus.COMPLETE),
        observed_items={item_id: _owned(item_id) for item_id in items},
        container_scans=(dict.fromkeys(Container, NOW) if scanned else {}),
        milestones={state.key: state for state in milestones},
        gp_sensitivity=gp_sensitivity,
        last_sync_at=NOW if synced else None,
    )


@pytest.fixture(scope="session")
def seed_content() -> Content:
    """The shipped corpus — the ids §16.2's judgments are written about."""
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def profile(seed_content: Content) -> ScoringProfile:
    """The authored scoring profile, so these tests score what the app scores."""
    return seed_content.profile


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def player() -> Callable[..., PlayerState]:
    return _player


@pytest.fixture
def milestone_state() -> Callable[..., MilestoneState]:
    return _milestone


@pytest.fixture
def make_profile() -> Callable[..., ScoringProfile]:
    """A profile with one knob moved, for tests about a single §9.7 value.

    Built rather than loaded because a test asserting *"raising this weight does X"* must
    not also depend on the corpus's current value of it — §16.3 calls the shipped weights
    provisional priors, and Step 13 will change them.
    """

    def build(**overrides: object) -> ScoringProfile:
        defaults: dict[str, object] = {
            "version": 1,
            "tau_hours": 10.0,
            "kappa_gp": KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
            "weights": ScoringWeights(
                pvp_value=1.0, leverage=0.8, proximity=0.6, effort_decay=0.7, cost_decay=0.5
            ),
            "refresher": RefresherPolicy(),
        }
        defaults.update(overrides)
        return ScoringProfile(**defaults)  # type: ignore[arg-type]

    return build
