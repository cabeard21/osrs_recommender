from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tracker.content.loader import ContentValidationError
from tracker.content.requirements import SkillLeaf
from tracker.content.schema import RoadmapGuide
from tracker.content.validate import load_and_validate

HERE = Path(__file__).parent
SHARED_PROFILE = HERE / "fixtures" / "profile.yaml"


VALID_GUIDE = """\
id: pvm_bossing_ladder
name: PvM Bossing Ladder
roadmap_id: pvm_ladder
source:
  url: https://oldschool.runescape.wiki/w/Guide:Bossing_Ladder?oldid=15319480
  revision: 15319480
  checked_at: 2026-09-04
  license: CC BY-NC-SA 3.0
tiers:
  - id: easy
    name: Easy
    summary: Introductory bosses and foundational preparation.
    capability_id: pvm_easy
    preparation:
      - id: basic_combat
        label: Build basic combat stats
        completion: {skill: {attack: 40}}
        candidate_ids: [train_attack_40]
      - id: bring_food
        label: Bring food appropriate to the encounter
    encounters:
      - id: giant_mole
        name: Giant Mole
        access: {skill: {attack: 20}}
        recommendations: {skill: {attack: 40}}
        mechanics: [Watch for the mole burrowing away.]
        rewards: [Mole parts]
        wiki_url: https://oldschool.runescape.wiki/w/Giant_Mole
"""


def _write_base_corpus(tmp_path: Path, guide: str = VALID_GUIDE) -> Path:
    corpus = tmp_path / "content"
    for directory in ("skills", "capabilities", "roadmaps", "candidates", "roadmap_guides"):
        (corpus / directory).mkdir(parents=True)
    (corpus / "skills" / "skills.yaml").write_text(
        "- {id: attack, name: Attack, is_combat: true}\n", encoding="utf-8"
    )
    (corpus / "capabilities" / "pvm.yaml").write_text(
        "- {id: pvm_easy, name: Easy PvM}\n- {id: pvm_other, name: Other PvM}\n",
        encoding="utf-8",
    )
    (corpus / "roadmaps" / "pvm.yaml").write_text(
        "id: pvm_ladder\nname: PvM ladder\ncapabilities: {pvm_easy: 0.5}\n",
        encoding="utf-8",
    )
    (corpus / "candidates" / "attack.yaml").write_text(
        "id: train_attack_40\nname: Train Attack to 40\nkind: skill_training\n"
        "completion: {skill: {attack: 40}}\n",
        encoding="utf-8",
    )
    (corpus / "roadmap_guides" / "pvm.yaml").write_text(guide, encoding="utf-8")
    return corpus


def test_guide_models_are_frozen_and_parse_both_requirement_kinds() -> None:
    guide = RoadmapGuide.model_validate(
        __import__("yaml").safe_load(VALID_GUIDE), context={"file": Path("guide.yaml")}
    )

    encounter = guide.tiers[0].encounters[0]
    assert isinstance(encounter.access, SkillLeaf)
    assert isinstance(encounter.recommendations, SkillLeaf)
    assert guide.source.revision == 15319480
    with pytest.raises(ValidationError, match="frozen"):
        guide.name = "Changed"  # type: ignore[misc]


def test_loader_indexes_roadmap_guides(tmp_path: Path) -> None:
    content = load_and_validate(_write_base_corpus(tmp_path), profile_path=SHARED_PROFILE)

    assert set(content.roadmap_guides) == {"pvm_bossing_ladder"}
    assert content.location_of("roadmap_guide", "pvm_bossing_ladder").file is not None


def test_cross_validation_reports_all_invalid_guide_content(tmp_path: Path) -> None:
    guide = VALID_GUIDE.replace("roadmap_id: pvm_ladder", "roadmap_id: missing")
    guide = guide.replace("capability_id: pvm_easy", "capability_id: missing")
    guide = guide.replace("candidate_ids: [train_attack_40]", "candidate_ids: [missing]")
    guide = guide.replace(
        "wiki_url: https://oldschool.runescape.wiki/w/Giant_Mole",
        "wiki_url: http://example.com/mole",
    )
    corpus = _write_base_corpus(tmp_path, guide)

    with pytest.raises(ContentValidationError) as caught:
        load_and_validate(corpus, profile_path=SHARED_PROFILE)

    message = str(caught.value)
    assert "roadmap 'missing'" in message
    assert "capability 'missing'" in message
    assert "candidate 'missing'" in message
    assert "must use HTTPS" in message


def test_tier_capability_must_belong_to_the_selected_roadmap(tmp_path: Path) -> None:
    corpus = _write_base_corpus(
        tmp_path, VALID_GUIDE.replace("capability_id: pvm_easy", "capability_id: pvm_other")
    )

    with pytest.raises(ContentValidationError, match="not included in roadmap 'pvm_ladder'"):
        load_and_validate(corpus, profile_path=SHARED_PROFILE)


def test_nested_tier_ids_must_be_unique(tmp_path: Path) -> None:
    duplicate = """\
  - id: easy
    name: Easy copy
    summary: Copy.
    capability_id: pvm_easy
    encounters:
      - id: copied
        name: Copied
        mechanics: [Learn.]
        rewards: [Practice.]
        wiki_url: https://example.com/copied
  - id: easy"""
    corpus = _write_base_corpus(tmp_path, VALID_GUIDE.replace("  - id: easy", duplicate))
    with pytest.raises(ContentValidationError, match="duplicate tier id 'easy'"):
        load_and_validate(corpus, profile_path=SHARED_PROFILE)


def test_nested_encounter_ids_must_be_unique(tmp_path: Path) -> None:
    duplicate = """\
      - id: giant_mole
        name: Copy
        mechanics: [Learn.]
        rewards: [Practice.]
        wiki_url: https://example.com/copy
      - id: giant_mole"""
    corpus = _write_base_corpus(tmp_path, VALID_GUIDE.replace("      - id: giant_mole", duplicate))
    with pytest.raises(ContentValidationError, match="duplicate encounter id 'giant_mole'"):
        load_and_validate(corpus, profile_path=SHARED_PROFILE)


def test_checkable_preparation_requires_a_candidate() -> None:
    raw = __import__("yaml").safe_load(VALID_GUIDE)
    del raw["tiers"][0]["preparation"][0]["candidate_ids"]

    with pytest.raises(ValidationError, match="checkable preparation step"):
        RoadmapGuide.model_validate(raw)


def test_guide_requirement_references_are_validated(tmp_path: Path) -> None:
    corpus = _write_base_corpus(
        tmp_path, VALID_GUIDE.replace("{attack: 20}", "{unknown_skill: 20}")
    )
    with pytest.raises(ContentValidationError, match="skill 'unknown_skill'"):
        load_and_validate(corpus, profile_path=SHARED_PROFILE)


def test_source_url_must_use_https(tmp_path: Path) -> None:
    corpus = _write_base_corpus(
        tmp_path,
        VALID_GUIDE.replace(
            "https://oldschool.runescape.wiki/w/Guide:Bossing_Ladder?oldid=15319480",
            "http://example.com/guide",
        ),
    )
    with pytest.raises(ContentValidationError, match="must use HTTPS"):
        load_and_validate(corpus, profile_path=SHARED_PROFILE)
