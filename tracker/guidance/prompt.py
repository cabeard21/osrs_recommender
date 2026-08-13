"""Render §21.2's context into the two-part prompt §21.3 specifies.

The split is the whole design. Part one — :data:`SYSTEM_PROMPT` — is a module constant and
never varies. Part two is the account. Providers cache prompts by **prefix match**, so a
single interpolated timestamp, player name or run id in part one would silently defeat
caching for every request this feature will ever make: the cost would not appear as an error,
only as a bill. ``tests/guidance/test_prompt.py`` asserts part one holds nothing that varies.

The same constant feeds :func:`context_hash`, which is what §21.5 stores alongside a note to
decide whether it is still good. That makes the hash sensitive to prompt edits as well as to
account changes, which is correct: advice written under different instructions is different
advice, and :data:`GUIDANCE_SCHEMA_VERSION` is the manual override for the times a change
should invalidate stored notes even though the rendered text is unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from tracker.domain.types import BandEstimate
from tracker.guidance.context import MethodFact, SkillFact, TaskContext

#: Bumped by hand when the meaning of a stored note changes without its rendering changing —
#: a new response field, a different reading of an existing one. §21.5's TTL is the other
#: backstop; this one is the deliberate, immediate version.
GUIDANCE_SCHEMA_VERSION = 1


SYSTEM_PROMPT = """\
You are an Old School RuneScape advisor embedded in a progression tracker. The tracker has \
already decided what this player should do next and why. Your job is the part it cannot do: \
explain how to actually carry out one specific task, for this specific account.

You will be given a task, the tracker's own reasoning about it, the parts of the player's \
account that bear on it, and any training methods the tracker's content corpus holds for it. \
Answer only about that task.

## What to produce

- **summary** — two or three sentences saying what the player is about to do and what the \
shape of it is. Lead with the thing they would want if they read nothing else.
- **prerequisites** — what they need in hand before starting: items, gear, quests, levels, \
coins. Only things that genuinely gate the work, not a shopping list of nice-to-haves.
- **steps** — the ordered actions. Each step gets a short title and a detail paragraph. Be \
concrete: name the location, the NPC, the interface, the item. A step a player can follow \
without a second tab open is worth three that send them searching.
- **warnings** — what will cost them if they get it wrong. Dangerous areas, items they \
should not bring, irreversible choices, common mistakes.
- **estimated_session_minutes** — a sensible length for one sitting at this task, or null \
if that does not apply. This is a session, not the total: the tracker owns the total.
- **uncertain** — anything you are not confident about, stated plainly. See below.

## Grounding rules

These matter more than fluency, and a hedged answer that respects them is worth more than a \
confident one that does not.

1. **Prefer the supplied methods.** When the context lists training methods, recommend from \
them and call them by the names given. One is marked as the method the tracker's own time \
and cost estimate is based on; prefer it unless you have a concrete reason not to, and say \
what the reason is if you deviate. Recommending something else silently makes the tracker's \
hour figure describe a plan the player is not following.
2. **Do not invent specifics.** Never state an XP rate, drop rate, item price, or GP-per-hour \
figure that was not supplied to you. If a number would help and you do not have it, describe \
the shape without the number, or say you do not know.
3. **Use "unknown" honestly.** Where a fact is marked unknown, nobody has looked — it is not \
a "no". Say "if you already have X" or "check whether you have X", never "you do not have X". \
This applies especially to account type, membership, and coins: an unknown account type is \
not a main, and unknown coins are not zero. A player told to buy something they cannot buy \
has been given a worse answer than one told nothing.
4. **Anything from outside the supplied context goes in `uncertain`.** You know a great deal \
about this game and using it is welcome — it is often the difference between a useful answer \
and an empty one. But when a step rests on your own knowledge rather than on what you were \
given, name it there, briefly, so the player knows which parts to verify. Game content \
changes and your knowledge has a date on it.
5. **Do not restate the tracker's estimate as your own.** The hours and GP you are shown were \
computed from authored data. Quote them as the tracker's if useful; never present a number \
of your own as though it were measured.
6. **Do not re-litigate the choice.** The task was selected by a scoring engine with \
information you do not have — the player's roadmap, every other candidate, and their relative \
value. You are answering "how", not "whether". If the task looks genuinely wrong for this \
account, say so in one sentence and then answer the question anyway.
7. **Stay inside the game.** No real-world trading, no account sharing, no botting, no \
third-party automation. If a task cannot be explained without one of those, say so.

