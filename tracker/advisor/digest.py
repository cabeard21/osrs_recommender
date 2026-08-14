"""The whole-account summary §22.2 pins to every conversation.

Where §21.2 selects a slice by relevance, this cannot: the question is not known until it is
asked, so there is no candidate whose requirement trees can do the selecting. The digest is the
other answer — everything small enough to carry in full, carried in full; everything else
bounded, and **every bounded section says so in the rendered text, naming the tool that reaches
the rest**. A truncated list that does not announce its truncation reads as a complete one, and
a model that believes it has seen every candidate will not go looking for the one that matters.

Two rules govern every line below, both carried from :mod:`tracker.guidance.context`:

**Everything is ordered.** §22.3 hashes this rendering to key a conversation's cached prefix. A
set iteration leaking into the output would produce a hash that moves when nothing has, costing
a re-cache on a turn that earned one.

**Three-valued facts stay three-valued.** An unobserved ``account_type`` renders *unknown* and
never *main*; unobserved ``members`` renders *unknown* and never *no*; unobserved liquid GP
renders *nobody has looked* and never *0*; a skill with no observation renders *never observed*
and never *level 1*. The stake is higher here than in §21, because a conversation invites the
question directly — *"can I afford this?"* answered from an assumed zero is a worse answer than
*"I do not know what you have."*
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from tracker.advisor.snapshot import AdvisorSnapshot, RankedTask
from tracker.content.loader import Content
from tracker.content.requirements import QuestLeaf, Requirement, UnlockLeaf, iter_leaves
from tracker.domain.types import (
    LeafRef,
    PlayerState,
    QuestStatus,
    RoadmapSelection,
)

#: What an unobserved three-valued fact renders as. One constant so the *unknown* in
#: ``account_type`` and the one in ``members`` cannot drift apart, exactly as
#: :data:`tracker.guidance.context.UNKNOWN` does for §21.
UNKNOWN: Final = "unknown"

#: Ranked entries carried in full. Ten is roughly what a person considers before the list stops
#: being a decision and starts being a catalogue; the rest are one ``search_candidates`` away.
MAX_RANKED: Final = 10

#: Blocked entries carried. Fewer than the actionable ones on purpose — a blocked task is
#: context for *why not yet*, and the tail of a blocked list is noise.
MAX_BLOCKED: Final = 5

#: Named incomplete quests. The corpus holds 200-odd; these are the ones some capability or
#: highly-ranked candidate actually gates on.
MAX_QUESTS: Final = 40

#: How far down the ranking to look when deciding which quests are worth naming.
QUEST_GATE_DEPTH: Final = 30

#: Blockers rendered per capability before the count takes over.
MAX_CAPABILITY_BLOCKERS: Final = 3

#: Names rendered in a ranked entry's consequence line before the count takes over. The ranked
#: block carries ten entries on every turn, so this is a line-length budget as much as a
#: readability one.
MAX_CONSEQUENCE_NAMES: Final = 3


@dataclass(frozen=True, slots=True)
class AccountDigest:
    """The rendered digest, section by section, before it is joined.

    Sections are kept apart rather than pre-joined so that a test can assert about one of them
    without matching against the whole document, and so an empty section can be dropped rather
    than emitted as a bare heading — which reads as *"there are none"* when the truth is often
    *"this does not apply"*.
    """

    account: str
    skills: str
    capabilities: str
    roadmaps: str
    recommended: str
    blocked: str
    quests: str
    unlocks: str
    practice: str


def build_digest(snapshot: AdvisorSnapshot) -> AccountDigest:
    """Render each section of §22.2's digest from one frozen snapshot."""
    return AccountDigest(
        account=_account_block(snapshot),
        skills=_skills_block(snapshot),
        capabilities=_capabilities_block(snapshot),
        roadmaps=_roadmaps_block(snapshot.roadmaps, snapshot.content),
        recommended=_recommended_block(snapshot),
        blocked=_blocked_block(snapshot),
        quests=_quests_block(snapshot),
        unlocks=_unlocks_block(snapshot),
        practice=_practice_block(snapshot),
    )


def render_digest(digest: AccountDigest) -> str:
    """Join the non-empty sections into the markdown the prompt carries.

    Markdown rather than JSON for :func:`tracker.guidance.prompt.render_context`'s reason: the
    sections are read once, in order, by a reader that handles prose better than braces.
    """
    blocks = (
        digest.account,
        digest.skills,
        digest.capabilities,
        digest.roadmaps,
        digest.recommended,
        digest.blocked,
        digest.quests,
        digest.unlocks,
        digest.practice,
    )
    return "\n\n".join(block for block in blocks if block)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _account_block(snapshot: AdvisorSnapshot) -> str:
    state = snapshot.state
    lines = [
        f"- Account type: {_account_type(state)}",
        f"- Members: {_members_word(state.members)}",
        f"- Combat level: {_or_unknown(state.combat_level)}",
        f"- Quest points: {_or_unknown(state.quest_points)}",
        f"- Coins on hand: {_coins(state.liquid_gp)}",
        f"- Account last observed: {snapshot.observed_age.value}",
    ]
    return "# Account\n\n" + "\n".join(lines)


