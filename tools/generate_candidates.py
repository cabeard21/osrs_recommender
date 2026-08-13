"""Turn vendored game data into content YAML — offline, deterministic, run by hand.

Modelled on :mod:`tools.tune_weights`: a tool that *writes content*, never something the
app imports. Nothing under ``tracker/`` may depend on this module, and this module reads
no database.

    python tools/generate_candidates.py all        # write the generated corpus
    python tools/generate_candidates.py --check    # regenerate in memory, fail on drift

**Generation asserts no priority.** §10.6's rule is that every scoring factor derives from
``advances``/``requires``/``completion``/``grants_facts``, so a generator that emitted a
``priority`` field would break the one invariant the whole ranking rests on. It emits
``advances: {}`` — the honest statement that nobody has yet said which capabilities a
quest advances. That is not a placeholder for a number this tool could have computed: how
much Monkey Madness advances "deep wilderness NH" is an editorial judgment, and inventing
one would be fabricating content semantics.

An empty ``advances`` is safe rather than merely legal. ``advances_value`` returns ``0.0``
for an empty map, so ``pvp_value`` is ε-floored and the candidate sorts to the bottom,
where Step 1's ``max_primary_entries`` cut keeps it off the page; and
``tracker.integrations.prices.scope`` already excludes empty-``advances`` candidates from
price scope, so nothing tries to price 211 quests.

**What generation does buy, measured rather than assumed.** The ``requires`` trees are the
real product: against the synced account they correctly block 122 of the 210 quests and 44
of the 48 diary tiers, entirely from facts the plugin already sends. Diaries are the
sharpest case — one tier reads back *complete*, three are actionable, and the rest are
gated. That is derived filtering, and it is what a "blocked" list is for.

**Combat achievements are deliberately not generated**, though their six ``ca_*`` keys
arrive with every sync. CA tiers unlock on a cumulative *points* threshold, and points are
not in the payload; nor does the wiki publish a per-tier requirement to derive one from.
Six candidates with no ``requires`` would each be permanently unblocked, permanently
zero-scored, and permanently wrong about whether the account could act on them — the same
trade this module refuses for an unmodelled skill.

**Quests do not get an order out of this; skill bands do.** Every generated *quest* scores
identically and the tie breaks alphabetically. ``pvp_value`` is 0 by construction
(``advances: {}``), and ``leverage`` — which one might expect to separate a prerequisite
quest from a leaf one — is 0 too: :func:`tracker.domain.candidates.unlock_flip_count`
counts *capabilities* whose requirements a candidate's facts would satisfy, and this
corpus's five capabilities gate on two quests between them. Quest-unblocks-quest is not a
thing ``leverage`` measures. So a generated quest is a known, valid, unblocked action with
no derived reason to outrank its neighbours, and ``max_primary_entries`` is what stops 88
of them filling the page.

Skill *bands* rank properly on the same empty ``advances``, because two factors that were
inert for quests are live for them: ``proximity`` and ``effort_decay`` both read §8's
sizing, and a five-level band is four hours where "train to 99" is three hundred. On the
synced account the top of the list becomes "Train Slayer to 10" at 0.0 hours and "Train
Magic to 50" at 2.2 — derived entirely from level facts, with nothing authored.

Either way the rule is the same: closing the remaining gap means authoring ``advances``,
which is the editorial judgment §10.6 reserves for a human and not one a generator may
make on its own.

**Authored content always wins.** Any quest already covered by a hand-authored candidate
or registry row is skipped entirely, so ``complete_desert_treasure_i`` keeps its editorial
``advances`` and is not shadowed by a generated twin. Adding weight to a generated entry
is done by moving it into an authored file and flipping ``source: authored``; ``--check``
only compares files this tool owns.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "tools" / "data"
DEFAULT_CONTENT_DIR = REPO_ROOT / "content"

#: The subdirectory this tool owns, inside each content kind it writes. Ownership is by
#: path: everything under it is regenerable, everything outside it is a human's.
GENERATED_DIR = "generated"

#: Wiki skill labels that are not skills in the §9.1 sense. Both already have their own
#: requirement leaf, so they are translated rather than dropped.
NON_SKILL_LABELS = {"Quest points": "quest_points", "Combat level": "combat_level"}

#: Wiki skills the corpus does not declare, with the reason. Anything *not* listed here
#: and not in ``content/skills`` aborts the run: a silently dropped requirement makes a
#: quest look startable when it is not, and that is worse than a failed generation.
#:
#: Sailing is a real skill the game has and this tracker does not model — neither
#: ``content/skills`` nor the WiseOldMan projection carries it, so a ``skill: {sailing:}``
#: leaf would fail §10.7 referential integrity. Declaring it is a content decision with a
#: sync-side dependency, not something a generator may make on its own.
KNOWN_UNMODELLED_SKILLS = {"Sailing"}

_LINK = re.compile(r"\[\[([^\]|#]+)")
_SKILL_SPAN = re.compile(r'data-skill="([^"]+)"\s+data-level="(\d+)"')

#: Quest prerequisites are listed under a "Completion of the following quests:" bullet, so
#: a direct prerequisite sits at depth 1 or 2. Depth 3 and beyond are the prerequisites
#: *of* those prerequisites, which the graph already implies — including them would bloat
#: every requirement tree with edges that change no evaluation.
MAX_QUEST_LINK_DEPTH = 2


# ---------------------------------------------------------------------------
# Parsing the vendored wikitext
# ---------------------------------------------------------------------------


def parse_skill_requirements(requirements: str) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Split the ``scp`` spans into skills, non-skill leaves, and unmodelled labels.

    The wiki renders every level requirement as ``data-skill="Magic" data-level="75"``,
    which is why this tool joins structured attributes rather than reading the prose
    beside them. The highest level wins where a skill appears twice — a quest listing
    Magic 50 and Magic 75 needs 75, and taking the last occurrence would depend on the
    order an editor happened to type them in.
    """
    skills: dict[str, int] = {}
    others: dict[str, int] = {}
    unmodelled: list[str] = []
    for label, raw_level in _SKILL_SPAN.findall(requirements):
        level = int(raw_level)
        if label in NON_SKILL_LABELS:
            key = NON_SKILL_LABELS[label]
            others[key] = max(others.get(key, 0), level)
        elif label in KNOWN_UNMODELLED_SKILLS:
            unmodelled.append(label)
        else:
            key = label.lower()
            skills[key] = max(skills.get(key, 0), level)
    return skills, others, unmodelled


