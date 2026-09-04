from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from tracker.content.loader import Content
from tracker.content.validate import load_and_validate

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


class TestBossingGuideCorpus:
    TIER_COUNTS: ClassVar[dict[str, int]] = {
        "easy": 7,
        "medium": 17,
        "hard": 20,
        "elite": 13,
        "master": 8,
        "grandmaster": 6,
    }
    PREPARATION_COUNTS: ClassVar[dict[str, int]] = {
        "easy": 7,
        "medium": 8,
        "hard": 9,
        "elite": 5,
        "master": 2,
        "grandmaster": 2,
    }
    TIER_IDS: ClassVar[dict[str, list[str]]] = {
        "easy": [
            "brutus",
            "wintertodt",
            "tempoross",
            "barrows",
            "obor_bryophyta",
            "deranged_archaeologist",
            "scurrius",
        ],
        "medium": [
            "shellbane_gryphon",
            "barbarian_assault",
            "amoxliatl",
            "hueycoatl",
            "hespori",
            "giant_mole",
            "crazy_archaeologist_chaos_fanatic",
            "kraken",
            "sarachnis",
            "king_black_dragon",
            "zalcano",
            "thermonuclear_smoke_devil",
            "mimic",
            "royal_titans",
            "moons_of_peril",
            "mad_angel",
            "god_wars_dungeon_teams",
        ],
        "hard": [
            "scorpia",
            "chaos_elemental",
            "vetion_calvarion",
            "venenatis_spindel",
            "callisto_artio",
            "dagannoth_kings",
            "grotesque_guardians",
            "skotizo",
            "tz_tok_jad",
            "demonic_gorillas",
            "tormented_demons",
            "gauntlet",
            "abyssal_sire",
            "cerberus",
            "araxxor",
            "alchemical_hydra",
            "corporeal_beast",
            "kalphite_queen",
            "commander_zilyana_solo",
            "kril_tsutsaroth_solo",
        ],
        "elite": [
            "zulrah",
            "vorkath",
            "phantom_muspah",
            "duke_sucellus",
            "maggot_king",
            "kreearra_solo",
            "general_graardor_solo",
            "corrupted_gauntlet",
            "whisperer",
            "leviathan",
            "vardorvis",
            "nex_small_teams",
            "yama",
        ],
        "master": [
            "tombs_of_amascut_300",
            "chambers_of_xeric",
            "nightmare_phosanis_nightmare",
            "demonic_brutus",
            "doom_of_mokhaiotl",
            "theatre_of_blood",
            "sol_heredit",
            "tzkal_zuk",
        ],
        "grandmaster": [
            "challenge_mode_chambers",
            "tombs_of_amascut_500",
            "hard_mode_theatre_of_blood",
            "yamas_contracts",
            "awakened_dt2_bosses",
            "grandmaster_combat_achievements",
        ],
    }

    def test_pinned_source_and_attribution(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]

        assert guide.roadmap_id == "pvm_ladder"
        assert guide.source.revision == 15319480
        assert str(guide.source.checked_at) == "2026-09-04"
        assert guide.source.license == "CC BY-NC-SA 3.0"
        assert guide.source.url.endswith("?oldid=15319480")

    def test_preserves_all_six_tiers_and_71_source_rows(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]

        assert [tier.id for tier in guide.tiers] == list(self.TIER_COUNTS)
        assert {tier.id: len(tier.encounters) for tier in guide.tiers} == self.TIER_COUNTS
        assert sum(len(tier.encounters) for tier in guide.tiers) == 71
        assert {
            tier.id: [encounter.id for encounter in tier.encounters] for tier in guide.tiers
        } == self.TIER_IDS

    def test_row_ids_are_unique_and_source_groupings_stay_grouped(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]
        encounters = [encounter for tier in guide.tiers for encounter in tier.encounters]

        assert len({encounter.id for encounter in encounters}) == 71
        assert "obor_bryophyta" in {encounter.id for encounter in encounters}
        assert "nightmare_phosanis_nightmare" in {encounter.id for encounter in encounters}
        assert "obor" not in {encounter.id for encounter in encounters}
        assert "bryophyta" not in {encounter.id for encounter in encounters}

    def test_every_row_has_actionable_prose_and_an_https_wiki_link(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]

        for tier in guide.tiers:
            assert tier.summary
            assert len(tier.preparation) == self.PREPARATION_COUNTS[tier.id]
            for encounter in tier.encounters:
                assert encounter.mechanics
                assert encounter.rewards
                assert encounter.wiki_url.startswith("https://oldschool.runescape.wiki/w/")

    def test_access_is_not_inferred_from_advisory_combat_levels(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]
        by_id = {encounter.id: encounter for tier in guide.tiers for encounter in tier.encounters}

        assert by_id["giant_mole"].access is None
        assert by_id["giant_mole"].recommendations is not None
        assert by_id["barrows"].access is not None
        assert by_id["barrows"].recommendations is not None
        assert by_id["alchemical_hydra"].access is not None

    def test_source_specific_requirements_match_the_pinned_revision(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]
        by_id = {encounter.id: encounter for tier in guide.tiers for encounter in tier.encounters}

        assert by_id["crazy_archaeologist_chaos_fanatic"].recommendations is not None
        assert by_id["zalcano"].recommendations is None
        assert by_id["grotesque_guardians"].access is not None
        assert by_id["cerberus"].recommendations is not None
        assert by_id["demonic_brutus"].access is not None
        assert by_id["tzkal_zuk"].access is not None
        assert by_id["yama"].recommendations is not None

    def test_granular_preparation_steps_keep_source_checklists(self, content: Content) -> None:
        guide = content.roadmap_guides["pvm_bossing_ladder"]
        tiers = {tier.id: tier for tier in guide.tiers}

        assert [step.id for step in tiers["easy"].preparation][:3] == [
            "easy_free_to_play_quests",
            "easy_early_monsters",
            "easy_quest_combat_xp",
        ]
        assert "hard_arclight" in {step.id for step in tiers["hard"].preparation}
        assert "elite_prayer_scrolls" in {step.id for step in tiers["elite"].preparation}
