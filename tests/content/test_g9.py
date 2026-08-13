"""G9 — *"No game content lives in Python or Java code."* (§10.8)

The original plan asserted this invariant without a test. It is mechanically checkable:
copy the real corpus, drop new YAML into it, and confirm the loader picks it up with
**zero** code changes. If someone later moves a capability list into a Python constant,
this fails.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tracker.content.validate import load_and_validate
from tracker.domain.types import Confidence, MilestoneClass, PracticeDomain

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"


def clone_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "content"
    shutil.copytree(CONTENT_ROOT, corpus)
    return corpus


def test_a_new_capability_needs_no_code_change(tmp_path: Path) -> None:
    corpus = clone_corpus(tmp_path)
    (corpus / "capabilities" / "dragon_dagger_specs.yaml").write_text(
        "id: dragon_dagger_specs\n"
        "name: Dragon dagger spec combos\n"
        "recommended_readiness: high\n"
        "pvp_value: 0.65\n"
        "requires:\n"
        "  all_of:\n"
        "    - capability: budget_nh\n"
        "    - milestone: comfortable_4_way_switches\n"
        "    - skill: {attack: 60}\n",
        encoding="utf-8",
    )

    content = load_and_validate(corpus)

    added = content.capabilities["dragon_dagger_specs"]
    assert added.name == "Dragon dagger spec combos"
    assert added.recommended_readiness is Confidence.HIGH
    assert added.requires is not None
    assert added.requires.type == "all_of"


def test_a_new_roadmap_needs_no_code_change(tmp_path: Path) -> None:
    """§4.2 — a playstyle is a set of weights, never a code path."""
    corpus = clone_corpus(tmp_path)
    (corpus / "roadmaps" / "zerker.yaml").write_text(
        "id: zerker\nname: Zerker\ncapabilities:\n  budget_nh: 1.00\n  anti_pk: 0.80\n",
        encoding="utf-8",
    )

    content = load_and_validate(corpus)

    assert content.roadmaps["zerker"].capabilities == {"budget_nh": 1.00, "anti_pk": 0.80}


def test_a_new_milestone_and_practice_group_need_no_code_change(tmp_path: Path) -> None:
    corpus = clone_corpus(tmp_path)
    (corpus / "milestones" / "extra.yaml").write_text(
        "- id: smite_switching\n"
        "  name: Smite switching\n"
        "  class: execution\n"
        "  kind: self_attested\n"
        "  practice_group: nh_fundamentals\n"
        "  practiced_by: [lms, nh_combat]\n",
        encoding="utf-8",
    )

    content = load_and_validate(corpus)

    added = content.milestones["smite_switching"]
    assert added.class_ is MilestoneClass.EXECUTION
    assert added.practiced_by == (PracticeDomain.LMS, PracticeDomain.NH_COMBAT)
    assert "smite_switching" in {m.id for m in content.milestones_in_group("nh_fundamentals")}


def test_a_new_quest_item_and_training_method_need_no_code_change(tmp_path: Path) -> None:
    corpus = clone_corpus(tmp_path)
    # Deliberately fictional. Every quest RuneLite reports is already declared by the
    # generated registry, so a real id would collide (§10.7) — but an id no code has ever
    # seen is the stronger test of G9's claim anyway: the loader must accept it because it
    # is *content*, not because it recognises the name.
    (corpus / "quests" / "extra.yaml").write_text(
        "- id: the_hypothetical_quest\n  name: The Hypothetical Quest\n  quest_points: 3\n",
        encoding="utf-8",
    )
    (corpus / "items" / "extra.yaml").write_text(
        "- id: dragon_claws\n"
        "  name: Dragon claws\n"
        "  item_id: 13652\n"
        "  price_mode: live\n"
        "  fallback_price_gp: 95000000\n",
        encoding="utf-8",
    )
    (corpus / "training_methods" / "extra.yaml").write_text(
        "- id: attack_fast\n"
        "  name: Attack — fast\n"
        "  skill: attack\n"
        "  xp_per_hour: 120000\n"
        "  level_range: {min: 60, max: 99}\n"
        "  cost_per_hour_gp: 900000\n"
        "  requires:\n"
        "    quest: the_hypothetical_quest\n",
        encoding="utf-8",
    )

    content = load_and_validate(corpus)

    assert "the_hypothetical_quest" in content.quests
    assert content.item_by_numeric_id(13652) is not None
    # Fastest first — this is the order §8.2 step 3 walks.
    assert [m.id for m in content.methods_for_skill("attack")] == [
        "attack_fast",
        "attack_conservative",
    ]


def test_retuning_the_profile_needs_no_code_change(tmp_path: Path) -> None:
    """§10.8 names the scoring profile as content precisely so Step 13 can retune it."""
    corpus = clone_corpus(tmp_path)
    (corpus / "scoring" / "profile.yaml").write_text(
        "scoring_profile:\n"
        "  version: 2\n"
        "  tuned_against_corpus: golden-2026-08\n"
        "  tau_hours: 6\n"
        "  kappa_gp: {high: 5000000, normal: 18000000, low: 60000000}\n"
        "  observation_aged_days: 21\n"
        "  weights:\n"
        "    pvp_value: 1.0\n"
        "    leverage: 0.9\n"
        "    proximity: 0.5\n"
        "    effort_decay: 0.6\n"
        "    cost_decay: 0.4\n"
        "    method_unlock: 0.3\n",
        encoding="utf-8",
    )

    profile = load_and_validate(corpus).profile

    assert profile.version == 2
    assert profile.tuned_against_corpus == "golden-2026-08"
    assert profile.tau_hours == 6
    assert profile.observation_aged_days == 21


def test_a_broken_addition_is_still_rejected(tmp_path: Path) -> None:
    """G9 is "no code change", not "no validation" — the two are independent."""
    corpus = clone_corpus(tmp_path)
    (corpus / "capabilities" / "broken.yaml").write_text(
        "id: broken\nname: Broken\nrequires:\n  item: no_such_item\n", encoding="utf-8"
    )

    from tracker.content.loader import ContentValidationError

    try:
        load_and_validate(corpus)
    except ContentValidationError as exc:
        assert "references item 'no_such_item'" in str(exc)
    else:  # pragma: no cover — the corpus is deliberately broken
        raise AssertionError("a dangling reference must not load")