def _skills_block(snapshot: AdvisorSnapshot) -> str:
    """All twenty-three, always.

    The full table rather than a slice because a question can turn on any of them and there is
    no candidate to narrow by; twenty-three lines is a cheap way to never need a tool call for
    *"what is my Agility?"*. Iterated over the **corpus**, not over observations, so a skill
    nobody has ever synced still appears — as *never observed*, which is the fact that matters.
    """
    skills = snapshot.content.skills
    if not skills:
        return ""
    lines = []
    for skill_id in sorted(skills):
        declared = skills[skill_id]
        observed = snapshot.state.skills.get(skill_id)
        if observed is None:
            current = "never observed"
        elif observed.xp is None:
            current = f"level {observed.level} (unranked — no XP recorded)"
        else:
            current = f"level {observed.level}"
        lines.append(f"- {declared.name}: {current}")
    return "# Skills\n\n" + "\n".join(lines)


def _capabilities_block(snapshot: AdvisorSnapshot) -> str:
    if not snapshot.capabilities:
        return ""
    blocks = []
    for view in snapshot.capabilities:
        declared = snapshot.content.capabilities.get(view.capability_id)
        name = declared.name if declared is not None else view.capability_id
        readiness = (
            view.readiness_confidence.name.lower()
            if view.readiness_confidence is not None
            else UNKNOWN
        )
        lines = [
            f"## {name}",
            f"- Status: {view.status.value}",
            f"- Requirements met: {view.unlock_fraction:.0%}",
            f"- Readiness confidence: {readiness}",
        ]
        if view.recommended_now:
            lines.append("- Recommended to use now: yes")
        elif view.recommended_now_reason:
            lines.append(f"- Recommended to use now: no — {view.recommended_now_reason}")
        lines += _leaf_lines("Missing", view.blockers)
        lines += _leaf_lines("Never observed", view.unknowns)
        lines += [f"- Warning: {warning}" for warning in view.warnings]
        blocks.append("\n".join(lines))
    return (
        "# Capabilities\n\nEvery capability the corpus declares. Use `get_capability_detail` "
        "for the full requirement tree of any one of them.\n\n" + "\n\n".join(blocks)
    )


def _leaf_lines(label: str, leaves: tuple[LeafRef, ...]) -> list[str]:
    if not leaves:
        return []
    shown = leaves[:MAX_CAPABILITY_BLOCKERS]
    line = f"- {label}: " + ", ".join(leaf.description for leaf in shown)
    remaining = len(leaves) - len(shown)
    if remaining > 0:
        line += f", and {remaining} more"
    return [line]


def _roadmaps_block(roadmaps: RoadmapSelection, content: Content) -> str:
    if not roadmaps.weights:
        return ""
    lines = []
    for capability_id, weight in sorted(roadmaps.weights.items()):
        declared = content.capabilities.get(capability_id)
        name = declared.name if declared is not None else capability_id
        lines.append(f"- {name}: {weight:.0%}")
    return (
        "# Active roadmap weighting\n\nThe blended capability weights the engine ranked "
        "against (§9.3).\n\n" + "\n".join(lines)
    )


def _recommended_block(snapshot: AdvisorSnapshot) -> str:
    if not snapshot.ranked:
        return (
            "# What the tracker recommends\n\nThere is no recommendation run for this account "
            "yet — nothing has been synced, or the last sync produced no actionable entry."
        )
    shown = snapshot.ranked[:MAX_RANKED]
    blocks = [_task_block(task) for task in shown]
    remaining = len(snapshot.ranked) - len(shown)
    footer = (
        f"\n\n{remaining} further ranked entries are not listed. "
        "Use `search_candidates` to reach them and `get_candidate_detail` for any one."
        if remaining > 0
        else "\n\nUse `get_candidate_detail` for the requirements or bands of any of these."
    )
    return (
        "# What the tracker recommends\n\nRanked by the engine. The reason on each line is the "
        "engine's own, computed from scoring headroom — not a summary written for you.\n\n"
        + "\n\n".join(blocks)
        + footer
    )


