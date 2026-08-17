"""§22.4's tool execution: a pure function of a frozen snapshot and one call.

**This is where D15 stops being a promise.** :func:`execute_tool` takes an
:class:`~tracker.advisor.snapshot.AdvisorSnapshot` and a
:class:`~tracker.integrations.llm.types.ToolCall`, and it can reach nothing else — there is no
session in scope to write through, no client to fetch with, and no engine entry point to invoke
with model-chosen arguments. The rule is enforced by what the function is handed rather than by
what its author remembered.

Two conventions run throughout:

**Bad input returns an error result, never an exception.** An unknown id, a missing required
argument, a wrong type — the model can see an error result and correct itself on the next
iteration, and raising would convert a recoverable mistake into a failed turn (§22.4).

**Every leaf renders with its current three-valued state**, and *unknown* is a first-class
answer meaning nobody observed it. A tool that reported an unobserved quest as *not started*
would hand the model a confident falsehood, which is the failure §22.2 spends its whole design
avoiding — reintroduced one layer out.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from tracker.advisor.snapshot import AdvisorSnapshot, PriceFact, RankedTask
from tracker.advisor.tools import (
    MAX_METHOD_RESULTS,
    MAX_PRICE_RESULTS,
    MAX_QUEST_RESULTS,
    MAX_SEARCH_RESULTS,
    MAX_TOOL_RESULT_CHARS,
)
from tracker.content.requirements import (
    AccountTypeLeaf,
    AllOf,
    AnyOf,
    AtLeast,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MembersLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
    iter_leaves,
)
from tracker.content.schema import Candidate, TrainingMethod
from tracker.domain.types import QuestStatus, Status, UnlockState
from tracker.estimation.xp_table import xp_for_level
from tracker.gear.render import render_setup
from tracker.gear.setup import STYLES
from tracker.integrations.llm.types import ToolCall, ToolResult

_SATISFIED = "satisfied"
_UNSATISFIED = "unsatisfied"
_UNKNOWN = "unknown"

_TRUNCATION_MARKER = "\n\n…truncated. Narrow the query and ask again."


class _BadArgument(ValueError):
    """A malformed or unusable argument. Becomes an error result, not a traceback."""


def execute_tool(snapshot: AdvisorSnapshot, call: ToolCall) -> ToolResult:
    """Answer one tool call from already-computed state. Never writes, never fetches."""
    handler = _HANDLERS.get(call.name)
    if handler is None:
        return _error(call, f"there is no tool named {call.name!r}")
    try:
        body = handler(snapshot, call.arguments)
    except _BadArgument as bad:
        return _error(call, str(bad))
    return ToolResult(call_id=call.call_id, content=_truncate(body))


def _truncate(body: str) -> str:
    if len(body) <= MAX_TOOL_RESULT_CHARS:
        return body
    return body[: MAX_TOOL_RESULT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call_id=call.call_id, content=message, is_error=True)


# ---------------------------------------------------------------------------
# Argument reading
# ---------------------------------------------------------------------------


def _required_str(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _BadArgument(f"{key!r} is required and must be a non-empty string")
    return value.strip()


def _optional_str(arguments: Mapping[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _BadArgument(f"{key!r} must be a string")
    return value.strip() or None


def _optional_int(arguments: Mapping[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _BadArgument(f"{key!r} must be an integer")
    return value


def _optional_bool(arguments: Mapping[str, Any], key: str) -> bool | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _BadArgument(f"{key!r} must be true or false")
    return value


def _limit(arguments: Mapping[str, Any], ceiling: int) -> int:
    """Clamp rather than reject. A model asking for 500 wants *lots*, not an error."""
    requested = _optional_int(arguments, "limit")
    if requested is None:
        return ceiling
    return max(1, min(requested, ceiling))


def _string_list(arguments: Mapping[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise _BadArgument(f"{key!r} must be an array")
    if not all(isinstance(item, str) for item in value):
        raise _BadArgument(f"every entry in {key!r} must be a string")
    return [str(item) for item in value]


def _int_list(arguments: Mapping[str, Any], key: str) -> list[int]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise _BadArgument(f"{key!r} must be an array of integers")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise _BadArgument(f"every entry in {key!r} must be an integer")
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Three-valued leaf state
# ---------------------------------------------------------------------------


def _leaf_state(leaf: Requirement, snapshot: AdvisorSnapshot) -> str:
    """One leaf against this account, in §9.1's three values.

    ``unlock: available`` resolves **unsatisfied**, per §9.1's table: obtainable is not held.
    An item with no container ever scanned is *unknown* rather than absent, because nobody has
    looked — G3, the same rule that keeps ``liquid_gp`` out of ``0``.
    """
    state = snapshot.state
    if isinstance(leaf, SkillLeaf):
        observed = state.skills.get(leaf.skill)
        if observed is None:
            return _UNKNOWN
        return _SATISFIED if observed.level >= leaf.level else _UNSATISFIED
    if isinstance(leaf, QuestLeaf):
        status = state.quests.get(leaf.quest_id)
        if status is None:
            return _UNKNOWN
        return _SATISFIED if status is QuestStatus.COMPLETE else _UNSATISFIED
    if isinstance(leaf, UnlockLeaf):
        unlock = state.unlocks.get(leaf.key)
        if unlock is None:
            return _UNKNOWN
        return _SATISFIED if unlock is UnlockState.UNLOCKED else _UNSATISFIED
    if isinstance(leaf, ItemLeaf):
        return _item_state(leaf, snapshot)
    if isinstance(leaf, MilestoneLeaf):
        milestone = state.milestones.get(leaf.key)
        if milestone is None:
            return _UNKNOWN
        return _SATISFIED if milestone.achieved else _UNSATISFIED
    if isinstance(leaf, CapabilityLeaf):
        for view in snapshot.capabilities:
            if view.capability_id == leaf.capability_id:
                if view.status is Status.UNKNOWN:
                    return _UNKNOWN
                return _SATISFIED if view.status is Status.UNLOCKED else _UNSATISFIED
        return _UNKNOWN
    if isinstance(leaf, CombatLevelLeaf):
        if state.combat_level is None:
            return _UNKNOWN
        return _SATISFIED if state.combat_level >= leaf.level else _UNSATISFIED
    if isinstance(leaf, QuestPointsLeaf):
        if state.quest_points is None:
            return _UNKNOWN
        return _SATISFIED if state.quest_points >= leaf.points else _UNSATISFIED
    if isinstance(leaf, AccountTypeLeaf):
        if state.account_type is None:
            return _UNKNOWN
        return _SATISFIED if state.account_type.value == leaf.account_type else _UNSATISFIED
    if isinstance(leaf, MembersLeaf):
        if state.members is None:
            return _UNKNOWN
        return _SATISFIED if state.members == leaf.members else _UNSATISFIED
    return _UNKNOWN


def _item_state(leaf: ItemLeaf, snapshot: AdvisorSnapshot) -> str:
    declared = snapshot.content.items.get(leaf.item_id)
    if declared is None or declared.item_id is None:
        return _UNKNOWN
    if declared.item_id in snapshot.state.observed_items:
        return _SATISFIED
    # Nobody has scanned anything, so absence from the observation map is not evidence.
    if not snapshot.state.container_scans:
        return _UNKNOWN
    return _UNSATISFIED


def _leaf_label(leaf: Requirement, snapshot: AdvisorSnapshot) -> str:
    if isinstance(leaf, SkillLeaf):
        declared = snapshot.content.skills.get(leaf.skill)
        name = declared.name if declared is not None else leaf.skill
        observed = snapshot.state.skills.get(leaf.skill)
        current = "never observed" if observed is None else f"currently {observed.level}"
        return f"{name} {leaf.level} ({current})"
    if isinstance(leaf, QuestLeaf):
        quest = snapshot.content.quests.get(leaf.quest_id)
        return f"quest: {quest.name if quest is not None else leaf.quest_id}"
    if isinstance(leaf, UnlockLeaf):
        return f"unlock: {leaf.key}"
    if isinstance(leaf, ItemLeaf):
        item = snapshot.content.items.get(leaf.item_id)
        return f"item: {item.name if item is not None else leaf.item_id}"
    if isinstance(leaf, MilestoneLeaf):
        return f"milestone: {leaf.key}"
    if isinstance(leaf, CapabilityLeaf):
        capability = snapshot.content.capabilities.get(leaf.capability_id)
        return f"capability: {capability.name if capability is not None else leaf.capability_id}"
    if isinstance(leaf, CombatLevelLeaf):
        return f"combat level {leaf.level}"
    if isinstance(leaf, QuestPointsLeaf):
        return f"{leaf.points} quest points"
    if isinstance(leaf, AccountTypeLeaf):
        return f"account type: {leaf.account_type}"
    if isinstance(leaf, MembersLeaf):
        return "members" if leaf.members else "free-to-play"
    return type(leaf).__name__


def _render_tree(tree: Requirement | None, snapshot: AdvisorSnapshot, depth: int = 0) -> list[str]:
    """The tree with its structure kept.

    Flattening to a leaf list would lose the ``any_of`` distinction, and *"one of these three"*
    versus *"all three"* is exactly the difference between a task being nearly done and barely
    started.
    """
    if tree is None:
        return []
    pad = "  " * depth
    if isinstance(tree, AllOf):
        lines = [f"{pad}- all of:"]
        for child in tree.children:
            lines += _render_tree(child, snapshot, depth + 1)
        return lines
    if isinstance(tree, AnyOf):
        lines = [f"{pad}- any of:"]
        for child in tree.children:
            lines += _render_tree(child, snapshot, depth + 1)
        return lines
    if isinstance(tree, AtLeast):
        lines = [f"{pad}- at least {tree.n} of:"]
        for child in tree.of:
            lines += _render_tree(child, snapshot, depth + 1)
        return lines
    if isinstance(tree, Not):
        return [f"{pad}- not:", *_render_tree(tree.child, snapshot, depth + 1)]
    return [f"{pad}- {_leaf_label(tree, snapshot)} — {_leaf_state(tree, snapshot)}"]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _ranked_by_id(snapshot: AdvisorSnapshot) -> dict[str, RankedTask]:
    found = {task.candidate_id: task for task in snapshot.blocked}
    found.update({task.candidate_id: task for task in snapshot.ranked})
    return found


def _skills_named(candidate: Candidate) -> set[str]:
    names: set[str] = set()
    for tree in (candidate.requires, candidate.completion, candidate.grants_facts):
        if tree is None:
            continue
        names |= {leaf.skill for leaf in iter_leaves(tree) if isinstance(leaf, SkillLeaf)}
    return names


def _search_candidates(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    query = (_optional_str(arguments, "query") or "").lower()
    kind = _optional_str(arguments, "kind")
    skill = _optional_str(arguments, "skill")
    blocked = _optional_bool(arguments, "blocked")
    limit = _limit(arguments, MAX_SEARCH_RESULTS)
    ranked = _ranked_by_id(snapshot)

    matches = []
    for candidate_id in sorted(snapshot.content.candidates):
        candidate = snapshot.content.candidates[candidate_id]
        if query and query not in candidate.name.lower() and query not in candidate_id.lower():
            continue
        if kind is not None and candidate.kind.value != kind:
            continue
        if skill is not None and skill not in _skills_named(candidate):
            continue
        task = ranked.get(candidate_id)
        if blocked is not None and bool(task and task.blocked) != blocked:
            continue
        matches.append((candidate, task))

    if not matches:
        return "No candidate in the corpus matches that."

    shown = matches[:limit]
    body = f"{len(matches)} matching candidates.\n\n" + "\n".join(
        _search_line(candidate, task) for candidate, task in shown
    )
    if len(matches) > len(shown):
        body += f"\n\n{len(matches) - len(shown)} more match; narrow the query to see them."
    return body


def _search_line(candidate: Candidate, task: RankedTask | None) -> str:
    parts = [f"- `{candidate.id}` — {candidate.name} ({candidate.kind.value.replace('_', ' ')})"]
    if task is None:
        parts.append("  not in the latest ranked run")
        return "\n".join(parts)
    estimate = []
    if task.hours is not None:
        estimate.append(f"{task.hours:.1f}h")
    if task.gp is not None:
        estimate.append(f"{task.gp:,} gp")
    if estimate:
        parts.append(f"  tracker estimate: {', '.join(estimate)} ({task.confidence})")
    parts.append(f"  rank {task.rank}{'; currently blocked' if task.blocked else ''}")
    return "\n".join(parts)


def _get_candidate_detail(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    candidate_id = _required_str(arguments, "candidate_id")
    candidate = snapshot.content.candidates.get(candidate_id)
    if candidate is None:
        return f"No candidate with id {candidate_id!r}. Use `search_candidates` to find it."

    task = _ranked_by_id(snapshot).get(candidate_id)
    lines = [
        f"# {candidate.name}",
        "",
        f"- id: `{candidate.id}`",
        f"- kind: {candidate.kind.value.replace('_', ' ')}",
    ]
    if task is None:
        lines.append("- not in the latest ranked run")
    else:
        lines.append(f"- rank in the latest run: {task.rank}")
        if task.reason:
            lines.append(f"- the engine's reason: {task.reason}")
        if task.blocked:
            lines.append("- currently blocked")

    for label, tree in (
        ("Requirements", candidate.requires),
        ("Completion", candidate.completion),
        ("Grants on completion", candidate.grants_facts),
    ):
        rendered = _render_tree(tree, snapshot)
        if rendered:
            lines += ["", f"## {label}", *rendered]

    if task is not None and task.bands:
        lines += ["", "## The tracker's estimate, by level band", ""]
        for band in task.bands:
            method = band.method_id if band.method_id is not None else "no authored method"
            note = " — conservative default, nothing authored here" if band.fallback else ""
            lines.append(
                f"- {band.from_level}→{band.to_level} via {method}: "
                f"{band.hours:.1f}h, {band.gp:,} gp{note}"
            )

    if task is not None and task.blockers:
        lines += ["", "## Not yet met", ""]
        lines += [f"- {blocker.description}" for blocker in task.blockers]

    if task is not None:
        lines += _consequence_lines(task)
    return "\n".join(lines)


def _consequence_lines(task: RankedTask) -> list[str]:
    consequences = task.consequences
    lines: list[str] = []
    if consequences.unblocks_capabilities:
        lines.append(
            "- unblocks: " + ", ".join(item.name for item in consequences.unblocks_capabilities)
        )
    if consequences.gate_progress:
        lines.append(
            "- is a prerequisite of: " + ", ".join(item.name for item in consequences.gate_progress)
        )
    if consequences.goal_progress:
        lines.append(
            "- moves toward: " + ", ".join(item.name for item in consequences.goal_progress)
        )
    if consequences.speeds_up:
        lines.append(
            "- speeds up: "
            + ", ".join(
                f"{item.name} ({item.hours_before:.1f}h → {item.hours_after:.1f}h)"
                for item in consequences.speeds_up
            )
        )
    return ["", "## What completing it would do", "", *lines] if lines else []


def _get_capability_detail(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    capability_id = _required_str(arguments, "capability_id")
    declared = snapshot.content.capabilities.get(capability_id)
    if declared is None:
        known = ", ".join(sorted(snapshot.content.capabilities)) or "none"
        return f"No capability with id {capability_id!r}. Declared capabilities: {known}."

    view = next(
        (item for item in snapshot.capabilities if item.capability_id == capability_id), None
    )
    lines = [f"# {declared.name}", "", f"- id: `{declared.id}`"]
    if view is None:
        lines.append("- state: not computed for this account")
    else:
        readiness = (
            view.readiness_confidence.name.lower()
            if view.readiness_confidence is not None
            else _UNKNOWN
        )
        recommended = "yes" if view.recommended_now else "no"
        if not view.recommended_now and view.recommended_now_reason:
            recommended += f" — {view.recommended_now_reason}"
        lines += [
            f"- status: {view.status.value}",
            f"- requirements met: {view.unlock_fraction:.0%}",
            f"- readiness confidence: {readiness}",
            f"- recommended to use now: {recommended}",
        ]
        lines += [f"- warning: {warning}" for warning in view.warnings]

    rendered = _render_tree(declared.requires, snapshot)
    if rendered:
        lines += ["", "## Requirements", *rendered]
    return "\n".join(lines)


def _list_training_methods(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    skill_id = _required_str(arguments, "skill_id")
    from_level = _optional_int(arguments, "from_level")
    to_level = _optional_int(arguments, "to_level")

    matches = [
        method
        for _, method in sorted(snapshot.content.training_methods.items())
        if method.skill == skill_id and _overlaps(method, from_level, to_level)
    ]
    if not matches:
        declared = snapshot.content.skills.get(skill_id)
        name = declared.name if declared is not None else skill_id
        return (
            f"The content corpus holds no training method for {name} in that range. "
            "Say so rather than presenting your own suggestion as the tracker's."
        )

    shown = matches[:MAX_METHOD_RESULTS]
    body = "\n\n".join(_method_block(method, snapshot) for method in shown)
    if len(matches) > len(shown):
        body += f"\n\n{len(matches) - len(shown)} further methods are not shown."
    return body


def _overlaps(method: TrainingMethod, from_level: int | None, to_level: int | None) -> bool:
    if from_level is not None and method.level_range.max < from_level:
        return False
    return not (to_level is not None and method.level_range.min > to_level)


def _method_block(method: TrainingMethod, snapshot: AdvisorSnapshot) -> str:
    lines = [
        f"## {method.name}",
        f"- id: `{method.id}`",
        f"- levels {method.level_range.min}–{method.level_range.max}",
        f"- {method.xp_per_hour:,} xp/hour, {method.cost_per_hour_gp:,} gp/hour",
    ]
    detail = method.detail
    if detail.location:
        lines.append(f"- where: {detail.location}")
    if detail.target:
        lines.append(f"- what: {detail.target}")
    if detail.gear:
        lines.append("- gear (descriptive, gates nothing): " + ", ".join(detail.gear))
    if detail.inventory:
        lines.append("- inventory (descriptive, gates nothing): " + ", ".join(detail.inventory))
    if detail.notes:
        lines.append(f"- notes: {detail.notes}")
    if detail.wiki_url:
        lines.append(f"- wiki: {detail.wiki_url}")
    rendered = _render_tree(method.requires, snapshot, depth=1)
    if rendered:
        lines += ["- requires:", *rendered]
    return "\n".join(lines)


def _get_quest_status(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    quest_ids = _string_list(arguments, "quest_ids")
    name_query = (_optional_str(arguments, "name_query") or "").lower()
    wanted = _optional_str(arguments, "status")
    limit = _limit(arguments, MAX_QUEST_RESULTS)

    unknown_ids = [quest_id for quest_id in quest_ids if quest_id not in snapshot.content.quests]
    if unknown_ids:
        return f"No quest in the corpus with id(s): {', '.join(sorted(unknown_ids))}."

    matches = []
    for quest_id in sorted(snapshot.content.quests):
        quest = snapshot.content.quests[quest_id]
        if quest_ids and quest_id not in quest_ids:
            continue
        if name_query and name_query not in quest.name.lower() and name_query not in quest_id:
            continue
        status = snapshot.state.quests.get(quest_id)
        word = status.value if status is not None else _UNKNOWN
        if wanted is not None and word != wanted:
            continue
        matches.append(f"- {quest.name} (`{quest_id}`): {word}")

    if not matches:
        return "No quest matches that."
    shown = matches[:limit]
    body = "\n".join(shown)
    if len(matches) > len(shown):
        body += f"\n\n{len(matches) - len(shown)} more match; narrow the query to see them."
    return body + "\n\n`unknown` means nobody has observed it — not the same as not started."


def _get_skill_detail(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    skill_id = _required_str(arguments, "skill_id")
    declared = snapshot.content.skills.get(skill_id)
    if declared is None:
        return f"No skill with id {skill_id!r}."

    observed = snapshot.state.skills.get(skill_id)
    lines = [f"# {declared.name}", ""]
    if observed is None:
        lines.append("- never observed — nobody has synced this skill")
    elif observed.xp is None:
        lines.append(f"- level {observed.level}, unranked (no XP recorded)")
    else:
        lines.append(f"- level {observed.level}, {observed.xp:,} xp")
        if observed.level < 99:
            lines.append(
                f"- {xp_for_level(observed.level + 1) - observed.xp:,} xp to level "
                f"{observed.level + 1}"
            )
            lines.append(f"- {xp_for_level(99) - observed.xp:,} xp to 99")

    depending = sorted(
        capability.name
        for capability in snapshot.content.capabilities.values()
        if capability.requires is not None
        and skill_id
        in {leaf.skill for leaf in iter_leaves(capability.requires) if isinstance(leaf, SkillLeaf)}
    )
    if depending:
        lines += ["", "## Capabilities that need it", "", *[f"- {name}" for name in depending]]

    tasks = [
        task
        for task in snapshot.ranked
        if (candidate := snapshot.content.candidates.get(task.candidate_id)) is not None
        and skill_id in _skills_named(candidate)
    ]
    if tasks:
        lines += ["", "## Ranked tasks that name it", ""]
        lines += [f"- rank {task.rank}: {task.name}" for task in tasks]
    return "\n".join(lines)


def _get_item_price(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    item_ids = _int_list(arguments, "item_ids")
    name_query = (_optional_str(arguments, "name_query") or "").lower()
    limit = _limit(arguments, MAX_PRICE_RESULTS)

    if not item_ids and not name_query:
        raise _BadArgument("supply either 'item_ids' or 'name_query'")

    matches: list[PriceFact] = []
    missing: list[str] = []
    for item_id in item_ids:
        price = snapshot.prices.get(item_id)
        if price is None:
            missing.append(str(item_id))
        else:
            matches.append(price)
    if name_query:
        matches += [
            price
            for price in snapshot.prices.values()
            if name_query in price.name.lower() and price not in matches
        ]

    lines = [_price_line(price) for price in matches[:limit]]
    body = "\n".join(lines) if lines else "Nothing in the price cache matches that."
    if missing:
        body += (
            f"\n\nNot in the price cache: {', '.join(missing)}. The tracker only caches prices "
            "for items its content references — do not substitute a price of your own."
        )
    if lines:
        body += (
            "\n\nTrade time is when the trade happened; fetch time is when the tracker last "
            "asked. A recent fetch of an old trade is not a current price."
        )
    return body


def _price_line(price: PriceFact) -> str:
    amount = f"{price.price_gp:,} gp" if price.price_gp is not None else "no usable price recorded"
    trade = price.trade_at.date().isoformat() if price.trade_at is not None else _UNKNOWN
    return (
        f"- {price.name} (`{price.item_id}`): {amount} — traded {trade}, "
        f"fetched {price.fetched_at.date().isoformat()}, source {price.provider}"
    )


_Handler = Callable[[AdvisorSnapshot, Mapping[str, Any]], str]


def _get_gear_setup(snapshot: AdvisorSnapshot, arguments: Mapping[str, Any]) -> str:
    """Project §23.4's setup for one style. **Computes nothing** — D15.

    Every decision rendered here was made in
    :func:`~tracker.advisor.snapshot.build_advisor_snapshot` while the turn's inputs were
    being frozen. This handler picks a style out of that frozen structure and renders it; it
    does not evaluate a requirement, read a price, or accept any argument that could describe
    an account other than this one. That is the whole of what makes a gear tool safe here.
    """
    style = _required_str(arguments, "style")
    setup = snapshot.gear.setup(style)
    if setup is None:
        raise _BadArgument(f"no ladder for style {style!r}; the styles are " + ", ".join(STYLES))

    slot = _optional_str(arguments, "slot")
    if slot is not None:
        known = sorted({plan.slot for plan in setup.slots})
        if slot not in known:
            raise _BadArgument(
                f"no {style} ladder for slot {slot!r}; this style has " + ", ".join(known)
            )

    body = render_setup(setup, slots=(slot,) if slot is not None else None)
    if snapshot.gear.fully_scanned:
        return body
    # Prepended rather than appended: it qualifies everything below it.
    scanned = ", ".join(snapshot.gear.scanned_containers) or "nothing"
    return (
        f"Not every container has been scanned — so far: {scanned}. Anything reported as "
        "unknown below is unknown, not absent.\n\n" + body
    )


_HANDLERS: Mapping[str, _Handler] = {
    "search_candidates": _search_candidates,
    "get_candidate_detail": _get_candidate_detail,
    "get_capability_detail": _get_capability_detail,
    "get_gear_setup": _get_gear_setup,
    "list_training_methods": _list_training_methods,
    "get_quest_status": _get_quest_status,
    "get_skill_detail": _get_skill_detail,
    "get_item_price": _get_item_price,
}