def parse_quest_links(requirements: str) -> list[str]:
    """Wiki page titles named as prerequisites, in document order, deduplicated.

    ``[[File:...]]`` links are skipped — every skill requirement carries an icon, and an
    icon is not a prerequisite.
    """
    found: list[str] = []
    seen: set[str] = set()
    for line in requirements.splitlines():
        stripped = line.lstrip()
        depth = len(stripped) - len(stripped.lstrip("*"))
        if depth == 0 or depth > MAX_QUEST_LINK_DEPTH:
            continue
        for target in _LINK.findall(stripped):
            title = target.strip()
            if title.startswith("File:") or title in seen:
                continue
            seen.add(title)
            found.append(title)
    return found


# ---------------------------------------------------------------------------
# Existing authored content
# ---------------------------------------------------------------------------


def _authored_yaml_documents(directory: Path) -> Iterable[Any]:
    """Every object in ``directory`` *outside* the generated subtree."""
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*")):
        if path.suffix not in {".yaml", ".yml"} or not path.is_file():
            continue
        if GENERATED_DIR in path.relative_to(directory).parts:
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, Mapping):
            yield document
        elif isinstance(document, list):
            yield from (entry for entry in document if isinstance(entry, Mapping))


def authored_quest_ids(content_dir: Path) -> set[str]:
    """Quest registry ids a human already declared — skipped to avoid a duplicate id."""
    return {
        str(entry["id"])
        for entry in _authored_yaml_documents(content_dir / "quests")
        if entry.get("id")
    }


