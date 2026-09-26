"""The quest generator, and the shipped corpus it produced (Step 4).

Two distinct claims are tested here, and they fail for different reasons:

* the **parser** turns vendored wikitext into the requirement tree a human would have
  written — checked against Desert Treasure I, whose requirements were hand-authored
  independently before any of this existed, so agreement is corroboration rather than a
  restatement of the generator's own output;
* the **shipped files** are what the generator produces from the vendored data right now,
  which is what makes a hand-edit to a generated file a test failure instead of a silent
  loss at the next run.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from tools import generate_candidates as gen
from tracker.content.loader import Content
from tracker.content.requirements import QuestLeaf, SkillLeaf, iter_leaves
from tracker.content.validate import load_and_validate

REPO_ROOT = Path(__file__).parent.parent.parent
CONTENT_ROOT = REPO_ROOT / "content"
DATA_DIR = REPO_ROOT / "tools" / "data"


@pytest.fixture(scope="module")
def vendored() -> dict:
    return json.loads((DATA_DIR / "osrs_quests.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus() -> Content:
    """The real, shipped corpus — generated subdirectories included."""
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture(scope="module")
def generated_candidates() -> list[dict]:
    path = CONTENT_ROOT / "candidates" / "generated" / "quests.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def test_skill_requirements_come_from_the_structured_attributes() -> None:
    """The wiki renders levels as ``data-skill``/``data-level``; prose is not parsed."""
    text = (
        '* <span class="scp" data-skill="Magic" data-level="75">[[File:Magic icon.png]] '
        "75 [[Magic]]</span>\n"
        '* <span class="scp" data-skill="Thieving" data-level="53">53 [[Thieving]]</span>\n'
    )

    skills, others, unmodelled = gen.parse_skill_requirements(text)

    assert skills == {"magic": 75, "thieving": 53}
    assert others == {}
    assert unmodelled == []


def test_the_highest_level_wins_when_a_skill_is_listed_twice() -> None:
    """Taking the last occurrence would make the tree depend on an editor's typing order."""
    text = (
        '<span data-skill="Magic" data-level="50"></span>\n'
        '<span data-skill="Magic" data-level="75"></span>\n'
    )

    skills, _, _ = gen.parse_skill_requirements(text)

    assert skills == {"magic": 75}


def test_quest_points_and_combat_level_become_their_own_leaves() -> None:
    """Both are rendered as skill spans by the wiki but are not skills (§9.1)."""
    text = (
        '<span data-skill="Quest points" data-level="200"></span>\n'
        '<span data-skill="Combat level" data-level="85"></span>\n'
    )

    skills, others, _ = gen.parse_skill_requirements(text)

    assert skills == {}
    assert others == {"quest_points": 200, "combat_level": 85}


def test_an_unmodelled_skill_is_reported_rather_than_dropped() -> None:
    """Sailing is a real requirement this corpus cannot express — it must be visible."""
    text = '<span data-skill="Sailing" data-level="20"></span>'

    skills, others, unmodelled = gen.parse_skill_requirements(text)

    assert (skills, others) == ({}, {})
    assert unmodelled == ["Sailing"]


def test_an_unknown_skill_refuses_to_generate(vendored: dict) -> None:
    """A skill nobody has classified aborts the run.

    This is the guard that makes ``KNOWN_UNMODELLED_SKILLS`` honest: were a new wiki skill
    to appear, silently dropping it would leave a quest looking startable when it is not,
    and nothing downstream could tell.
    """
    quest = {
        "id": "invented",
        "name": "Invented",
        "wiki_page": "Invented",
        "requirements": '<span data-skill="Bartering" data-level="10"></span>',
    }

    with pytest.raises(gen.GenerationError, match="bartering"):
        gen.generate_quests(
            {"quests": [quest]}, authored_ids=set(), authored_completions=set(), skills=set()
        )


def test_icon_links_are_not_mistaken_for_prerequisites() -> None:
    """Every skill line carries ``[[File:Magic icon.png]]``. An icon is not a quest."""
    text = "* [[File:Magic icon.png|link=Magic]] 75 [[Magic]]\n"

    assert gen.parse_quest_links(text) == ["Magic"]


def test_prerequisites_of_prerequisites_are_not_restated() -> None:
    """Depth 3 is the prerequisite of a prerequisite, which the graph already implies.

    Desert Treasure I lists Death Plateau beneath Troll Stronghold. Emitting both would
    add an edge that changes no evaluation — Troll Stronghold cannot be complete without
    it — while doubling the size of every requirement tree.
    """
    text = (
        "* Completion of the following quests:\n"
        "** [[Troll Stronghold]]\n"
        "*** [[Death Plateau]]\n"
        "** [[Waterfall Quest]]\n"
    )

    assert gen.parse_quest_links(text) == ["Troll Stronghold", "Waterfall Quest"]


