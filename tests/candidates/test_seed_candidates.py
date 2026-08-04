"""The shipped `content/candidates/` corpus and the §10.6 schema rules that guard it.

Like `tests/content/test_seed_corpus.py`, this is a test of *content*: these candidates
are the fixture step 6's ranking and step 13's scenarios both run against, so a silent
edit to an `advances` weight would otherwise surface as an inexplicable reordering two
steps later.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tracker.content.loader import Content, ContentValidationError
from tracker.content.schema import Candidate
from tracker.content.validate import load_and_validate
from tracker.domain.types import CandidateKind

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: Every id later steps name: §16.2's pairwise judgments and step 13's scenarios.
REQUIRED_IDS = {
    "train_magic_87_to_94",
    "buy_voidwaker",
    "complete_desert_treasure_i",
    "unlock_rigour",
    "train_woodcutting",
    "buy_high_risk_gear",
    "train_strength_to_99",
    "unlock_protect_item",
}


@pytest.fixture(scope="module")
def content() -> Content:
    return load_and_validate(CONTENT_ROOT)


class TestShape:
    def test_every_id_later_steps_reference_exists(self, content: Content) -> None:
        assert REQUIRED_IDS <= set(content.candidates)

    def test_every_candidate_declares_a_completion_predicate(self, content: Content) -> None:
        """§10.7 — a candidate that can never be complete would rank forever."""
        for shipped in content.candidates.values():
            assert shipped.completion is not None, shipped.id

    def test_every_advances_target_is_a_declared_capability(self, content: Content) -> None:
        for shipped in content.candidates.values():
            for capability_id in shipped.advances:
                assert capability_id in content.capabilities, f"{shipped.id} → {capability_id}"

    def test_every_advances_weight_is_in_the_unit_interval(self, content: Content) -> None:
        for shipped in content.candidates.values():
            for capability_id, weight in shipped.advances.items():
                assert 0.0 <= weight <= 1.0, f"{shipped.id} → {capability_id}"

    def test_the_corpus_covers_four_of_the_five_kinds(self, content: Content) -> None:
        """`practice` is the exception by design: §10.6 says refreshers are *synthesized*
        from practice groups, never authored into `candidates/`."""
        kinds = {shipped.kind for shipped in content.candidates.values()}
        assert kinds == {
            CandidateKind.SKILL_TRAINING,
            CandidateKind.ACQUISITION,
            CandidateKind.QUEST,
            CandidateKind.UNLOCK,
        }

    def test_a_candidate_may_share_an_id_with_a_capability(self, tmp_path: Path) -> None:
        """Ids are unique per kind, not globally — exactly as `anti_pk` is already both a
        capability and a roadmap. Two *candidates* called `anti_pk` would still fail."""
        corpus = tmp_path / "content"
        shutil.copytree(CONTENT_ROOT, corpus)
        (corpus / "candidates" / "clash.yaml").write_text(
            "id: anti_pk\n"
            "name: Get comfortable anti-PKing\n"
            "kind: unlock\n"
            "advances: {anti_pk: 1.0}\n"
            "completion:\n"
            "  milestone: first_anti_pk\n",
            encoding="utf-8",
        )

        loaded = load_and_validate(corpus)

        assert "anti_pk" in loaded.candidates
        assert "anti_pk" in loaded.capabilities
        assert (
            loaded.location_of("candidate", "anti_pk").file
            != loaded.location_of("capability", "anti_pk").file
        )


class TestNoFactorIsAuthored:
    """§10.6, D11: *"None is authored directly, so no content file can assert its own
    priority."*"""

    @pytest.mark.parametrize("factor", ["pvp_value", "leverage", "proximity", "priority"])
    def test_a_candidate_declaring_a_factor_is_rejected(self, tmp_path: Path, factor: str) -> None:
        corpus = tmp_path / "content"
        (corpus / "candidates").mkdir(parents=True)
        (corpus / "candidates" / "cheat.yaml").write_text(
            "id: cheat\n"
            "name: Asserts its own priority\n"
            "kind: unlock\n"
            f"{factor}: 1.0\n"
            "completion:\n"
            "  unlock: something\n",
            encoding="utf-8",
        )
        with pytest.raises(ContentValidationError, match=factor):
            load_and_validate(corpus, profile_path=CONTENT_ROOT / "scoring" / "profile.yaml")

    def test_the_schema_has_no_factor_effort_or_cost_field_at_all(self) -> None:
        """§8 estimates hours and gp from the training methods and item prices the
        `completion` predicate names; an authored `gp_cost` would let a candidate declare
        itself cheap, which is the same failure as an authored `pvp_value`."""
        assert not set(Candidate.model_fields) & {
            "pvp_value",
            "leverage",
            "proximity",
            "priority",
            "hours",
            "gp_cost",
        }


