"""Cross-object validation for authored account and Gear facts."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from tracker.content.errors import ContentError
from tracker.content.loader import (
    DEFAULT_CONTENT_DIR,
    Content,
    ContentValidationError,
    parse_corpus,
)
from tracker.content.requirements import (
    ItemLeaf,
    QuestLeaf,
    SkillLeaf,
    iter_leaves,
)
from tracker.content.schema import Item


def validate_content(content: Content) -> list[ContentError]:
    """Return every cross-object factual content violation."""
    errors = _check_references(content)
    errors.extend(_check_live_prices(content))
    errors.extend(_check_gear_ladders(content))
    errors.extend(_check_item_requirements(content))
    errors.extend(_check_item_acquisition(content))
    return errors


def load_and_validate(root: Path | str = DEFAULT_CONTENT_DIR) -> Content:
    """Parse and cross-check factual content."""
    content, errors = parse_corpus(root)
    if content is not None:
        errors.extend(validate_content(content))
    if content is None or errors:
        raise ContentValidationError(errors)
    return content


def _check_references(content: Content) -> list[ContentError]:
    errors: list[ContentError] = []
    for item in content.items.values():
        if item.requires is None:
            continue
        location = content.location_of("item", item.id).with_path(item.id)
        for leaf in iter_leaves(item.requires):
            missing: str | None = None
            if isinstance(leaf, SkillLeaf) and leaf.skill not in content.skills:
                missing = f"skill {leaf.skill!r}"
            elif isinstance(leaf, QuestLeaf) and leaf.quest_id not in content.quests:
                missing = f"quest {leaf.quest_id!r}"
            elif isinstance(leaf, ItemLeaf) and leaf.item_id not in content.items:
                missing = f"item {leaf.item_id!r}"
            if missing is not None:
                errors.append(
                    ContentError(
                        f"references {missing}, which is not declared in the factual corpus",
                        location,
                    )
                )
    return errors


def _check_live_prices(content: Content) -> list[ContentError]:
    """``price_mode: live`` needs the numeric id the price API is keyed by (§8.3)."""
    return [
        ContentError(
            "has price_mode: live but no numeric item_id; the OSRS Wiki price API is keyed "
            "by item id, so this item could never be priced live (§10.5)",
            content.location_of("item", item.id).with_path(item.id),
        )
        for item in content.items.values()
        if item.price_mode == "live" and item.item_id is None
    ]


def _check_gear_ladders(content: Content) -> list[ContentError]:
    """A rung needs a ladder, a ladder has one item per rung, and an id belongs to one item.

    Three failures, none of which raise on their own:

    *A tier with no slot or style* is a number with nothing to order it against. It reads
    like progression data and contributes none, so it is rejected rather than ignored.

    *Two items on the same rung* makes "their best melee weapon" ambiguous, and which one
    wins would fall to dict ordering — the exact non-determinism §21.5's cache cannot take.

    *One id on two items* means a single observed item would mark both as held — which is
    **right** when the two rows are the same piece of gear on two different ladders, and
    wrong every other time. An Antler guard is one shield and the guides put it on the melee
    and the ranged progression both; owning it really does place the account on both. So the
    rule is not *"an id belongs to one row"* but *"an id belongs to one **piece**"*, and rows
    sharing an id must prove they are placements of it: same name, same ownership union, same
    wear gate, same acquisition, same pricing, and different ladders. Anything else is the
    aliasing slip this rule was written for — the corrupt fixture is a Voidwaker id listed
    among an Armadyl godsword's variants — and is still rejected.
    """
    errors: list[ContentError] = []
    rungs: dict[tuple[str, str, int], str] = {}
    owners: dict[int, Item] = {}

    for item in content.items.values():
        location = content.location_of("item", item.id).with_path(item.id)
        if item.tier is not None and (item.slot is None or item.style is None):
            errors.append(
                ContentError(
                    f"declares tier {item.tier} but no gear ladder to sit on; tier needs "
                    "both slot and style to mean anything (§10.5)",
                    location,
                )
            )
        elif item.tier is not None and item.slot is not None and item.style is not None:
            rung = (item.style, item.slot, item.tier)
            if rung in rungs:
                errors.append(
                    ContentError(
                        f"shares {item.style} {item.slot} tier {item.tier} with "
                        f"{rungs[rung]!r}; a rung holds one item, or 'the best held' is a "
                        "coin toss (§10.5)",
                        location,
                    )
                )
            else:
                rungs[rung] = item.id

        for item_id in sorted(item.owned_item_ids):
            other = owners.get(item_id)
            if other is not None and other.id != item.id:
                if _same_piece(item, other):
                    continue
                errors.append(
                    ContentError(
                        f"claims item id {item_id}, which {other.id!r} also claims, and the "
                        "two are not the same piece on different ladders; one observation "
                        "would mark both items held (§10.5)",
                        location,
                    )
                )
            else:
                owners[item_id] = item

    return errors


#: What two rows must agree on to be placements of one piece of gear rather than two items
#: that have collided. Everything about the *item*; nothing about where it sits.
_PIECE_FIELDS = (
    "name",
    "item_id",
    "variant_item_ids",
    "requires",
    "gate_unknown",
    "acquisition",
    "acquired_from",
    "price_mode",
    "fallback_price_gp",
    "price_staleness_days",
)


def _same_piece(left: Item, right: Item) -> bool:
    """Whether two rows are one piece of gear placed on two ladders (§10.5).

    The permission is deliberately narrow. Sharing an id lets one observation mark both rows
    held, so the rows must be indistinguishable as *items* — the only things allowed to differ
    are ``id``, ``style``, ``slot`` and ``tier``, which say where the piece sits and nothing
    about what it is. A second row with a different wear gate would be two answers to *"can I
    equip this"* for one object in the bank, and the surfaces would show whichever the
    iteration order handed them.

    They must also sit on **different** ladders. Two placements on one ladder is a piece
    occupying two rungs of its own progression, which is a duplicate however it is spelled.
    """
    if (left.style, left.slot) == (right.style, right.slot):
        return False
    return all(getattr(left, field) == getattr(right, field) for field in _PIECE_FIELDS)


def _check_item_requirements(content: Content) -> list[ContentError]:
    """§23.2's two failures: a contradictory gate, and a gate that can never be satisfied.

    *An item declaring both ``requires`` and ``gate_unknown``* asserts at once that the
    gate is known and that it is not. The two fields exist to keep three answers apart
    (§10.5), and an item claiming two of them leaves the reader to pick — so it is
    rejected rather than resolved by precedence, which would only hide the authoring slip.

    *An item requirement cycle* — ``a`` needs ``b`` needs ``a`` — is a gate no account can
    ever satisfy, and the evaluator would descend it rather than report it. The diagnostic
    prints the path for :func:`_check_acyclic`'s reason: a bare "there is a cycle" leaves
    the author to find it by hand.

    A **monotonicity** rule was considered and deliberately left out: *a rung may not be
    gated more weakly than the rung below it* sounds right and is not, because requirements
    are not totally ordered. Barrows gloves are a quest and Ferocious gloves are a level;
    neither is weaker than the other, and a corpus stating both correctly would fail.
    """
    errors: list[ContentError] = []
    edges: dict[str, list[str]] = {}

    for item in content.items.values():
        location = content.location_of("item", item.id).with_path(item.id)
        if item.requires is not None and item.gate_unknown:
            errors.append(
                ContentError(
                    "declares both requires and gate_unknown; the gate is either known or "
                    "it is not, and claiming both leaves the reader to choose (§10.5)",
                    location,
                )
            )
        edges[item.id] = (
            [
                leaf.item_id
                for leaf in iter_leaves(item.requires)
                if isinstance(leaf, ItemLeaf) and leaf.item_id in content.items
            ]
            if item.requires is not None
            else []
        )

    errors.extend(
        ContentError(
            f"item requirements form a cycle: {' -> '.join(cycle)}; no account can ever "
            "satisfy it (§10.5)",
            content.location_of("item", cycle[0]).with_path(cycle[0]),
        )
        for cycle in _cycles(edges)
    )
    return errors


def _check_item_acquisition(content: Content) -> list[ContentError]:
    """§10.5's acquisition axis: a source belongs only to a piece you cannot buy.

    ``acquired_from`` names the content that yields an **untradeable** piece. On a
    ``tradeable`` one it sends a reader to a boss for something the market sells; on an
    unclassified one the corpus claims at once that nobody knows how the piece is obtained
    and that it comes from the Inferno. Rejected rather than resolved by precedence, for
    :func:`_check_item_requirements`'s reason — picking one would only hide the slip.

    The **converse is deliberately not a rule.** An ``untradeable`` piece with no source is
    allowed: requiring the prose would turn a missing sentence into a blocked corpus edit,
    and every surface has an honest line for it. §4.5's discipline is about never converting
    an absence into a claim, not about forbidding absences.

    There is also no rule that an ``acquisition`` be declared at all. Absence is the third
    state (§10.5) and §23.4 does not demote on it; what makes the absence trustworthy is
    ``tools.gear_ladders.missing_acquisitions``, which proves the authoring partition total
    on the side that can act on it.
    """
    return [
        ContentError(
            "declares acquired_from without acquisition: untradeable. Naming the content "
            "that yields a piece the market sells sends the reader to a boss for something "
            "they can buy, and naming it on an unclassified piece says at once that nobody "
            "knows how it is obtained and where it comes from (§10.5)",
            content.location_of("item", item.id).with_path(item.id),
        )
        for item in content.items.values()
        if item.acquired_from is not None and item.acquisition != "untradeable"
    ]


def _cycles(edges: Mapping[str, list[str]]) -> list[list[str]]:
    """Every cycle in a small graph, each reported once and as the path that closes it."""
    found: list[list[str]] = []
    seen_cycles: set[frozenset[str]] = set()
    settled: set[str] = set()

    def walk(node: str, stack: list[str], on_stack: set[str]) -> None:
        if node in on_stack:
            cycle = [*stack[stack.index(node) :], node]
            key = frozenset(cycle)
            if key not in seen_cycles:
                seen_cycles.add(key)
                found.append(cycle)
            return
        if node in settled:
            return
        stack.append(node)
        on_stack.add(node)
        for target in edges.get(node, ()):
            walk(target, stack, on_stack)
        on_stack.discard(node)
        stack.pop()
        settled.add(node)

    for start in sorted(edges):
        walk(start, [], set())
    return found


def _sort_key(error: ContentError) -> tuple[str, int, str]:
    location = error.location
    return (str(location.file or ""), location.line or 0, error.message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracker.content.validate",
        description="Validate authored skill, quest, and item facts.",
    )
    parser.add_argument(
        "--content-dir",
        default=os.environ.get("TRACKER_CONTENT_DIR", str(DEFAULT_CONTENT_DIR)),
        help="content root (default: content/)",
    )
    args = parser.parse_args(argv)
    content, errors = parse_corpus(args.content_dir)
    if content is not None:
        errors.extend(validate_content(content))
    if errors:
        print(f"{len(errors)} content problems found:", file=sys.stderr)
        for error in sorted(errors, key=_sort_key):
            print(f"  {error}", file=sys.stderr)
        return 1
    if content is None:
        print("content could not be loaded", file=sys.stderr)
        return 1
    print(
        f"content OK — {len(content.skills)} skills, "
        f"{len(content.quests)} quests, {len(content.items)} items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
