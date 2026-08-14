"""Builders for §22's pure layer.

Deliberately hand-built rather than loaded from ``content/``: these tests assert about what the
digest *says*, and a fixture that tracked the real corpus would rewrite its own expectations
every time somebody authored a quest. ``tests/golden/`` is where the real corpus is exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from tracker.advisor.snapshot import (
    AdvisorSnapshot,
    PriceFact,
    RankedTask,
    build_advisor_snapshot,
)
from tracker.content.loader import Content
from tracker.content.schema import (
    Candidate,
    Capability,
    Item,
    Quest,
    ScoringProfile,
    Skill,
    TrainingMethod,
)
from tracker.domain.types import (
    CapabilityView,
    Confidence,
    Container,
    ItemObservation,
    PlayerState,
    SkillState,
    Source,
    Status,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


def skill_at(level: int, *, xp: int | None = 100_000) -> SkillState:
    """One observed skill. ``xp=None`` is G5's *unranked*, which is not level 1."""
    return SkillState(level=level, xp=xp, source=Source.RUNELITE, observed_at=NOW)


def _profile() -> ScoringProfile:
    """The authored profile, read once.

    :class:`~tracker.content.loader.Content` requires one, and nothing in §22 reads it — the
    advisor never scores anything (D15). Reusing the real file rather than hand-building a
    stub keeps this fixture from becoming a second, quietly diverging definition of a profile.
    """
    raw = yaml.safe_load(Path("content/scoring/profile.yaml").read_text(encoding="utf-8"))
    return ScoringProfile.model_validate(raw["scoring_profile"])


def make_content(**overrides: object) -> Content:
    """A tiny corpus: three skills, two quests, one capability, two candidates, one method."""
    defaults: dict[str, object] = {
        "profile": _profile(),
        "skills": {
            "magic": Skill(id="magic", name="Magic"),
            "slayer": Skill(id="slayer", name="Slayer"),
            "agility": Skill(id="agility", name="Agility"),
        },
        "quests": {
            "desert_treasure_i": Quest(id="desert_treasure_i", name="Desert Treasure I"),
            "dragon_slayer_i": Quest(id="dragon_slayer_i", name="Dragon Slayer I"),
        },
        "items": {"coins": Item(id="coins", name="Coins", item_id=995)},
        "capabilities": {
            "ice_barrage_nh": Capability(
                id="ice_barrage_nh",
                name="Ice Barrage NH",
                requires={
                    "all_of": [
                        {"skill": {"magic": 94}},
                        {"quest": "desert_treasure_i"},
                        {"unlock": "ancient_magicks"},
                    ]
                },
            )
        },
        "candidates": {
            "train_magic_87_94": Candidate(
                id="train_magic_87_94",
                name="Train Magic 87 to 94",
                kind="skill_training",
                completion={"skill": {"magic": 94}},
            ),
            "quest_desert_treasure_i": Candidate(
                id="quest_desert_treasure_i",
                name="Desert Treasure I",
                kind="quest",
                completion={"quest": "desert_treasure_i"},
                grants_facts={"unlock": "ancient_magicks"},
            ),
        },
        "training_methods": {
            "magic_bursting": TrainingMethod(
                id="magic_bursting",
                name="Barrage at Nechryael",
                skill="magic",
                xp_per_hour=250_000,
                level_range={"min": 87, "max": 99},
                cost_per_hour_gp=1_200_000,
                detail={"location": "Catacombs of Kourend", "target": "Nechryael"},
            )
        },
    }
    defaults.update(overrides)
    return Content(**defaults)  # type: ignore[arg-type]


def make_state(**overrides: object) -> PlayerState:
    """A player with nothing observed unless a test says so.

    The defaults matter: ``account_type``, ``members`` and ``liquid_gp`` are all ``None``, so
    every test starts from the three-valued case the digest is most at risk of collapsing.
    """
    defaults: dict[str, object] = {"player_id": 1, "last_sync_at": NOW}
    defaults.update(overrides)
    return PlayerState(**defaults)  # type: ignore[arg-type]


def scanned(coins: int | None = None) -> dict[str, object]:
    """State fragments that put :attr:`PlayerState.liquid_gp` into a chosen one of its three states.

    ``liquid_gp`` is derived, not stored (§6.5), and deriving it is the only honest way to
    reach *someone looked and there were none* — which is a different fact from *nobody
    looked*, and the distinction these tests exist to protect.
    """
    scans = {Container.BANK: NOW}
    if coins is None:
        return {"container_scans": scans}
    return {
        "container_scans": scans,
        "observed_items": {
            995: ItemObservation(
                item_id=995,
                quantity=coins,
                containers=frozenset({Container.BANK}),
                observed_at=NOW,
            )
        },
    }


def make_capability_view(**overrides: object) -> CapabilityView:
    defaults: dict[str, object] = {
        "capability_id": "ice_barrage_nh",
        "status": Status.LOCKED,
        "unlock_fraction": 0.5,
        "readiness_confidence": Confidence.LOW,
    }
    defaults.update(overrides)
    return CapabilityView(**defaults)  # type: ignore[arg-type]


def make_task(**overrides: object) -> RankedTask:
    defaults: dict[str, object] = {
        "candidate_id": "train_magic_87_94",
        "name": "Train Magic 87 to 94",
        "kind": "skill_training",
        "rank": 1,
        "score": 0.42,
        "reason": "unblocks Ice Barrage NH",
        "blocked": False,
        "hours": 16.0,
        "gp": 19_200_000,
        "confidence": "medium",
    }
    defaults.update(overrides)
    return RankedTask(**defaults)  # type: ignore[arg-type]


def make_price(**overrides: object) -> PriceFact:
    defaults: dict[str, object] = {
        "item_id": 995,
        "name": "Coins",
        "price_gp": 1,
        "trade_at": NOW,
        "fetched_at": NOW,
        "provider": "osrs_wiki",
    }
    defaults.update(overrides)
    return PriceFact(**defaults)  # type: ignore[arg-type]


def make_snapshot(**overrides: object) -> AdvisorSnapshot:
    """Build through :func:`build_advisor_snapshot` rather than the dataclass.

    Constructing :class:`AdvisorSnapshot` directly would skip the ordering *and* the
    observation-age derivation, so a digest test could pass against a snapshot no production
    path can produce — the classic fixture that tests the fixture.
    """
    defaults: dict[str, object] = {
        "state": make_state(),
        "content": make_content(),
        "now": NOW,
    }
    defaults.update(overrides)
    return build_advisor_snapshot(**defaults)  # type: ignore[arg-type]