class TestTheSddWorkedExample:
    """`train_magic_87_to_94` is §10.6's own YAML, and several later tests read it back."""

    def test_matches_the_schema_block_in_the_sdd(self, content: Content) -> None:
        train_magic = content.candidates["train_magic_87_to_94"]

        assert train_magic.kind is CandidateKind.SKILL_TRAINING
        assert train_magic.advances == {"ice_barrage_nh": 1.00, "deep_wildy_nh": 0.70}
        assert train_magic.requires is not None
        assert train_magic.completion.to_yaml() == {"skill": {"magic": 94}}
        assert train_magic.grants_facts is not None

    def test_advances_and_grants_facts_are_separate_claims(self, content: Content) -> None:
        """§10.6 — `grants_facts` is objective, `advances` is editorial. Training Magic
        fully enables Ice Barrage NH while only partly advancing Deep Wilderness NH,
        which it does not unlock at all."""
        train_magic = content.candidates["train_magic_87_to_94"]

        assert train_magic.advances["deep_wildy_nh"] < 1.0
        assert train_magic.grants_facts is not None
        assert train_magic.grants_facts.to_yaml() == {"skill": {"magic": 94}}

    def test_desert_treasure_grants_the_unlock_other_content_gates_on(
        self, content: Content
    ) -> None:
        """This is what `leverage` reads: without `unlock: ancient_magicks` among the
        granted facts, completing DT1 would appear to unblock nothing."""
        granted = content.candidates["complete_desert_treasure_i"].grants_facts
        assert granted is not None
        assert {"unlock": "ancient_magicks"} in granted.to_yaml()["all_of"]

    def test_woodcutting_advances_nothing(self, content: Content) -> None:
        """The control: it must rank last because the content says it is irrelevant, not
        because any code knows what woodcutting is (§10.8)."""
        assert content.candidates["train_woodcutting"].advances == {}


class TestG9:
    """§10.8 — adding a candidate is content, never a code change."""

    def test_a_new_candidate_needs_no_code_change(self, tmp_path: Path) -> None:
        corpus = tmp_path / "content"
        shutil.copytree(CONTENT_ROOT, corpus)
        (corpus / "candidates" / "extra.yaml").write_text(
            "id: unlock_augury\n"
            "name: Unlock Augury\n"
            "kind: unlock\n"
            "advances:\n"
            "  ice_barrage_nh: 0.35\n"
            "  deep_wildy_nh: 0.30\n"
            "completion:\n"
            "  all_of:\n"
            "    - skill: {prayer: 77}\n"
            "    - unlock: augury\n"
            "grants_facts:\n"
            "  unlock: augury\n",
            encoding="utf-8",
        )

        added = load_and_validate(corpus).candidates["unlock_augury"]

        assert added.kind is CandidateKind.UNLOCK
        assert added.advances == {"ice_barrage_nh": 0.35, "deep_wildy_nh": 0.30}
        assert added.completion.type == "all_of"

    def test_a_broken_addition_is_still_rejected(self, tmp_path: Path) -> None:
        corpus = tmp_path / "content"
        shutil.copytree(CONTENT_ROOT, corpus)
        (corpus / "candidates" / "extra.yaml").write_text(
            "id: broken\n"
            "name: Broken\n"
            "kind: acquisition\n"
            "advances: {ice_barrage_nh: 0.5}\n"
            "completion:\n"
            "  item: no_such_item\n",
            encoding="utf-8",
        )
        with pytest.raises(ContentValidationError, match="references item 'no_such_item'"):
            load_and_validate(corpus)