def authored_quest_completions(content_dir: Path) -> set[str]:
    """Quest ids some authored candidate already claims as its ``completion``.

    Matched on the completion predicate rather than on the candidate id, because that is
    what actually collides: two candidates completing on the same fact are two entries
    that finish together, and the hand-weighted one is the one worth keeping.
    """
    claimed: set[str] = set()
    for entry in _authored_yaml_documents(content_dir / "candidates"):
        completion = entry.get("completion")
        if isinstance(completion, Mapping):
            quest = completion.get("quest")
            if isinstance(quest, str):
                claimed.add(quest)
    return claimed


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class GenerationError(Exception):
    """A refusal to write, always naming the content decision that has to be made."""


def _quest_lookup(quests: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Wiki page title *and* display name → quest id, for resolving prerequisite links."""
    lookup: dict[str, str] = {}
    for quest in quests:
        lookup[str(quest["wiki_page"])] = str(quest["id"])
        lookup.setdefault(str(quest["name"]), str(quest["id"]))
    return lookup


def _requires_tree(
    skills: Mapping[str, int], others: Mapping[str, int], quest_ids: Sequence[str]
) -> dict[str, Any] | None:
    """Assemble a §10.2 requirement tree, or ``None`` when the quest gates on nothing.

    A single requirement is emitted bare rather than wrapped in a one-element ``all_of``:
    both parse identically, and the unwrapped form is what a human writes.
    """
    clauses: list[dict[str, Any]] = []
    for skill in sorted(skills):
        clauses.append({"skill": {skill: skills[skill]}})
    for key in sorted(others):
        clauses.append({key: others[key]})
    clauses.extend({"quest": quest_id} for quest_id in quest_ids)

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"all_of": clauses}


def generate_quests(
    data: Mapping[str, Any],
    *,
    authored_ids: set[str],
    authored_completions: set[str],
    skills: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the quest registry rows and the quest candidates.

    Returns ``(registry, candidates)``. Order follows the vendored dump, which is RuneLite
    enum order — stable across runs, so ``--check`` diffs only on real change.
    """
    quests = list(data["quests"])
    lookup = _quest_lookup(quests)
    unknown_skills: set[str] = set()

    registry: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for quest in quests:
        quest_id = str(quest["id"])
        parsed_skills, others, _ = parse_skill_requirements(quest["requirements"])
        unknown_skills.update(name for name in parsed_skills if name not in skills)

        if quest_id not in authored_ids:
            registry.append({"id": quest_id, "name": str(quest["name"])})

        if quest_id in authored_completions:
            continue

        prerequisites = [
            resolved
            for title in parse_quest_links(quest["requirements"])
            if (resolved := lookup.get(title)) is not None and resolved != quest_id
        ]
        candidate: dict[str, Any] = {
            "id": f"complete_{quest_id}",
            "name": f"Complete {quest['name']}",
            "kind": "quest",
            "source": "generated",
            "advances": {},
        }
        requires = _requires_tree(parsed_skills, others, prerequisites)
        if requires is not None:
            candidate["requires"] = requires
        candidate["completion"] = {"quest": quest_id}
        candidate["grants_facts"] = {"quest": quest_id}
        candidates.append(candidate)

    if unknown_skills:
        raise GenerationError(
            "the wiki names skills this corpus does not declare: "
            + ", ".join(sorted(unknown_skills))
            + ". Declare them in content/skills/ (which also needs a sync source for the "
            "level) or add them to KNOWN_UNMODELLED_SKILLS with the reason — a silently "
            "dropped requirement makes a quest look startable when it is not"
        )
    return registry, candidates


# ---------------------------------------------------------------------------
# Achievement diaries (Step 6)
# ---------------------------------------------------------------------------

_SCP = re.compile(r"\{\{SCP\|([^|}]+)(?:\|(\d+))?[^}]*\}\}")

#: ``{{SCP|...}}`` labels that are not skills, lowercased. Diary pages abbreviate what
#: quest pages spell out in ``NON_SKILL_LABELS``, and both already have their own §10.2
#: requirement leaf — so these are translated rather than dropped.
SCP_NON_SKILL_LABELS = {"quest": "quest_points", "combat": "combat_level"}

#: A task line asking for a quest marks it with a level-less ``{{SCP|Quest}}`` and names
#: the quest in the link that follows.
_QUEST_MARKER = "{{SCP|Quest}}"


def parse_diary_requirements(wikitext: str) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """``(max level per skill, non-skill leaves, quest page titles)`` for one task table.

    **The maximum, not the sum or the mode.** A tier is complete only when every task in
    it is, so the tier's requirement is the hardest ask on each skill — that is a floor
    derived from the tasks themselves, not an estimate of difficulty.

    ``{{SCP|Quest}}`` carries no level and is not a skill; the quest it refers to is named
    by the first link on the same line, which is where the quest requirements come from.
    The *same* template with a level — ``{{SCP|Quest|32}}`` — is a quest-**points** ask,
    and ``{{SCP|Combat|85}}`` is a combat level. Diary pages abbreviate both where quest
    pages spell them out, which is why they need their own table.
    """
    skills: dict[str, int] = {}
    others: dict[str, int] = {}
    quests: list[str] = []
    for line in wikitext.splitlines():
        for label, level in _SCP.findall(line):
            if not level:
                continue
            name = label.strip().lower()
            if name in SCP_NON_SKILL_LABELS:
                key = SCP_NON_SKILL_LABELS[name]
                others[key] = max(others.get(key, 0), int(level))
            else:
                skills[name] = max(skills.get(name, 0), int(level))
        if _QUEST_MARKER in line:
            after = line.split(_QUEST_MARKER, 1)[1]
            quests.extend(
                title.strip()
                for title in _LINK.findall(after)
                if not title.strip().startswith("File:")
            )
    return skills, others, quests


def generate_diaries(
    data: Mapping[str, Any],
    *,
    quest_lookup: Mapping[str, str],
    authored_completions: set[str],
    skills: set[str],
) -> list[dict[str, Any]]:
    """One ``kind: unlock`` candidate per diary tier.

    No registry rows: §6.3 leaves the ``unlock:`` key space open with a reserved
    ``diary_`` prefix supplied by the plugin, and ``_check_references`` does not resolve
    ``unlock:`` leaves — so unlike quests there is nothing to declare.
    """
    unknown: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for diary in data["diaries"]:
        key = str(diary["key"])
        if key in authored_completions:
            continue
        tier_skills, others, quest_titles = parse_diary_requirements(diary["requirements"])
        unknown.update(name for name in tier_skills if name not in skills)
        prerequisites: list[str] = []
        for title in quest_titles:
            resolved = quest_lookup.get(title)
            if resolved is not None and resolved not in prerequisites:
                prerequisites.append(resolved)

        candidate: dict[str, Any] = {
            "id": f"complete_{key}",
            "name": str(diary["name"]),
            "kind": "unlock",
            "source": "generated",
            "advances": {},
        }
        requires = _requires_tree(tier_skills, others, prerequisites)
        if requires is not None:
            candidate["requires"] = requires
        candidate["completion"] = {"unlock": key}
        candidate["grants_facts"] = {"unlock": key}
        candidates.append(candidate)

    if unknown:
        raise GenerationError(
            "diary tasks name skills this corpus does not declare: "
            + ", ".join(sorted(unknown))
            + ". Declare them in content/skills/ or add them to KNOWN_UNMODELLED_SKILLS "
            "with the reason — an omitted requirement makes a diary tier look startable "
            "when it is not"
        )
    return candidates


# ---------------------------------------------------------------------------
# Skill training bands (Step 5)
# ---------------------------------------------------------------------------

#: Levels worth stopping at that the corpus does not itself name. Every other boundary is
#: read out of content, and these are the ones a PvP account plans around regardless —
#: the defence brackets that define account builds, and the round numbers gear and combat
#: formulas are quoted at. Authored here rather than in YAML because they are a property
#: of the *game*, not of this corpus, and a boundary is not a priority: it says where a
#: band ends, never how much the band is worth.
PVP_BREAKPOINTS = (70, 75, 80, 85, 90, 94, 99)

#: The floor every skill starts from.
MIN_LEVEL = 1
MAX_LEVEL = 99


def _skill_leaf_levels(tree: Any, out: dict[str, set[int]]) -> None:
    """Collect ``skill: {magic: 94}`` levels from a raw requirement mapping, recursively."""
    if isinstance(tree, list):
        for entry in tree:
            _skill_leaf_levels(entry, out)
        return
    if not isinstance(tree, Mapping):
        return
    for key, value in tree.items():
        if key == "skill" and isinstance(value, Mapping):
            for skill, level in value.items():
                if isinstance(level, int):
                    out.setdefault(str(skill), set()).add(level)
        else:
            _skill_leaf_levels(value, out)


def corpus_skill_levels(content_dir: Path) -> dict[str, set[int]]:
    """Every skill level the *authored* corpus names, by skill.

    Read from capabilities, authored candidates and training-method level ranges — the
    three places a level can already matter. This is what makes the bands the corpus's
    own boundaries rather than an arbitrary ladder: a band ends at 94 Magic because
    ``ice_barrage_nh`` requires 94 Magic, and if that requirement changes the bands move
    with it at the next generation.
    """
    levels: dict[str, set[int]] = {}
    for directory in ("capabilities", "candidates"):
        for entry in _authored_yaml_documents(content_dir / directory):
            _skill_leaf_levels(entry.get("requires"), levels)
            _skill_leaf_levels(entry.get("completion"), levels)
            _skill_leaf_levels(entry.get("grants_facts"), levels)
    for entry in _authored_yaml_documents(content_dir / "training_methods"):
        skill = entry.get("skill")
        level_range = entry.get("level_range")
        if isinstance(skill, str) and isinstance(level_range, Mapping):
            for bound in ("min", "max"):
                if isinstance(level_range.get(bound), int):
                    levels.setdefault(skill, set()).add(int(level_range[bound]))
        _skill_leaf_levels(entry.get("requires"), levels)
    return levels


def band_boundaries(named: Iterable[int]) -> list[int]:
    """The sorted level ladder for one skill: its own boundaries, plus the breakpoints."""
    ladder = {MIN_LEVEL, MAX_LEVEL, *PVP_BREAKPOINTS}
    ladder.update(level for level in named if MIN_LEVEL <= level <= MAX_LEVEL)
    return sorted(ladder)


def generate_skill_bands(
    levels: Mapping[str, set[int]], *, authored_targets: set[tuple[str, int]]
) -> list[dict[str, Any]]:
    """One candidate per (skill, band), for the skills the corpus references.

    **Only referenced skills get bands, and that is a scoping decision worth stating.**
    Generating a ladder for all 23 skills would add ~180 candidates for things like
    Farming and Cooking, which this corpus's capabilities never mention — every one of
    them would advance nothing, estimate against a fallback method, and dilute the list.
    A skill nothing references also has no boundaries of its own, so its bands would be
    pure invention. The corpus's own references are the honest scope signal.

    **Each band requires the previous one's level**, which is what makes exactly one band
    per skill actionable at a time: the rest are either complete (§16.2 tests completion
    before scoring, so they never rank) or blocked by the level below. That is also what
    makes the §8 estimate meaningful — a five-level band is quoted at four hours instead
    of the three hundred a bare "train to 99" would carry.
    """
    candidates: list[dict[str, Any]] = []
    for skill in sorted(levels):
        ladder = band_boundaries(levels[skill])
        for start, target in pairwise(ladder):
            if (skill, target) in authored_targets:
                continue
            candidate: dict[str, Any] = {
                "id": f"train_{skill}_{start}_to_{target}",
                # Named by target only. The band's floor is a *corpus* boundary, not where
                # the account stands: §8 estimates from the player's current level, so a
                # Magic-35 account reading "Train Magic 1 → 50" beside a 2.2 hour estimate
                # is being told something false about itself. The floor stays in the id,
                # where it keeps the chain legible without being shown.
                "name": f"Train {skill.capitalize()} to {target}",
                "kind": "skill_training",
                "source": "generated",
                "advances": {},
            }
            if start > MIN_LEVEL:
                candidate["requires"] = {"skill": {skill: start}}
            candidate["completion"] = {"skill": {skill: target}}
            candidate["grants_facts"] = {"skill": {skill: target}}
            candidates.append(candidate)
    return candidates


def authored_unlock_completions(content_dir: Path) -> set[str]:
    """Unlock keys an authored candidate already completes on — skipped, as for quests."""
    claimed: set[str] = set()
    for entry in _authored_yaml_documents(content_dir / "candidates"):
        completion = entry.get("completion")
        if isinstance(completion, Mapping) and isinstance(completion.get("unlock"), str):
            claimed.add(str(completion["unlock"]))
    return claimed


def authored_skill_targets(content_dir: Path) -> set[tuple[str, int]]:
    """``(skill, target level)`` pairs an authored candidate already completes on.

    Keyed on the completion target rather than the candidate id for the reason
    :func:`authored_quest_completions` gives: ``train_magic_87_to_94`` and a generated
    ``train_magic_82_to_94`` are different ids that finish on the same fact, and it is the
    hand-weighted one that must survive.
    """
    targets: set[tuple[str, int]] = set()
    for entry in _authored_yaml_documents(content_dir / "candidates"):
        found: dict[str, set[int]] = {}
        _skill_leaf_levels(entry.get("completion"), found)
        for skill, skill_levels in found.items():
            targets.update((skill, level) for level in skill_levels)
    return targets


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

_REGISTRY_HEADER = """\
# Generated by tools/generate_candidates.py — do not edit.
#
# One row per quest RuneLite reports, so that `quest:` leaves anywhere in the corpus
# resolve (§10.7). Identity is slug(Quest.name()), which is what the plugin transmits.
#
# `quest_points` is omitted rather than guessed: the field defaults to 0, no engine reads
# it (a `quest_points:` leaf reads the *player's* total from PlayerState), and the wiki
# dump this is generated from does not carry it.
"""

_CANDIDATE_HEADER = """\
# Generated by tools/generate_candidates.py — do not edit.
#
# `advances: {}` on every entry is deliberate and is not a TODO marker in disguise: how
# much a quest advances a capability is an editorial judgment (§10.6), and no generator
# can derive it. These rank by `leverage` — what their completion unblocks — and sort
# below anything hand-weighted until a human says otherwise.
#
# To weight one: move it into an authored file under content/candidates/, set
# `source: authored`, and fill in `advances`. This file is regenerated wholesale, and a
# quest already claimed by an authored candidate's `completion` is skipped here.
"""


_BAND_HEADER = """\
# Generated by tools/generate_candidates.py — do not edit.
#
# `kind: skill_training`, decomposed into bands so that §8's estimate is about the next
# few hours rather than the next few hundred. Boundaries are the corpus's own: every level
# a capability, authored candidate or training method names, plus the standard PvP
# breakpoints. Change a capability's `skill:` requirement and the bands move with it.
#
# Each band requires the level below it, so exactly one band per skill is ever actionable:
# the ones beneath are already complete (and §16.2 drops complete candidates before
# scoring), the ones above are blocked.
#
# `advances: {}` for the reason given in quests.yaml — which capability a level advances,
# and by how much, is the editorial judgment §10.6 reserves for a human.
"""


_DIARY_HEADER = """# Generated by tools/generate_candidates.py — do not edit.
#
# One `kind: unlock` candidate per achievement-diary tier. `completion` is the plugin's own
# `diary_<region>_<tier>` key, so these complete themselves off a sync with no new payload
# fields — the facts have been arriving since step 12b.
#
# `requires` is the maximum level each skill is asked for across the tier's tasks, plus the
# quests its tasks name. That is a floor rather than an estimate: a tier is complete only
# when every task in it is.
#
# No registry file accompanies this one. §6.3 keeps the `unlock:` key space open with a
# reserved `diary_` prefix supplied by the plugin, and `_check_references` does not resolve
# `unlock:` leaves — so unlike quests there is nothing to declare.
"""


def dump_yaml(rows: Sequence[Mapping[str, Any]], header: str) -> str:
    """Deterministic YAML: insertion-ordered keys, block style, no aliases."""
    body = yaml.safe_dump(
        [dict(row) for row in rows],
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return f"{header}\n{body}"


def _outputs(content_dir: Path, data_dir: Path) -> dict[Path, str]:
    """Every file this tool owns, mapped to the content it should have."""
    data = json.loads((data_dir / "osrs_quests.json").read_text(encoding="utf-8"))
    skills = {
        str(entry["id"]) for entry in _authored_yaml_documents(content_dir / "skills") if entry
    }
    registry, candidates = generate_quests(
        data,
        authored_ids=authored_quest_ids(content_dir),
        authored_completions=authored_quest_completions(content_dir),
        skills=skills,
    )
    diaries = generate_diaries(
        json.loads((data_dir / "osrs_diaries.json").read_text(encoding="utf-8")),
        quest_lookup=_quest_lookup(data["quests"]),
        authored_completions=authored_unlock_completions(content_dir),
        skills=skills,
    )
    bands = generate_skill_bands(
        corpus_skill_levels(content_dir), authored_targets=authored_skill_targets(content_dir)
    )
    return {
        content_dir / "quests" / GENERATED_DIR / "quests.yaml": dump_yaml(
            registry, _REGISTRY_HEADER
        ),
        content_dir / "candidates" / GENERATED_DIR / "quests.yaml": dump_yaml(
            candidates, _CANDIDATE_HEADER
        ),
        content_dir / "candidates" / GENERATED_DIR / "skill_bands.yaml": dump_yaml(
            bands, _BAND_HEADER
        ),
        content_dir / "candidates" / GENERATED_DIR / "diaries.yaml": dump_yaml(
            diaries, _DIARY_HEADER
        ),
    }


def _write(outputs: Mapping[Path, str]) -> None:
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def _check(outputs: Mapping[Path, str]) -> int:
    """Fail if any owned file differs from what generation produces right now.

    This is the drift guard: it catches a hand-edit to a generated file (which the next
    run would silently discard) and a vendored-data change nobody regenerated for.
    """
    drifted = [
        path
        for path, text in outputs.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]
    if drifted:
        print("generated content is out of date:", file=sys.stderr)
        for path in drifted:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        print("run: python tools/generate_candidates.py quests", file=sys.stderr)
        return 1
    print(f"generated content is up to date — {len(outputs)} files")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tools/generate_candidates.py",
        description="Generate content YAML from vendored game data.",
    )
    parser.add_argument(
        "mode", nargs="?", choices=["quests", "skills", "diaries", "all"], help="what to generate"
    )
    parser.add_argument("--check", action="store_true", help="fail on drift instead of writing")
    parser.add_argument("--content-dir", type=Path, default=DEFAULT_CONTENT_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    if args.mode is None and not args.check:
        parser.error("give a mode to generate, or --check to verify")

    try:
        outputs = _outputs(args.content_dir, args.data_dir)
    except GenerationError as exc:
        print(f"generation refused: {exc}", file=sys.stderr)
        return 1

    if args.check:
        return _check(outputs)
    _write(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