def _blocked_block(snapshot: AdvisorSnapshot) -> str:
    if not snapshot.blocked:
        return ""
    shown = snapshot.blocked[:MAX_BLOCKED]
    blocks = []
    for task in shown:
        lines = [f"## {task.name} ({task.kind.replace('_', ' ')})"]
        if task.blockers:
            lines.append(
                "- Not yet met: " + ", ".join(blocker.description for blocker in task.blockers)
            )
        blocks.append("\n".join(lines))
    remaining = len(snapshot.blocked) - len(shown)
    footer = f"\n\n{remaining} further blocked entries are not listed." if remaining > 0 else ""
    return "# Blocked, and what is blocking it\n\n" + "\n\n".join(blocks) + footer


def _task_block(task: RankedTask) -> str:
    lines = [f"## {task.rank}. {task.name} ({task.kind.replace('_', ' ')})"]
    estimate = _estimate_line(task)
    if estimate:
        lines.append(f"- Tracker's estimate: {estimate}")
    if task.reason:
        lines.append(f"- Why the tracker ranked it: {task.reason}")
    consequence = _consequence_line(task)
    if consequence:
        lines.append(f"- What it would do: {consequence}")
    return "\n".join(lines)


def _consequence_line(task: RankedTask) -> str:
    """§9.10's consequences for one ranked entry, in **one** line.

    :func:`tracker.advisor.dispatch._consequence_lines` renders the same object across four
    lines with figures attached, and that is the right shape there — it answers a question
    somebody asked about one candidate. Here the same detail is multiplied by ten entries on
    every turn, so this is the short form: what it opens, what it finishes, and how many things
    it shortens.

    Two omissions are deliberate and both are about §22.3's hash. ``remaining_after`` /
    ``remaining_before`` move whenever any requirement is observed, so only the *completed*
    gates are named — a gate part-way cleared says nothing here that the blocked section does
    not. ``speeds_up`` renders as a count rather than ``hours_before → hours_after`` because
    those floats move on every reprice, which would re-cache the prefix for a change the player
    did not make.

    An empty result is a legitimate answer and renders as no line at all: §9.5 forbids authored
    justification, and an entry that ranked on cheapness alone genuinely has nothing to say.
    """
    consequences = task.consequences
    parts = []
    if consequences.unblocks_capabilities:
        names = _bounded_names(item.name for item in consequences.unblocks_capabilities)
        parts.append(f"unlocks {names}")
    finishes = [gate.name for gate in consequences.gate_progress if gate.unblocks]
    if finishes:
        parts.append(f"clears the last requirement of {_bounded_names(finishes)}")
    if consequences.goal_progress:
        goals = _bounded_names(goal.name for goal in consequences.goal_progress)
        parts.append(f"moves toward {goals}")
    if consequences.speeds_up:
        count = len(consequences.speeds_up)
        parts.append(f"shortens {count} other task{'' if count == 1 else 's'}")
    return "; ".join(parts)


def _bounded_names(names: Iterable[str]) -> str:
    """A comma-joined name list, capped, announcing what it left out."""
    listed = list(names)
    shown = listed[:MAX_CONSEQUENCE_NAMES]
    joined = ", ".join(shown)
    remaining = len(listed) - len(shown)
    return f"{joined} and {remaining} more" if remaining > 0 else joined


def _estimate_line(task: RankedTask) -> str:
    parts = []
    if task.hours is not None:
        parts.append(f"about {task.hours:.1f} hours")
    if task.gp is not None:
        parts.append(f"about {task.gp:,} gp")
    if not parts:
        return ""
    return f"{' and '.join(parts)} (confidence: {task.confidence})"


def _quests_block(snapshot: AdvisorSnapshot) -> str:
    """Counts for everything, names for what is actually gated on.

    Two hundred quest names would be the single largest thing in the prompt and would earn it
    on roughly one question in fifty. The counts give the shape; the named subset covers the
    quests some capability or highly-ranked candidate is waiting on; ``get_quest_status``
    covers the rest on demand.
    """
    state = snapshot.state
    content = snapshot.content
    if not content.quests:
        return ""

    counts = dict.fromkeys(QuestStatus, 0)
    unobserved = 0
    for quest_id in content.quests:
        status = state.quests.get(quest_id)
        if status is None:
            unobserved += 1
        else:
            counts[status] += 1

    lines = [
        f"- {status.value}: {count}"
        for status, count in sorted(counts.items(), key=lambda item: item[0].value)
        if count
    ]
    if unobserved:
        lines.append(f"- never observed: {unobserved}")

    incomplete = sorted(
        quest_id
        for quest_id in _gated_quest_ids(snapshot)
        if state.quests.get(quest_id) is not QuestStatus.COMPLETE
    )
    named = []
    for quest_id in incomplete[:MAX_QUESTS]:
        declared = content.quests.get(quest_id)
        name = declared.name if declared is not None else quest_id
        status = state.quests.get(quest_id)
        named.append(f"- {name}: {status.value if status is not None else UNKNOWN}")

    body = "# Quests\n\nCounts across the whole corpus:\n\n" + "\n".join(lines)
    if named:
        remaining = len(incomplete) - len(named)
        suffix = f"\n- …and {remaining} more" if remaining > 0 else ""
        body += (
            "\n\nIncomplete quests that something is waiting on:\n\n" + "\n".join(named) + suffix
        )
    body += "\n\nUse `get_quest_status` for any quest not named here."
    return body


