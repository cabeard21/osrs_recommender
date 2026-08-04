"""§10.7 validation: the ten rules, the ten corrupt corpora, and the CLI.

*"Unvalidated YAML fails at runtime with an unhelpful ``KeyError``, typically months
later."* Every assertion here is about the diagnostic being **usable**, not merely
present: it must name the rule, and it must name the file it came from.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tracker.content.loader import ContentValidationError, load_content, parse_corpus
from tracker.content.validate import load_and_validate, main, validate_content
from tracker.domain.types import Confidence, Freshness, MilestoneClass, PracticeDomain

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
CORRUPT = HERE / "corrupt"
MINIMAL = FIXTURES / "minimal"
SHARED_PROFILE = FIXTURES / "profile.yaml"

#: One entry per §10.7 rule, paired with a phrase its diagnostic must contain.
CORRUPT_CORPORA: list[tuple[str, str]] = [
    ("01_duplicate_id", "duplicate id 'magic'"),
    ("02_dangling_reference", "references item 'nonexistent_item'"),
    ("03_unknown_grant", "grants 'not_a_capability'"),
    ("04_unknown_practice_domain", "practiced_by"),
    ("05_empty_practice_group", "no milestone belongs to"),
    ("06_non_execution_practices", "Only class: execution milestones practice"),
    ("07_live_price_without_item_id", "price_mode: live but no numeric item_id"),
    ("08_capability_cycle", "form a cycle"),
    ("09_weight_out_of_range", "outside [0, 1]"),
    ("10_kappa_ordering", "ordering violated"),
]


def profile_for(corpus: Path) -> Path:
    """A corpus supplies its own profile only when it is corrupting the profile."""
    own = corpus / "scoring" / "profile.yaml"
    return own if own.is_file() else SHARED_PROFILE


class TestValidCorpus:
    def test_the_minimal_corpus_passes(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        assert set(content.capabilities) == {"ice_barrage_nh"}
        assert set(content.roadmaps) == {"main_nh"}
        assert validate_content(content) == []

    def test_a_list_file_and_a_single_object_file_both_load(self) -> None:
        """23 skills in 23 files is absurd; one capability per file is exactly right."""
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        assert set(content.skills) == {"magic", "defence"}  # one list file
        assert content.capabilities["ice_barrage_nh"].name == "Ice Barrage NH"  # one per file

    def test_requirement_trees_are_parsed_not_left_as_dicts(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        requires = content.capabilities["ice_barrage_nh"].requires
        assert requires is not None
        assert requires.type == "all_of"

    def test_named_readiness_becomes_the_ordered_enum(self) -> None:
        """A9 — content authors write `high`; the engine needs something comparable."""
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        assert content.capabilities["ice_barrage_nh"].recommended_readiness is Confidence.HIGH

    def test_enums_are_parsed_from_their_yaml_spellings(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        milestone = content.milestones["comfortable_4_way_switches"]
        assert milestone.class_ is MilestoneClass.EXECUTION
        assert PracticeDomain.LMS in milestone.practiced_by
        refresher = content.refreshers["refresh_nh_fundamentals"]
        assert refresher.trigger.any_member_freshness_at_least is Freshness.STALE

    def test_profile_carries_the_amended_defaults(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        assert content.profile.observation_aged_days == 14  # A4
        assert content.profile.tuned_against_corpus is None  # not yet tuned (§16.3)
        assert content.profile.tau_hours == 10
        assert content.profile.weights.pvp_value == 1.0

    def test_refresher_declares_session_hours(self) -> None:
        """A8 — absent hours would give effort_decay = 1.0 and defeat G10."""
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        assert content.refreshers["refresh_nh_fundamentals"].suggested_session_hours == 0.5


class TestIndexes:
    def test_item_lookup_by_numeric_id(self) -> None:
        """How an `item:` leaf reaches a PlayerState observation keyed by game id."""
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        found = content.item_by_numeric_id(27690)
        assert found is not None
        assert found.id == "voidwaker"
        assert content.item_by_numeric_id(1) is None

    def test_methods_for_skill_are_fastest_first(self) -> None:
        """§8.2 step 3 walks methods in speed order, picking the first that is available."""
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        methods = content.methods_for_skill("magic")
        assert [m.id for m in methods] == ["magic_bursting"]
        assert content.methods_for_skill("defence") == ()

    def test_practice_group_membership(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        members = content.milestones_in_group("nh_fundamentals")
        assert [m.id for m in members] == ["comfortable_4_way_switches"]

    def test_every_object_knows_where_it_came_from(self) -> None:
        content = load_and_validate(MINIMAL, profile_path=SHARED_PROFILE)
        location = content.location_of("ice_barrage_nh")
        assert location.file is not None
        assert location.file.name == "ice_barrage_nh.yaml"


class TestTheTenRules:
    @pytest.mark.parametrize(("directory", "expected"), CORRUPT_CORPORA)
    def test_each_corrupt_corpus_fails_loudly(self, directory: str, expected: str) -> None:
        corpus = CORRUPT / directory
        with pytest.raises(ContentValidationError) as caught:
            load_and_validate(corpus, profile_path=profile_for(corpus))
        assert expected in str(caught.value)

    @pytest.mark.parametrize(("directory", "_expected"), CORRUPT_CORPORA)
    def test_every_diagnostic_names_a_file(self, directory: str, _expected: str) -> None:
        """The κ rule is the one exception: it is about the profile as a whole."""
        corpus = CORRUPT / directory
        with pytest.raises(ContentValidationError) as caught:
            load_and_validate(corpus, profile_path=profile_for(corpus))

        for error in caught.value.errors:
            if error.location.path == "scoring_profile.kappa_gp":
                continue
            assert error.location.file is not None, f"{error} has no file"

    def test_all_ten_rules_have_a_fixture(self) -> None:
        on_disk = {p.name for p in CORRUPT.iterdir() if p.is_dir()}
        assert on_disk == {directory for directory, _ in CORRUPT_CORPORA}
        assert len(CORRUPT_CORPORA) == 10


class TestCycleReporting:
    def test_the_diagnostic_names_the_actual_cycle_path(self) -> None:
        """A boolean 'there is a cycle' leaves the author to find it by hand."""
        corpus = CORRUPT / "08_capability_cycle"
        with pytest.raises(ContentValidationError) as caught:
            load_and_validate(corpus, profile_path=SHARED_PROFILE)

        message = str(caught.value)
        assert "alpha → beta → gamma → alpha" in message

    def test_a_self_referential_capability_is_a_cycle(self, tmp_path: Path) -> None:
        corpus = tmp_path / "content"
        (corpus / "capabilities").mkdir(parents=True)
        (corpus / "capabilities" / "loop.yaml").write_text(
            "id: loop\nname: Loop\nrequires:\n  capability: loop\n", encoding="utf-8"
        )
        with pytest.raises(ContentValidationError, match="loop → loop"):
            load_and_validate(corpus, profile_path=SHARED_PROFILE)

    def test_a_diamond_is_not_a_cycle(self, tmp_path: Path) -> None:
        """Capabilities compose into a DAG (§4.1) — shared ancestors are normal."""
        corpus = tmp_path / "content"
        (corpus / "capabilities").mkdir(parents=True)
        (corpus / "capabilities" / "diamond.yaml").write_text(
            "- id: base\n"
            "  name: Base\n"
            "- id: left\n"
            "  name: Left\n"
            "  requires: {capability: base}\n"
            "- id: right\n"
            "  name: Right\n"
            "  requires: {capability: base}\n"
            "- id: top\n"
            "  name: Top\n"
            "  requires:\n"
            "    all_of:\n"
            "      - capability: left\n"
            "      - capability: right\n",
            encoding="utf-8",
        )
        content = load_and_validate(corpus, profile_path=SHARED_PROFILE)
        assert set(content.capabilities) == {"base", "left", "right", "top"}


class TestErrorAccumulation:
    def test_several_problems_are_reported_together(self, tmp_path: Path) -> None:
        """Fixing content one error per run is the slow version of §10.7."""
        corpus = tmp_path / "content"
        (corpus / "capabilities").mkdir(parents=True)
        (corpus / "capabilities" / "broken.yaml").write_text(
            "- id: one\n"
            "  name: One\n"
            "  requires: {item: missing_a}\n"
            "- id: two\n"
            "  name: Two\n"
            "  requires: {item: missing_b}\n"
            "  grants: [nope]\n",
            encoding="utf-8",
        )
        with pytest.raises(ContentValidationError) as caught:
            load_and_validate(corpus, profile_path=SHARED_PROFILE)

        assert len(caught.value.errors) == 3
        assert "3 content problems found" in str(caught.value)


class TestLoaderFailures:
    def test_a_missing_content_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ContentValidationError, match="does not exist"):
            load_content(tmp_path / "absent")

    def test_a_missing_scoring_profile_is_an_error(self, tmp_path: Path) -> None:
        corpus = tmp_path / "content"
        corpus.mkdir()
        with pytest.raises(ContentValidationError, match="scoring profile is missing"):
            load_content(corpus)

    def test_malformed_yaml_names_the_line(self, tmp_path: Path) -> None:
        corpus = tmp_path / "content"
        (corpus / "items").mkdir(parents=True)
        (corpus / "items" / "broken.yaml").write_text(
            "id: a\n  name: [unclosed\n", encoding="utf-8"
        )
        _content, errors = parse_corpus(corpus, profile_path=SHARED_PROFILE)
        assert errors
        assert any("not valid YAML" in error.message for error in errors)

    def test_an_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        """extra='forbid' — a typo would otherwise silently take a default."""
        corpus = tmp_path / "content"
        (corpus / "items").mkdir(parents=True)
        (corpus / "items" / "typo.yaml").write_text(
            "id: voidwaker\nname: Voidwaker\nprice_moed: live\n", encoding="utf-8"
        )
        with pytest.raises(ContentValidationError, match="price_moed"):
            load_content(corpus, profile_path=SHARED_PROFILE)

    def test_the_requirement_trap_is_caught_during_loading(self, tmp_path: Path) -> None:
        """§10.2's missing space, reaching the validator through a real content file."""
        corpus = tmp_path / "content"
        (corpus / "capabilities").mkdir(parents=True)
        (corpus / "capabilities" / "trap.yaml").write_text(
            "id: trap\nname: Trap\nrequires:\n  all_of:\n    - skill: {magic:94}\n",
            encoding="utf-8",
        )
        with pytest.raises(ContentValidationError, match="space after the colon"):
            load_content(corpus, profile_path=SHARED_PROFILE)


class TestCli:
    def test_exit_zero_on_a_valid_corpus(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--content-dir", str(MINIMAL), "--profile", str(SHARED_PROFILE)])
        assert code == 0
        assert "content OK" in capsys.readouterr().out

    @pytest.mark.parametrize(("directory", "expected"), CORRUPT_CORPORA)
    def test_exit_nonzero_on_each_corrupt_corpus(
        self, directory: str, expected: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`make validate-content` must fail loudly on all ten."""
        corpus = CORRUPT / directory
        code = main(["--content-dir", str(corpus), "--profile", str(profile_for(corpus))])
        assert code == 1
        assert expected in capsys.readouterr().err

    def test_module_entry_point_is_wired(self) -> None:
        """`make validate-content` runs `python -m tracker.content.validate`."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tracker.content.validate",
                "--content-dir",
                str(CORRUPT / "08_capability_cycle"),
                "--profile",
                str(SHARED_PROFILE),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "form a cycle" in result.stderr