def test_the_parser_reproduces_the_hand_authored_desert_treasure_requirements(
    vendored: dict,
) -> None:
    """The one place generated and hand-authored content can be compared directly.

    ``content/candidates/quests.yaml`` declares DT1's skill requirements, written by a
    human from the same game long before this generator existed. The parser must agree.
    """
    quest = next(q for q in vendored["quests"] if q["id"] == "desert_treasure_i")
    authored = yaml.safe_load(
        (CONTENT_ROOT / "candidates" / "quests.yaml").read_text(encoding="utf-8")
    )
    clauses = next(c for c in authored if c["id"] == "complete_desert_treasure_i")["requires"][
        "all_of"
    ]
    # Skill clauses only. DT1's `quest:` clauses were added *from* this generator once the
    # registry declared all 211 quests, so asserting them here would be circular — the
    # skill half is the part a human wrote independently, and it is the whole corroboration.
    expected = {
        skill: level
        for clause in clauses
        if "skill" in clause
        for skill, level in clause["skill"].items()
    }

    skills, _, _ = gen.parse_skill_requirements(quest["requirements"])

    assert skills == expected


# ---------------------------------------------------------------------------
# The shipped corpus
# ---------------------------------------------------------------------------


def test_the_shipped_generated_files_match_what_the_generator_produces() -> None:
    """``--check``'s claim, as a test. A hand-edit to a generated file fails here."""
    assert gen.main(["--check"]) == 0


def test_every_generated_candidate_advances_nothing(generated_candidates: list[dict]) -> None:
    """§10.6 — a generator may not assert priority, and ``advances`` is where it would."""
    weighted = [c["id"] for c in generated_candidates if c["advances"]]

    assert weighted == [], f"generated candidates carry editorial weight: {weighted}"


def test_generated_candidates_declare_their_provenance(generated_candidates: list[dict]) -> None:
    assert {c["source"] for c in generated_candidates} == {"generated"}


def test_an_authored_candidate_is_not_shadowed_by_a_generated_twin(
    generated_candidates: list[dict],
) -> None:
    """Desert Treasure I is hand-weighted; generation must leave it alone.

    Matching is on the ``completion`` predicate rather than the id, because that is what
    collides: two candidates completing on the same fact both finish at once, and the
    hand-weighted one is the one worth keeping.
    """
    completions = [c["completion"]["quest"] for c in generated_candidates]

    assert "desert_treasure_i" not in completions


def test_the_generated_corpus_loads_and_cross_validates(corpus: Content) -> None:
    """The whole point: ``rglob`` picks the subdirectory up with no loader change (G9)."""
    generated = [c for c in corpus.candidates.values() if c.source == "generated"]

    assert len(generated) > 200
    assert all(candidate.completion is not None for candidate in generated)


# ---------------------------------------------------------------------------
# Skill training bands (Step 5)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generated_bands() -> list[dict]:
    path = CONTENT_ROOT / "candidates" / "generated" / "skill_bands.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_band_boundaries_come_from_the_corpus_not_from_a_fixed_ladder() -> None:
    """A level a capability names becomes a band edge; change the capability and it moves."""
    assert 53 in gen.band_boundaries({53})
    assert 53 not in gen.band_boundaries(set())


def test_band_boundaries_always_span_the_whole_range() -> None:
    """Without a floor and a ceiling the first and last bands would be unreachable."""
    ladder = gen.band_boundaries({53})

    assert ladder[0] == gen.MIN_LEVEL
    assert ladder[-1] == gen.MAX_LEVEL
    assert ladder == sorted(set(ladder))


def test_each_band_requires_the_level_below_it() -> None:
    """What makes exactly one band per skill actionable at a time."""
    bands = gen.generate_skill_bands({"magic": {50}}, authored_targets=set())

    ladder = gen.band_boundaries({50})
    by_target = {band["completion"]["skill"]["magic"]: band for band in bands}

    assert "requires" not in bands[0], "the floor band gates on nothing"
    for start, target in pairwise(ladder[1:]):
        assert by_target[target]["requires"] == {"skill": {"magic": start}}


def test_a_band_is_named_by_its_target_not_by_its_floor() -> None:
    """§8 estimates from the *player's* level, so a floor in the name states a falsehood.

    A Magic-35 account offered "Train Magic 1 → 50" beside a 2.2 hour estimate is being
    told something untrue about itself; the floor is a corpus boundary, not a position.
    """
    bands = gen.generate_skill_bands({"magic": {50}}, authored_targets=set())

    assert bands[0]["name"] == "Train Magic to 50"
    assert all("→" not in band["name"] for band in bands)


def test_a_band_an_authored_candidate_already_completes_on_is_skipped() -> None:
    """``train_magic_87_to_94`` keeps its editorial weight; no generated twin appears."""
    bands = gen.generate_skill_bands({"magic": {94}}, authored_targets={("magic", 94)})

    assert all(band["completion"]["skill"]["magic"] != 94 for band in bands)