def _gated_quest_ids(snapshot: AdvisorSnapshot) -> set[str]:
    """Quests named by a capability tree or by a highly-ranked candidate's trees.

    Depth-limited rather than corpus-wide: every generated skill band has a completion tree,
    and walking all 365 would name most of the quest list, which is the outcome this section
    exists to avoid.
    """
    ids: set[str] = set()
    for capability in snapshot.content.capabilities.values():
        ids |= _quest_ids(capability.requires)
    for task in snapshot.ranked[:QUEST_GATE_DEPTH]:
        candidate = snapshot.content.candidates.get(task.candidate_id)
        if candidate is not None:
            ids |= _quest_ids(candidate.requires)
            ids |= _quest_ids(candidate.completion)
        ids |= {blocker.key for blocker in task.blockers if blocker.leaf_type == "quest"}
    return ids


def _quest_ids(tree: Requirement | None) -> set[str]:
    if tree is None:
        return set()
    return {leaf.quest_id for leaf in iter_leaves(tree) if isinstance(leaf, QuestLeaf)}


def _unlocks_block(snapshot: AdvisorSnapshot) -> str:
    """Only the unlock keys the corpus actually references.

    An unlock key the corpus never names cannot gate anything, so reporting its state would be
    noise the model has to read past on every turn.
    """
    keys = _referenced_unlock_keys(snapshot.content)
    if not keys:
        return ""
    lines = []
    for key in sorted(keys):
        observed = snapshot.state.unlocks.get(key)
        lines.append(f"- {key}: {observed.value if observed is not None else UNKNOWN}")
    return (
        "# Unlocks\n\n`available` means obtainable but **not** held — treat it as not "
        "unlocked (§9.1).\n\n" + "\n".join(lines)
    )


def _referenced_unlock_keys(content: Content) -> set[str]:
    keys: set[str] = set()
    for capability in content.capabilities.values():
        keys |= _unlock_keys(capability.requires)
    for candidate in content.candidates.values():
        keys |= _unlock_keys(candidate.requires)
        keys |= _unlock_keys(candidate.completion)
        keys |= _unlock_keys(candidate.grants_facts)
    for method in content.training_methods.values():
        keys |= _unlock_keys(method.requires)
    return keys


def _unlock_keys(tree: Requirement | None) -> set[str]:
    if tree is None:
        return set()
    return {leaf.key for leaf in iter_leaves(tree) if isinstance(leaf, UnlockLeaf)}


def _practice_block(snapshot: AdvisorSnapshot) -> str:
    if not snapshot.stale_practice:
        return ""
    lines = [f"- {name}: {band}" for name, band in snapshot.stale_practice]
    return (
        "# Practice freshness\n\nExecution milestones whose evidence has aged (§6.9). This "
        "lowers readiness confidence; it never revokes a capability (D1, D8). A milestone "
        "absent from this list has either been practiced recently or has no practice evidence "
        "at all — the two are not distinguished here, and neither is a failure.\n\n"
        + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# Small renderers
# ---------------------------------------------------------------------------


def _account_type(state: PlayerState) -> str:
    """§4.5's rule at the prompt boundary: nobody asked is not *main*.

    The gloss is not decoration. A model told only *unknown* will reach for the most common
    case, and the most common case is the one where buying things is allowed — which is
    precisely the advice that is wrong for an ironman.
    """
    if state.account_type is None:
        return f"{UNKNOWN} — nobody has reported it; do not assume main, and do not assume ironman"
    return state.account_type.value


def _members_word(members: bool | None) -> str:
    if members is None:
        return f"{UNKNOWN} — nobody has reported it; this is not the same as free-to-play"
    return "yes" if members else "no"


def _or_unknown(value: int | None) -> str:
    return UNKNOWN if value is None else str(value)


def _coins(liquid_gp: int | None) -> str:
    """§6.5's three states, kept three, with the same words :mod:`tracker.guidance.prompt` uses."""
    if liquid_gp is None:
        return (
            f"{UNKNOWN} — no container has been scanned, so do not assume they have coins "
            "or that they have none"
        )
    return f"{liquid_gp:,} gp (observed)"
