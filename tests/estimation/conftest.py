"""Builders for the estimation tests (§16.4 — *"unit tests over synthetic method tables"*).

The shipped corpus has two authored Magic methods and a handful of melee defaults, which
is enough to demonstrate §8.2 and not enough to *test* it: there is no band anywhere in it
that no method covers, so the fallback path §8.2 ends on would go unexercised. Every unit
test here builds the method table it needs, and the last few tests in each module run the
same code against ``content/`` as a smoke check that the synthetic shapes are real ones.

Builders are handed out as **fixtures returning callables**, matching
``tests/progression/conftest.py``: sibling test directories share one flat module
namespace, so an importable helper here could collide with another step's.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tracker.content.loader import Content
from tracker.content.schema import (
    Candidate,
    Item,
    KappaPresets,
    RefresherTemplate,
    ScoringProfile,
    ScoringWeights,
    Skill,
    TrainingMethod,
)
from tracker.content.validate import load_and_validate
from tracker.domain.types import (
    Container,
    ItemObservation,
    PlayerState,
    PriceSourceLayer,
    QuestStatus,
    SkillState,
    Source,
    UnlockState,
)
from tracker.estimation.prices import PriceRecord

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: A fixed clock. Every age below is ``NOW - timedelta(...)``, so no test depends on when
#: it runs — ``estimate`` and ``resolve_price`` both take ``now`` as an argument (§16.1).
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

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


@dataclass(frozen=True, slots=True)
class FakePriceRecord:
    """A stand-in for §6.8's ``ItemPrice`` row, structurally satisfying ``PriceRecord``.

    Frozen for the same reason the real ``PriceDTO`` is, which is exactly what makes the
    read-only-property protocol necessary — see ``tests/integration/test_price_seam.py``,
    where the *real* DTO is checked against the same protocol.
    """

    item_id: int
    high_price_gp: int | None = None
    high_trade_at: datetime | None = None
    low_price_gp: int | None = None
    low_trade_at: datetime | None = None
    fetched_at: datetime = NOW
    source: str = PriceSourceLayer.LIVE.value


def _index(objects: Iterable[Any]) -> dict[str, Any]:
    return {obj.id: obj for obj in objects}


def _build_content(
    *,
    methods: Sequence[TrainingMethod] = (),
    items: Sequence[Item] = (),
    candidates: Sequence[Candidate] = (),
    refreshers: Sequence[RefresherTemplate] = (),
    skills: Sequence[Skill] = (Skill(id="magic", name="Magic", is_combat=True),),
) -> Content:
    return Content(
        profile=PROFILE,
        skills=_index(skills),
        items=_index(items),
        candidates=_index(candidates),
        refreshers=_index(refreshers),
        training_methods=_index(methods),
    )


def _method(
    method_id: str,
    *,
    xp_per_hour: int,
    skill: str = "magic",
    levels: tuple[int, int] = (1, 99),
    cost_per_hour_gp: int = 0,
    requires: Any = None,
) -> TrainingMethod:
    """One §8.1 training method. ``requires`` takes the YAML form — ``{"unlock": "x"}``."""
    return TrainingMethod.model_validate(
        {
            "id": method_id,
            "name": method_id.replace("_", " ").title(),
            "skill": skill,
            "xp_per_hour": xp_per_hour,
            "level_range": {"min": levels[0], "max": levels[1]},
            "cost_per_hour_gp": cost_per_hour_gp,
            "requires": requires,
        }
    )


def _candidate(candidate_id: str, *, kind: str, completion: Any, requires: Any = None) -> Candidate:
    return Candidate.model_validate(
        {
            "id": candidate_id,
            "name": candidate_id.replace("_", " ").title(),
            "kind": kind,
            "completion": completion,
            "requires": requires,
        }
    )


def _state(
    *,
    skills: dict[str, int] | None = None,
    xp: dict[str, int] | None = None,
    unlocks: dict[str, UnlockState] | None = None,
    quests: dict[str, QuestStatus] | None = None,
    owned: Iterable[int] = (),
    scanned: bool = True,
) -> PlayerState:
    """An account with the named levels, and nothing else observed.

    ``scanned`` controls whether every container has been seen (§6.5): with it off, an
    ``item:`` leaf resolves ``unknown`` rather than ``unsatisfied``, which is the state in
    which §8.3 must still price the item conservatively.
    """
    levels = skills or {}
    totals = xp or {}
    return PlayerState(
        player_id=1,
        skills={
            skill: SkillState(
                level=level, xp=totals.get(skill), source=Source.RUNELITE, observed_at=NOW
            )
            for skill, level in levels.items()
        },
        unlocks=unlocks or {},
        quests=quests or {},
        observed_items={
            item_id: ItemObservation(
                item_id=item_id,
                quantity=1,
                containers=frozenset({Container.BANK}),
                observed_at=NOW,
            )
            for item_id in owned
        },
        container_scans=dict.fromkeys(Container, NOW) if scanned else {},
        last_sync_at=NOW,
    )


@pytest.fixture
def build_content() -> Callable[..., Content]:
    return _build_content


@pytest.fixture
def method() -> Callable[..., TrainingMethod]:
    return _method


@pytest.fixture
def candidate() -> Callable[..., Candidate]:
    return _candidate


@pytest.fixture
def state() -> Callable[..., PlayerState]:
    return _state


@pytest.fixture
def price_record() -> Callable[..., PriceRecord]:
    """A §6.8 price row builder, annotated as the protocol it has to satisfy.

    The annotation is a static assertion in its own right: mypy accepts this fixture only
    while ``FakePriceRecord`` structurally satisfies ``PriceRecord``. The *real*
    ``PriceDTO`` is checked against the same protocol in
    ``tests/integration/test_price_seam.py`` — a protocol is only verified where an
    implementation is assigned to it, and a fake satisfying it proves nothing about the
    class that crosses the seam.
    """
    return FakePriceRecord


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def ago() -> Callable[..., datetime]:
    """``ago(days=5)`` — a timestamp that far before :data:`NOW`."""

    def _ago(**kwargs: float) -> datetime:
        return NOW - timedelta(**kwargs)

    return _ago


@pytest.fixture(scope="session")
def seed_content() -> Content:
    """The real ``content/`` corpus, for the end-of-module smoke checks."""
    return load_and_validate(CONTENT_ROOT)
