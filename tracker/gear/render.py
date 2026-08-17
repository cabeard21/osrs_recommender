"""One stable markdown rendering of a computed setup (§23.4, §22.4).

The advisor's tool result is text, and §22.4 requires it bounded and truncated with a marker
rather than silently. That is this module's job. The UI does **not** use it: §15 renders from
view-model rows, and two renderings of one computation is already the established shape here
(``digest._consequence_line`` beside ``dispatch._consequence_lines``).

Everything is ordered and nothing iterates a set, because §22.3 hashes what comes out.

The wording carries three distinctions a caller must not flatten:

* *held* / *not held* / *unknown* are three answers, and the third means nobody has looked.
* A gate the account fails is different from a gate nobody has written down.
* A rung above the recommendation is named *with what blocks it*, so the reader learns the
  requirement rather than merely that one exists.
"""

from __future__ import annotations

from tracker.domain.types import LeafRef, Tri
from tracker.gear.setup import GearPick, GearSetup, SetupSlot

#: Blockers named on one line before the rest become a count. Three is enough to say
#: *"60 Attack, Monkey Madness I"* without a wall of leaves on a distant rung.
MAX_NAMED_BLOCKERS = 3

_HELD_WORD = {
    Tri.SATISFIED: "held",
    Tri.UNSATISFIED: "not held",
    Tri.UNKNOWN: "unknown whether held — not every container has been scanned",
}


def render_setup(setup: GearSetup, *, slots: tuple[str, ...] | None = None) -> str:
    """One style's setup as markdown, optionally narrowed to some slots."""
    wanted = [slot for slot in setup.slots if slots is None or slot.slot in slots]
    lines = [
        f"# {setup.style.capitalize()} gear",
        "",
        "Computed by the tracker from the wiki's progression ladders and this account's "
        "observed items, skills and quests. Rung numbers are the guides' ordering, not a "
        "power rating: rung 6 is the step after rung 5, not twice as good as rung 3.",
        "",
    ]
    for slot in wanted:
        lines += _slot_lines(slot)

    missing = [pick.name for pick in setup.missing]
    total = setup.to_complete_gp
    if not missing:
        lines += ["", "Every recommended piece is already held."]
    elif total is not None:
        lines += [
            "",
            f"Still to get: {', '.join(missing)} — roughly {total:,} gp at cached prices.",
        ]
    else:
        lines += [
            "",
            f"Still to get: {', '.join(missing)}. No total, because at least one has no "
            "cached price and a sum of only the ones that do would understate it.",
        ]

    lines += _not_counted(setup, wanted)
    return "\n".join(lines).rstrip() + "\n"


def _not_counted(setup: GearSetup, slots: list[SetupSlot]) -> list[str]:
    """What the bill leaves out, and why — said rather than left to be noticed.

    The total covers what can be bought, so a piece the account could wear and must win never
    enters it. That is correct and it is also an *absence*, which §4.5 spends this codebase
    insisting is a different thing from a stated fact. A model reading a bill with no cape in
    it has two ways to explain the gap, and one of them is to price the cape from its own
    knowledge of the game.
    """
    targets = [slot.earn for slot in slots if slot.earn is not None]
    if not targets:
        return []
    named = ", ".join(
        f"{pick.name} ({pick.acquired_from})" for pick in targets if pick.acquired_from
    )
    named = named or ", ".join(pick.name for pick in targets)
    return [
        "",
        f"Not in that figure: {named}. These are pieces the account can already wear and "
        "cannot buy at any price, so they carry no cost — only the content that yields them.",
    ]