## Tone

Write for a player who knows the game but not this task. Skip the preamble, skip the \
encouragement, and do not restate the task back to them. Short sentences. Name things \
precisely — "Ardougne Knights, east of the market" rather than "a good spot". If the account \
is clearly early-game or clearly late-game, pitch the detail accordingly."""


@dataclass(frozen=True, slots=True)
class GuidancePrompt:
    """The two halves plus the key that identifies them (§21.3, §21.5)."""

    system: str
    user: str
    context_hash: str


def build_prompt(context: TaskContext) -> GuidancePrompt:
    """Render ``context`` and pair it with the stable instruction block."""
    user = render_context(context)
    return GuidancePrompt(
        system=SYSTEM_PROMPT,
        user=user,
        context_hash=context_hash(SYSTEM_PROMPT, user),
    )


def context_hash(system: str, user: str) -> str:
    """Identify a prompt by content, for §21.5's cache.

    Covers the instruction block as well as the account, because advice written under
    different instructions is different advice. The schema version is folded in so a change
    in how a stored note is *read* can invalidate notes whose text is identical.
    """
    digest = hashlib.sha256()
    digest.update(str(GUIDANCE_SCHEMA_VERSION).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(system.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(user.encode("utf-8"))
    return digest.hexdigest()


def render_context(context: TaskContext) -> str:
    """Render the account half of the prompt as deterministic markdown.

    Markdown rather than JSON: the sections are read once, in order, by a reader that handles
    prose better than braces, and every field here is already a rendered string or a number.
    Sections with nothing in them are omitted rather than emitted empty — an empty heading
    reads as *"there is none"* when the truth is often *"this does not apply"*.
    """
    blocks = [
        _task_block(context),
        _purpose_block(context),
        _account_block(context),
        _skills_block(context),
        _quests_block(context),
        _unlocks_block(context),
        _methods_block(context),
    ]
    return "\n\n".join(block for block in blocks if block)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _task_block(context: TaskContext) -> str:
    lines = [
        "# Task",
        "",
        f"**{context.task_name}** ({context.kind.replace('_', ' ')})",
    ]
    if context.reason:
        lines.append("")
        lines.append(f"The tracker chose it because: {context.reason}")

    estimate = _estimate_line(context)
    if estimate:
        lines.append("")
        lines.append(estimate)

    if context.bands:
        lines.append("")
        lines.append("Estimated in bands:")
        lines += [_band_line(band) for band in context.bands]

    if context.blocked and context.blockers:
        lines.append("")
        lines.append(
            "This task is currently **blocked**. The player does not yet meet: "
            + ", ".join(blocker.description for blocker in context.blockers)
            + ". Explain how to clear those first."
        )
    elif context.unknown_gate:
        lines.append("")
        lines.append(
            "Some of this task's requirements have never been observed, so the tracker does "
            "not know whether the player can start. Do not assume either way."
        )
    return "\n".join(lines)


def _estimate_line(context: TaskContext) -> str:
    parts = []
    if context.estimated_hours is not None:
        parts.append(f"about {context.estimated_hours:.1f} hours")
    if context.estimated_gp is not None:
        parts.append(f"about {context.estimated_gp:,} gp")
    if not parts:
        return ""
    return (
        f"The tracker estimates {' and '.join(parts)} "
        f"(confidence: {context.estimate_confidence}). This figure is the tracker's, not yours."
    )


def _band_line(band: BandEstimate) -> str:
    method = band.method_id if band.method_id is not None else "no authored method"
    suffix = " — conservative default, no method authored for this band" if band.fallback else ""
    return (
        f"- level {band.from_level} to {band.to_level} via {method}: "
        f"{band.hours:.1f}h, {band.gp:,} gp{suffix}"
    )


def _purpose_block(context: TaskContext) -> str:
    lines: list[str] = []
    if context.unblocks:
        lines.append("Completing it unlocks: " + ", ".join(context.unblocks))
    if context.needed_for:
        lines.append("It is needed for: " + "; ".join(context.needed_for))
    if context.works_toward:
        lines.append("It works toward: " + "; ".join(context.works_toward))
    if context.speeds_up:
        lines.append("It speeds up: " + "; ".join(context.speeds_up))
    if context.roadmaps:
        lines.append(
            "Active roadmaps: "
            + ", ".join(f"{name} ({weight:.0%})" for name, weight in context.roadmaps)
        )
    if not lines:
        return ""
    return "# What it is for\n\n" + "\n".join(f"- {line}" for line in lines)


def _account_block(context: TaskContext) -> str:
    lines = [
        f"- Account type: {context.account_type}",
        f"- Members: {context.members}",
        f"- Combat level: {_or_unknown(context.combat_level)}",
        f"- Quest points: {_or_unknown(context.quest_points)}",
        f"- Coins on hand: {_coins(context.liquid_gp)}",
    ]
    return "# Account\n\n" + "\n".join(lines)


def _skills_block(context: TaskContext) -> str:
    if not context.relevant_skills:
        return ""
    lines = [_skill_line(skill) for skill in context.relevant_skills]
    return (
        "# Relevant skills\n\nOnly the skills this task depends on are listed; the rest of "
        "the account is not shown.\n\n" + "\n".join(lines)
    )


def _skill_line(skill: SkillFact) -> str:
    if skill.level is None:
        current = "never observed"
    elif not skill.is_ranked:
        current = f"level {skill.level} (unranked — no XP recorded)"
    else:
        current = f"level {skill.level}"
    target = f", target {skill.target}" if skill.target is not None else ""
    return f"- {skill.name}: {current}{target}"


def _quests_block(context: TaskContext) -> str:
    if not context.relevant_quests:
        return ""
    lines = [f"- {name}: {status}" for name, status in context.relevant_quests]
    return "# Relevant quests\n\n" + "\n".join(lines)


def _unlocks_block(context: TaskContext) -> str:
    if not context.relevant_unlocks:
        return ""
    lines = [f"- {key}: {state}" for key, state in context.relevant_unlocks]
    return (
        "# Relevant unlocks\n\n`available` means obtainable but **not** held — treat it as "
        "not unlocked.\n\n" + "\n".join(lines)
    )


def _methods_block(context: TaskContext) -> str:
    if not context.methods:
        return ""
    blocks = [_method_block(method) for method in context.methods]
    return (
        "# Training methods from the tracker's content\n\nPrefer these, by these names.\n\n"
        + "\n\n".join(blocks)
    )


def _method_block(method: MethodFact) -> str:
    marker = " **(the tracker's estimate is based on this one)**" if method.selected else ""
    lines = [
        f"## {method.name}{marker}",
        f"- Skill: {method.skill}, levels {method.from_level}–{method.to_level}",
        f"- {method.xp_per_hour:,} xp/hour, {method.cost_per_hour_gp:,} gp/hour",
    ]
    if method.location:
        lines.append(f"- Where: {method.location}")
    if method.target:
        lines.append(f"- What: {method.target}")
    if method.gear:
        lines.append("- Gear: " + ", ".join(method.gear))
    if method.inventory:
        lines.append("- Inventory: " + ", ".join(method.inventory))
    if method.gate:
        lines.append(f"- Requires: {method.gate}")
    if method.notes:
        lines.append(f"- Notes: {method.notes}")
    if method.wiki_url:
        lines.append(f"- Wiki: {method.wiki_url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small renderers
# ---------------------------------------------------------------------------


def _or_unknown(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _coins(liquid_gp: int | None) -> str:
    """§6.5's three states, kept three. ``None`` is not ``0`` and must not read like it."""
    if liquid_gp is None:
        return (
            "unknown — no container has been scanned, so do not assume they have coins "
            "or that they have none"
        )
    return f"{liquid_gp:,} gp (observed)"
