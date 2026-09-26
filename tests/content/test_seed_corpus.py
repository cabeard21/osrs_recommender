"""Focused checks for shipped content used by retained account and gear views."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from tracker.content.loader import Content
from tracker.content.requirements import CapabilityLeaf
from tracker.content.validate import load_and_validate

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


class TestShape:
    def test_the_shipped_corpus_validates(self, content: Content) -> None:
        assert content.profile.version == 2


class TestPvmLadder:
    """The Wiki tiers are independently evaluable preparation goals.

    Tier order belongs to the authored guide.  A player must therefore be able to be ready
    for a later encounter without completing every earlier encounter or capability.
    """

    #: Bottom to top. The order is the assertion.
    RUNGS: ClassVar[tuple[str, ...]] = (
        "boss_fundamentals",
        "mid_tier_bossing",
        "gwd_bossing",
        "dragon_bossing",
        "raid_ready",
        "grandmaster_bossing",
    )

    @staticmethod
    def _capability_leaves(node: object) -> list[str]:
        """Every ``capability:`` id anywhere in a requirement tree."""
        if isinstance(node, CapabilityLeaf):
            return [node.capability_id]
        # The combinators name their children differently — ``children`` on all_of/any_of,
        # ``child`` on not, ``of`` on at_least — so all three are walked rather than the one
        # this corpus happens to use today.
        nested = [
            found
            for attribute in ("children", "child", "of")
            if (found := getattr(node, attribute, None)) is not None
        ]
        return [
            leaf
            for group in nested
            for child in (group if isinstance(group, tuple | list) else [group])
            for leaf in TestPvmLadder._capability_leaves(child)
        ]

    def test_no_tier_requires_another_tier(self, content: Content) -> None:
        for rung in self.RUNGS:
            assert self._capability_leaves(content.capabilities[rung].requires) == [], rung


class TestTrainingMethods:
    def test_the_fast_magic_method_is_gated_and_the_default_is_not(self, content: Content) -> None:
        """§8.2 step 3 — the fast method is behind the content being sequenced."""
        fast = content.training_methods["magic_bursting"]
        default = content.training_methods["magic_conservative"]

        assert fast.requires is not None
        assert default.requires is None
        assert fast.xp_per_hour > default.xp_per_hour

    def test_methods_are_ordered_fastest_first(self, content: Content) -> None:
        assert [m.id for m in content.methods_for_skill("magic")] == [
            "magic_bursting",
            "magic_conservative",
        ]

    def test_every_method_resolves_to_a_declared_skill(self, content: Content) -> None:
        for method in content.training_methods.values():
            assert method.skill in content.skills


class TestGearLaddersAreContiguous:
    """Every ladder runs 1..n with no gap, which is a claim the page makes out loud.

    ``ladder_size`` counts the rungs that reached the corpus and ``tier`` is the position in
    the transcription, so the two only agree while nothing is dropped between them. They
    disagreed for as long as a name could sit on only one ladder: Barrows gloves are melee and
    ranged, the generator declared them once, and the ranged hands ladder was left with tiers
    1, 2, 4, 5 and a top rung rendering as *"rung 5 of 4"*.

    Asserted over the shipped corpus rather than over the transcription, because the
    transcription is contiguous by construction — ``tier`` is ``enumerate``'s index — and the
    dropping happened downstream of it.
    """

    def test_no_ladder_skips_a_rung(self, content: Content) -> None:
        from tracker.gear.ladders import build_ladders

        gaps = {
            f"{ladder.style} {ladder.slot}": [item.tier for item in ladder.rungs]
            for ladder in build_ladders(content)
            if [item.tier for item in ladder.rungs] != list(range(1, ladder.size + 1))
        }
        assert gaps == {}

    def test_a_piece_on_two_ladders_is_one_piece_with_two_placements(
        self, content: Content
    ) -> None:
        """One numeric id, two rows, and every field that describes the *item* identical.

        Ownership tests the union, so an observation of the one Antler guard in the bank
        marks both rows held — which is the point, and is only sound while the rows cannot
        disagree about what the item is.
        """
        rows = [item for item in content.items.values() if item.name == "Antler guard"]
        assert len(rows) == 2
        assert {(row.style, row.slot) for row in rows} == {
            ("melee", "shield"),
            ("ranged", "shield"),
        }
        assert len({row.item_id for row in rows}) == 1
        assert len({row.requires for row in rows}) == 1
        assert len({row.acquisition for row in rows}) == 1
        assert len({row.fallback_price_gp for row in rows}) == 1