def _slot_lines(slot: SetupSlot) -> list[str]:
    lines = [f"## {slot.slot} ({rungs_label(slot.ladder_size)})"]

    if slot.recommended is None and slot.earn is not None:
        # The reason matters. Saying "no rung's requirements are met" here would be false —
        # they are met, and what is missing is a way to get one. Ranged capes are the whole
        # ladder in this state: every rung is earned, so there is nothing to buy at all.
        lines.append(
            "- best you can equip: nothing you can buy — every rung on this ladder has to be "
            "earned, so the target below is the whole answer"
        )
    elif slot.recommended is None:
        lines.append(
            "- best you can equip: nothing on this ladder — no rung's requirements are "
            "known to be met"
        )
    else:
        lines.append(f"- best you can equip: {_pick_line(slot.recommended)}")

    if slot.best_held is None:
        unseen = "- holding: nothing on this ladder has been seen"
        if not slot.certain:
            unseen += (
                " — and not every container has been scanned, so this is unknown rather than none"
            )
        lines.append(unseen)
    elif slot.recommended is not None and slot.best_held.item_id == slot.recommended.item_id:
        # The same rung, so the line above already said it. Repeating it verbatim spends the
        # result's budget on a restatement and invites the model to narrate an upgrade
        # between two identical pieces.
        lines.append("- holding: the same rung — nothing better is owned for this slot")
    else:
        lines.append(f"- holding: {_pick_line(slot.best_held)}")

    if slot.holds_what_it_cannot_wear:
        lines.append(
            "- note: the rung held is above the rung whose requirements are met. Both are "
            "shown rather than the higher one taken, because one of the two is wrong."
        )

    if slot.also_held:
        lines.append("- also holding: " + ", ".join(pick.name for pick in slot.also_held))

    if slot.next_rung is not None:
        lines.append(f"- next rung: {_pick_line(slot.next_rung)}")

    if slot.earn is not None and (
        slot.next_rung is None or slot.earn.item_id != slot.next_rung.item_id
    ):
        # Named separately only when it is not already the line above. The two coincide often
        # — the rung above the recommendation is frequently the untradeable one — and saying
        # it twice spends the result's bound restating a fact, which is the collapse §23.5
        # asks for on `holding` for the same reason.
        lines.append(f"- to earn: {_pick_line(slot.earn)}")

    lines.extend(f"- above that: {_pick_line(pick)}" for pick in slot.aspirational[1:])
    lines.append("")
    return lines


def _pick_line(pick: GearPick) -> str:
    parts = [f"{pick.name} (rung {pick.tier} of the ladder)", _HELD_WORD[pick.held]]

    if pick.gate_unknown:
        parts.append("requirements not established by the tracker — do not assume it is wearable")
    elif pick.fit is Tri.UNSATISFIED:
        parts.append(f"needs {_leaves(pick.blockers)}")
    elif pick.fit is Tri.UNKNOWN:
        parts.append(f"cannot tell — nobody has observed {_leaves(pick.unknowns)}")

    parts.extend(_acquisition_words(pick))
    return "; ".join(parts)


def _acquisition_words(pick: GearPick) -> list[str]:
    """§23.2's second axis, and the price — which are one decision rather than two.

    A gp figure beside something the market does not sell is a number inviting an action
    nobody can take, and in the same sentence as *"cannot be bought"* it reads as a
    contradiction the model will try to resolve. So an untradeable rung says what wins it and
    says nothing about money.

    A **tradeable** rung says nothing about acquisition at all, on the rule ``fit_label``
    already follows: an answer of *yes* earns no space in a bounded result.
    """
    if pick.obtainable is Tri.UNSATISFIED:
        earned = f" — earned from {pick.acquired_from}" if pick.acquired_from else ""
        return [f"cannot be bought{earned}"]

    words = []
    if pick.obtainable is Tri.UNKNOWN:
        words.append("the tracker has not recorded how this is obtained")
    words.append(f"{pick.price_gp:,} gp cached" if pick.price_gp is not None else "no cached price")
    return words


def rungs_label(size: int) -> str:
    """*"1 rungs"* is a stated fact that is wrong, on a page whose whole argument is that a
    stated fact is read literally.

    Not hypothetical since the melee ammunition ladder landed: the guides list one blessing
    for that slot and nothing else, so the corpus now really does hold a ladder of one. Shared
    with :mod:`tracker.ui.read_model` so the page and the tool result cannot disagree about
    it.
    """
    return f"{size} rung" if size == 1 else f"{size} rungs"


def _leaves(refs: tuple[LeafRef, ...]) -> str:
    """Name the first few, then count the rest — a truncation that says it truncated."""
    if not refs:
        return "something the corpus did not name"
    named = [ref.description for ref in refs[:MAX_NAMED_BLOCKERS]]
    remaining = len(refs) - len(named)
    if remaining > 0:
        named.append(f"and {remaining} more")
    return ", ".join(named)