def test_only_skills_the_corpus_references_get_bands(generated_bands: list[dict]) -> None:
    """Scoping decision, stated: a skill nothing references has no boundaries of its own.

    Generating a ladder for all 23 skills would add ~180 candidates for Farming, Cooking
    and the rest — none of which any capability here mentions, all of which would advance
    nothing and estimate against a fallback method.
    """
    banded = {band["id"].split("_")[1] for band in generated_bands}

    assert "magic" in banded and "defence" in banded
    # The PvM ladder's gates, which is the whole mechanism: a rung gating on Slayer 55 and
    # Herblore 78 is what makes bands ending at those levels exist. Without them the ladder
    # would be five goals with no path between them.
    assert "slayer" in banded and "herblore" in banded and "prayer" in banded
    assert "farming" not in banded and "cooking" not in banded


def test_the_shipped_bands_all_declare_a_skill_completion(generated_bands: list[dict]) -> None:
    for band in generated_bands:
        assert band["kind"] == "skill_training"
        assert band["source"] == "generated"
        assert band["advances"] == {}
        assert list(band["completion"]["skill"]) != []


# ---------------------------------------------------------------------------
# Achievement diaries (Step 6)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generated_diaries() -> list[dict]:
    path = CONTENT_ROOT / "candidates" / "generated" / "diaries.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_a_tier_requires_the_hardest_ask_across_its_tasks() -> None:
    """The maximum, not the sum and not the last one seen.

    A tier is complete only when every task in it is, so the hardest ask on each skill is
    a *floor* derived from the tasks themselves rather than an estimate of difficulty.
    """
    wikitext = "|{{SCP|Agility|39|link=y}}\n|{{SCP|Agility|51}}\n|{{SCP|Magic|54}}\n"

    skills, others, quests = gen.parse_diary_requirements(wikitext)

    assert skills == {"agility": 51, "magic": 54}
    assert (others, quests) == ({}, [])


def test_the_quest_marker_names_its_quest_in_the_following_link() -> None:
    """``{{SCP|Quest}}`` carries no level; the quest is the link beside it."""
    wikitext = "|*{{SCP|Quest}} Completion of [[Rune Mysteries]]\n|*{{SCP|Thieving|5}}\n"

    skills, _, quests = gen.parse_diary_requirements(wikitext)

    assert skills == {"thieving": 5}
    assert quests == ["Rune Mysteries"]


def test_diary_pages_abbreviate_quest_points_and_combat_level() -> None:
    """``{{SCP|Quest|32}}`` is quest *points*; the level-less form is a quest.

    Diary pages abbreviate what quest pages spell out, and reading either as a skill would
    have produced a ``skill: {quest: 32}`` leaf that §10.7 rejects — which is how this was
    found.
    """
    skills, others, _ = gen.parse_diary_requirements("|{{SCP|Quest|32}}\n|{{SCP|Combat|85}}\n")

    assert skills == {}
    assert others == {"quest_points": 32, "combat_level": 85}


def test_an_unknown_diary_skill_refuses_to_generate() -> None:
    """Same guard as quests: an omitted requirement makes a tier look startable."""
    data = {
        "diaries": [{"key": "diary_x_easy", "name": "X", "requirements": "{{SCP|Bartering|3}}"}]
    }

    with pytest.raises(gen.GenerationError, match="bartering"):
        gen.generate_diaries(data, quest_lookup={}, authored_completions=set(), skills={"magic"})


def test_every_diary_tier_is_generated(generated_diaries: list[dict]) -> None:
    """12 regions × 4 tiers, matching the plugin's varbit enumeration exactly."""
    keys = {diary["completion"]["unlock"] for diary in generated_diaries}

    assert len(generated_diaries) == 48
    assert len(keys) == 48
    assert {key.rsplit("_", 1)[1] for key in keys} == {"easy", "medium", "hard", "elite"}


def test_diary_candidates_complete_on_the_plugin_key(generated_diaries: list[dict]) -> None:
    """No new payload field: these facts have been arriving since step 12b."""
    for diary in generated_diaries:
        assert diary["kind"] == "unlock"
        assert diary["advances"] == {}
        assert diary["completion"]["unlock"].startswith("diary_")
        assert diary["grants_facts"] == diary["completion"]


def test_diary_requirements_reach_the_corpus_as_real_gates(corpus: Content) -> None:
    """Spot-check against the game: Varrock Hard needs Farming 68 and Desert Treasure I."""
    candidate = corpus.candidates["complete_diary_varrock_hard"]
    assert candidate.requires is not None
    leaves = list(iter_leaves(candidate.requires))
    skills = {leaf.skill: leaf.level for leaf in leaves if isinstance(leaf, SkillLeaf)}
    quests = {leaf.quest_id for leaf in leaves if isinstance(leaf, QuestLeaf)}

    assert skills["farming"] == 68
    assert skills["hunter"] == 69
    assert "desert_treasure_i" in quests
