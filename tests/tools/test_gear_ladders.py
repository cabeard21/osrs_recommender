"""The gear ladders' own invariants (§23.2).

``tools/`` is authoring machinery rather than application code, so most of it is verified
by running it. These three tables are the exception: they are hand-transcribed, they decide
what the application tells a player they can wear, and the way they go wrong is *silently*.
A rung nobody classified would default to ungated and the page would confidently offer a
Twisted bow to a level-3 account — no exception, no warning, just a wrong answer.

So the partition is asserted here rather than assumed. This test file may import
``tracker``; ``tools/gear_ladders.py`` deliberately may not, which is why the requirement
mappings are plain nested dicts and their §10.2 validity is checked from this side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import gear_ladders  # noqa: E402

from tracker.content.requirements import SkillLeaf, iter_leaves, parse  # noqa: E402


class TestThePartitionIsTotal:
    """Every rung is classified, and no classification names a rung that no longer exists."""

    def test_no_rung_is_unclassified(self) -> None:
        """The one that matters. An unclassified rung silently reads as *no requirements*."""
        assert gear_ladders.missing_requirements() == []

    def test_no_classification_is_orphaned(self) -> None:
        """The mirror: a name removed from a ladder leaves dead weight that reads as live."""
        assert gear_ladders.orphan_requirements() == []

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("REQUIREMENTS", "UNGATED"),
            ("REQUIREMENTS", "UNTRANSCRIBED"),
            ("UNGATED", "UNTRANSCRIBED"),
        ],
    )
    def test_the_three_tables_are_disjoint(self, left: str, right: str) -> None:
        """Three *states*, so a name in two of them is a rung with two answers."""
        overlap = set(getattr(gear_ladders, left)) & set(getattr(gear_ladders, right))
        assert overlap == set()

    def test_an_unclassified_name_raises_rather_than_reading_as_ungated(self) -> None:
        """``None`` means *no gate*, so an unknown name must not be able to return it."""
        with pytest.raises(KeyError, match="must never default to ungated"):
            gear_ladders.requirement_for("Not a real item")


class TestRequirementsAreWellFormed:
    """The tables are plain dicts here and requirement trees by the time they are corpus."""

    @pytest.mark.parametrize("name", sorted(gear_ladders.REQUIREMENTS))
    def test_every_requirement_parses_as_a_tree(self, name: str) -> None:
        """§10.2, checked here because ``gear_ladders`` cannot import the parser itself."""
        requirement = gear_ladders.requirement_for(name)
        assert requirement is not None
        assert parse(requirement, path=name) is not None

    @pytest.mark.parametrize("name", sorted(gear_ladders.REQUIREMENTS))
    def test_no_requirement_gates_on_making_the_item(self, name: str) -> None:
        """Wear requirements only.

        The wiki states these in prose, and the prose mixes in the levels needed to *make*
        or *repair* the item — 80 Fletching for a magic shortbow, 90 Smithing for Torva.
        Those gate a workbench, not the equipment screen, and a player told they cannot
        wear their own whip until they have 80 Fletching has been handed a wrong answer
        that reads as authoritative. No OSRS item requires an artisan skill to equip, so
        one appearing here is always a transcription slip rather than a real gate.
        """
        artisan = {"fletching", "smithing", "crafting", "herblore", "cooking", "firemaking"}
        requirement = gear_ladders.requirement_for(name)
        assert requirement is not None
        skills = {
            leaf.skill
            for leaf in iter_leaves(parse(requirement, path=name))
            if isinstance(leaf, SkillLeaf)
        }
        assert not skills & artisan, f"{name} gates on a skill that makes it, not one that wears it"


class TestCanonicalisation:
    """The compact multi-skill spelling is a convenience, and must change nothing else."""

    def test_a_multi_skill_leaf_becomes_one_leaf_per_skill(self) -> None:
        """§10.2 is strict that a skill leaf names exactly one skill."""
        requirement = gear_ladders.requirement_for("Ferocious gloves")
        assert requirement == {"all_of": [{"skill": {"attack": 80}}, {"skill": {"defence": 80}}]}

    def test_a_single_skill_leaf_is_left_alone(self) -> None:
        assert gear_ladders.requirement_for("Abyssal whip") == {"skill": {"attack": 70}}

    def test_expansion_reaches_inside_a_combinator(self) -> None:
        """A compact leaf nested under ``all_of`` is the common shape: levels plus a quest."""
        assert gear_ladders.requirement_for("Green d'hide body") == {
            "all_of": [
                {"all_of": [{"skill": {"ranged": 40}}, {"skill": {"defence": 40}}]},
                {"quest": "dragon_slayer_i"},
            ]
        }


class TestTheAcquisitionPartitionIsTotal:
    """The second axis's copy of the same proof, over the same names (§10.5).

    Two partitions rather than one six-way table, so an omission on either axis fails on its
    own. A rung classified for its wear gate and forgotten here would silently say nothing
    about how it is obtained — which reads exactly like a piece the market sells.
    """

    def test_no_rung_is_unclassified(self) -> None:
        assert gear_ladders.missing_acquisitions() == []

    def test_no_classification_is_orphaned(self) -> None:
        assert gear_ladders.orphan_acquisitions() == []

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("EARNED_FROM", "TRADEABLE"),
            ("EARNED_FROM", "ACQUISITION_UNTRANSCRIBED"),
            ("TRADEABLE", "ACQUISITION_UNTRANSCRIBED"),
        ],
    )
    def test_the_three_tables_are_disjoint(self, left: str, right: str) -> None:
        """Three *states*, so a name in two of them is a rung with two answers."""
        overlap = set(getattr(gear_ladders, left)) & set(getattr(gear_ladders, right))
        assert overlap == set()

    def test_an_unclassified_name_raises_rather_than_reading_as_tradeable(self) -> None:
        """``(None, None)`` is a meaning — *nobody checked* — so it must not be reachable."""
        with pytest.raises(KeyError, match="must never default to tradeable"):
            gear_ladders.acquisition_for("Not a real item")


class TestSourcesAreNounPhrases:
    """Every surface composes the source into a sentence, so a sentence here nests one.

    *"untradeable — earned from You must beat the Inferno"* is the one way this can go wrong,
    and it is invisible in the table and obvious in the rendering. Asserted on the table side,
    where it is cheap.
    """

    @pytest.mark.parametrize("name", sorted(gear_ladders.EARNED_FROM))
    def test_the_source_reads_as_a_noun_phrase(self, name: str) -> None:
        source = gear_ladders.EARNED_FROM[name]
        assert source, f"{name} has an empty source"
        assert not source.endswith("."), f"{name} ends in a full stop, so it is a sentence"
        assert source.split()[0] not in {
            "You",
            "Complete",
            "Kill",
            "Beat",
        }, f"{name} starts like a sentence rather than a noun phrase"


class TestNothingEarnedIsAlsoQuotedByTheMarket:
    """A one-directional cross-check of the acquisition tables against the price catalog.

    The catalog is the price API's ``/mapping`` snapshot, which carries **only tradeables**.
    So a name in :data:`EARNED_FROM` that the market quotes *under that exact name* is a flat
    contradiction: the corpus would be telling a player they cannot buy something the Grand
    Exchange sells, and that is the one direction of this axis that withholds a rung.

    **The converse is deliberately not asserted, and the numbers are why.** Twenty-five names
    in :data:`TRADEABLE` are absent from the catalog — Toxic blowpipe, Blade of saeldor,
    Sanguinesti staff, Crystal helm, Trident of the seas — and every one is a piece whose
    *worn* form is untradeable and whose component trades under a different name. That is the
    rule TRADEABLE is written to, so absence from the catalog is no evidence against it.

    Asserted here rather than in ``tracker/content/validate.py`` because it needs a tools-side
    artefact, and because whoever can act on it is whoever re-runs the capture.
    """

    def test_no_rung_the_market_quotes_is_classified_as_earned(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "tools" / "data" / "osrs_gear_ids.json").read_text(encoding="utf-8")
        )
        catalog = set(payload["catalog"])
        assert sorted(set(gear_ladders.EARNED_FROM) & catalog) == []


class TestANameMayBeClaimedByTwoLadders:
    """A piece the guides put on two ladders is authored onto both, and this pins the reason.

    Barrows gloves are melee and ranged; an Antler guard is a tribrid shield both guides reach
    for. The generator used to declare a name once and comment out the recurrence, so whichever
    style was walked first won the rung and the rest lost it — silently, and worse than an
    omission, because ``tier`` is the position in the transcription while ``ladder_size``
    counts what reached the corpus, so the loser was left with a *gap* and rendered its top
    rung as "rung 5 of 4".
    """

    def test_the_names_the_guides_share_are_on_every_ladder_that_prints_them(self) -> None:
        placements: dict[str, set[str]] = {}
        for style, _slot, _tier, name in gear_ladders.every_name():
            placements.setdefault(name, set()).add(style)

        assert placements["Barrows gloves"] == {"melee", "ranged"}
        assert placements["Antler guard"] == {"melee", "ranged"}
        assert placements["Combat bracelet"] == {"melee", "magic"}

    def test_a_shared_name_never_sits_twice_on_one_ladder(self) -> None:
        """Two placements on one ladder is a piece occupying two rungs of its own
        progression, which is a duplicate however it is spelled."""
        seen: set[tuple[str, str, str]] = set()
        for style, slot, _tier, name in gear_ladders.every_name():
            key = (style, slot, name)
            assert key not in seen, f"{name} appears twice on the {style} {slot} ladder"
            seen.add(key)


class TestTheShieldLadderIsTheGuidesAndNotASlotTable:
    """A regression pin for the way this file goes wrong.

    The melee shield ladder was briefly eleven rungs: Mooleta and the three real ones, plus
    the bronze/iron/steel/black/mithril/adamant/rune defenders lifted from the wiki's
    ``Shield_slot_table``. Every one of those is a real item in a sensible order, which is
    exactly why nothing caught it — the ladder looked *more* complete and had quietly stopped
    being the guide's opinion, which is the only thing ``tier`` is supposed to encode.

    Pinned by name rather than by length. A length check would pass the moment somebody
    swapped one wrong rung for another, and the failure mode here is a plausible-looking name,
    not a miscount.
    """

    def test_melee_shield_is_exactly_the_guides_four_rungs(self) -> None:
        assert gear_ladders.MELEE["shield"] == [
            "Mooleta",
            "Antler guard",
            "Dragon defender",
            "Avernic defender",
        ]

    def test_no_plain_defender_is_on_any_ladder(self) -> None:
        """The specific items the slot table contributed. None is in any progression guide."""
        metal = {"Bronze", "Iron", "Steel", "Black", "Mithril", "Adamant", "Rune"}
        strays = {
            name
            for name in gear_ladders.unique_names()
            if name.endswith(" defender") and name.split()[0] in metal
        }
        assert strays == set()

    def test_ranged_ammunition_is_the_guides_nine_rungs(self) -> None:
        """Trimmed from twenty-three for the same reason: the arrow, bolt and dart families
        were pulled in wholesale, and the guide's ammo cells print nine names."""
        assert gear_ladders.RANGED["ammunition"] == [
            "Iron arrow",
            "Mithril arrow",
            "Adamant arrow",
            "Bone bolts",
            "Rune arrow",
            "Amethyst arrow",
            "Moonlight antler bolts",
            "Ruby dragon bolts (e)",
            "Seeking dragon arrow",
        ]
