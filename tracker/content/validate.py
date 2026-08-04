"""Cross-object content validation — the §10.7 rules a single model cannot check.

*"Unvalidated YAML fails at runtime with an unhelpful ``KeyError``, typically months
later."* — §10.7

The twelve §10.7 assertions are enforced in three places, chosen by how much of the
corpus each rule needs to see:

| §10.7 rule | Enforced by |
|---|---|
| id uniqueness across the corpus | :func:`tracker.content.loader.parse_corpus` |
| referential integrity of capability/quest/item/skill/milestone ids | here |
| every ``grants`` target is a declared capability | here |
| every ``practiced_by`` entry is a declared practice domain | ``PracticeDomain`` enum |
| every refresher's ``practice_group`` has an execution member | here |
| only ``class: execution`` milestones practice | ``Milestone`` model validator |
| ``price_mode: live`` implies a numeric ``item_id`` | here |
| capability and requirement graphs are acyclic | here |
| weights, ``pvp_value``, roadmap weights ∈ [0,1] | model ``Field`` bounds |
| κ presets satisfy §9.6 min/max/ordering | here |

Rules land in the models where a single object can decide, and here where they need the
rest of the corpus. Nothing is checked in two places.

Run as ``python -m tracker.content.validate`` (this is what ``make validate-content``
invokes); exits non-zero with one located diagnostic per problem.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from tracker.content.errors import ContentError, ContentLocation
from tracker.content.loader import (
    DEFAULT_CONTENT_DIR,
    Content,
    ContentValidationError,
    parse_corpus,
)
from tracker.content.requirements import (
    CapabilityLeaf,
    ItemLeaf,
    MilestoneLeaf,
    QuestLeaf,
    Requirement,
    SkillLeaf,
    iter_leaves,
)
from tracker.domain.types import MilestoneClass

#: §9.6's validation block, restated so a retune cannot quietly leave the sane range.
KAPPA_MIN_GP = 1_000_000
KAPPA_MAX_GP = 250_000_000


def validate_content(content: Content) -> list[ContentError]:
    """Every cross-object §10.7 rule. Returns all violations; never raises."""
    errors: list[ContentError] = []
    errors.extend(_check_references(content))
    errors.extend(_check_grants(content))
    errors.extend(_check_practice_groups(content))
    errors.extend(_check_live_prices(content))
    errors.extend(_check_acyclic(content))
    errors.extend(_check_kappa(content))
    return errors


def load_and_validate(
    root: Path | str = DEFAULT_CONTENT_DIR, *, profile_path: Path | str | None = None
) -> Content:
    """Parse **and** cross-check. The entry point everything outside tests should use."""
    content, errors = parse_corpus(root, profile_path=profile_path)
    if content is not None:
        errors.extend(validate_content(content))
    if content is None or errors:
        raise ContentValidationError(errors)
    return content


# ---------------------------------------------------------------------------
# Referential integrity
# ---------------------------------------------------------------------------


def _requirement_sources(content: Content) -> Iterator[tuple[str, str, Requirement]]:
    """Every requirement tree in the corpus, with the id of the object that owns it."""
    for capability in content.capabilities.values():
        if capability.requires is not None:
            yield "capability", capability.id, capability.requires
    for method in content.training_methods.values():
        if method.requires is not None:
            yield "training method", method.id, method.requires


def _check_references(content: Content) -> list[ContentError]:
    """Every referenced capability, quest, item, skill and milestone id resolves.

    ``unlock:`` leaves are deliberately **not** checked: §6.3 makes the unlock key space
    open, with reserved ``spellbook_``/``diary_``/``ca_`` prefixes supplied by the
    plugin rather than declared in content.
    """
    errors: list[ContentError] = []

    def missing(owner_id: str, what: str, referenced: str) -> ContentError:
        return ContentError(
            f"references {what} {referenced!r}, which is not declared anywhere in the corpus",
            content.location_of(owner_id).with_path(owner_id),
        )

    for _label, owner_id, requirement in _requirement_sources(content):
        for leaf in iter_leaves(requirement):
            if isinstance(leaf, SkillLeaf) and leaf.skill not in content.skills:
                errors.append(missing(owner_id, "skill", leaf.skill))
            elif isinstance(leaf, QuestLeaf) and leaf.quest_id not in content.quests:
                errors.append(missing(owner_id, "quest", leaf.quest_id))
            elif isinstance(leaf, ItemLeaf) and leaf.item_id not in content.items:
                errors.append(missing(owner_id, "item", leaf.item_id))
            elif isinstance(leaf, MilestoneLeaf) and leaf.key not in content.milestones:
                errors.append(missing(owner_id, "milestone", leaf.key))
            elif (
                isinstance(leaf, CapabilityLeaf) and leaf.capability_id not in content.capabilities
            ):
                errors.append(missing(owner_id, "capability", leaf.capability_id))

    for method in content.training_methods.values():
        if method.skill not in content.skills:
            errors.append(missing(method.id, "skill", method.skill))

    for roadmap in content.roadmaps.values():
        for capability_id in roadmap.capabilities:
            if capability_id not in content.capabilities:
                errors.append(missing(roadmap.id, "capability", capability_id))

    for refresher in content.refreshers.values():
        for capability_id in refresher.advances:
            if capability_id not in content.capabilities:
                errors.append(missing(refresher.id, "capability", capability_id))

    return errors


def _check_grants(content: Content) -> list[ContentError]:
    """Every ``grants`` target is a declared capability (§10.7)."""
    return [
        ContentError(
            f"grants {granted!r}, which is not a declared capability",
            content.location_of(capability.id).with_path(capability.id),
        )
        for capability in content.capabilities.values()
        for granted in capability.grants
        if granted not in content.capabilities
    ]


# ---------------------------------------------------------------------------
# Practice groups (§9.8, §10.4)
# ---------------------------------------------------------------------------


def _check_practice_groups(content: Content) -> list[ContentError]:
    """Every ``practice_group`` a refresher names has ≥1 ``class: execution`` member.

    A refresher for an empty group would be synthesized, scored, and recommend a
    practice session for nothing — and because only execution milestones age (§6.6), a
    group of non-execution members can never become stale enough to trigger it.
    """
    errors: list[ContentError] = []
    for refresher in content.refreshers.values():
        members = content.milestones_in_group(refresher.practice_group)
        location = content.location_of(refresher.id).with_path(refresher.id)
        if not members:
            errors.append(
                ContentError(
                    f"names practice_group {refresher.practice_group!r}, which no milestone "
                    "belongs to",
                    location,
                )
            )
            continue
        if not any(member.class_ is MilestoneClass.EXECUTION for member in members):
            names = ", ".join(member.id for member in members)
            errors.append(
                ContentError(
                    f"names practice_group {refresher.practice_group!r}, whose members "
                    f"({names}) include no class: execution milestone — only execution "
                    "milestones age (§6.6), so this refresher can never trigger",
                    location,
                )
            )
    return errors


# ---------------------------------------------------------------------------
# Prices (§10.5)
# ---------------------------------------------------------------------------


def _check_live_prices(content: Content) -> list[ContentError]:
    """``price_mode: live`` needs the numeric id the price API is keyed by (§8.3)."""
    return [
        ContentError(
            "has price_mode: live but no numeric item_id; the OSRS Wiki price API is keyed "
            "by item id, so this item could never be priced live (§10.5)",
            content.location_of(item.id).with_path(item.id),
        )
        for item in content.items.values()
        if item.price_mode == "live" and item.item_id is None
    ]


# ---------------------------------------------------------------------------
# Acyclicity (§10.7)
# ---------------------------------------------------------------------------


def _capability_edges(content: Content) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = {}
    for capability in content.capabilities.values():
        targets: list[str] = []
        if capability.requires is not None:
            targets = [
                leaf.capability_id
                for leaf in iter_leaves(capability.requires)
                if isinstance(leaf, CapabilityLeaf)
            ]
        edges[capability.id] = targets
    return edges


def _check_acyclic(content: Content) -> list[ContentError]:
    """The capability graph is a DAG — and the diagnostic names the cycle.

    §10.7 asks for acyclicity; reporting a bare boolean would leave the author to find
    the loop by hand in a corpus of dozens of files, so the walk keeps its stack and
    prints the actual path.
    """
    edges = _capability_edges(content)
    errors: list[ContentError] = []
    visited: set[str] = set()
    on_stack: list[str] = []
    in_stack: set[str] = set()
    reported: set[frozenset[str]] = set()

    def walk(node: str) -> None:
        visited.add(node)
        on_stack.append(node)
        in_stack.add(node)
        for target in edges.get(node, ()):
            if target in in_stack:
                cycle = [*on_stack[on_stack.index(target) :], target]
                signature = frozenset(cycle)
                if signature not in reported:
                    reported.add(signature)
                    errors.append(
                        ContentError(
                            "capability requirements form a cycle: " + " → ".join(cycle),
                            content.location_of(target).with_path(target),
                        )
                    )
            elif target not in visited and target in edges:
                walk(target)
        on_stack.pop()
        in_stack.discard(node)

    for capability_id in sorted(edges):
        if capability_id not in visited:
            walk(capability_id)
    return errors


# ---------------------------------------------------------------------------
# Scoring profile (§9.6)
# ---------------------------------------------------------------------------


def _check_kappa(content: Content) -> list[ContentError]:
    """κ presets stay in range and keep their ordering (§9.6's validation block).

    ``high < normal < low`` reads backwards until you remember what the setting means:
    *high* sensitivity to cost means expensive things are discouraged **sooner**, which
    is a **smaller** κ.
    """
    kappa = content.profile.kappa_gp
    location = ContentLocation(path="scoring_profile.kappa_gp")
    errors: list[ContentError] = []

    for name, value in (("high", kappa.high), ("normal", kappa.normal), ("low", kappa.low)):
        if not KAPPA_MIN_GP <= value <= KAPPA_MAX_GP:
            errors.append(
                ContentError(
                    f"κ preset {name} is {value:,} gp, outside the §9.6 range "
                    f"{KAPPA_MIN_GP:,}–{KAPPA_MAX_GP:,}",
                    location,
                )
            )

    if not kappa.high < kappa.normal:
        errors.append(
            ContentError(
                f"κ ordering violated: high ({kappa.high:,}) must be less than normal "
                f"({kappa.normal:,}) — higher cost sensitivity means a smaller κ (§9.6)",
                location,
            )
        )
    if not kappa.normal < kappa.low:
        errors.append(
            ContentError(
                f"κ ordering violated: normal ({kappa.normal:,}) must be less than low "
                f"({kappa.low:,}) (§9.6)",
                location,
            )
        )
    return errors


# ---------------------------------------------------------------------------
# CLI — `make validate-content`
# ---------------------------------------------------------------------------


def _sort_key(error: ContentError) -> tuple[str, int, str]:
    location = error.location
    return (str(location.file or ""), location.line or 0, error.message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tracker.content.validate",
        description="Validate the authored content corpus against §10.7.",
    )
    parser.add_argument(
        "--content-dir",
        default=os.environ.get("TRACKER_CONTENT_DIR", str(DEFAULT_CONTENT_DIR)),
        help="corpus root (default: content/)",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("TRACKER_SCORING_PROFILE_PATH"),
        help="scoring profile path (default: <content-dir>/scoring/profile.yaml)",
    )
    args = parser.parse_args(argv)

    content, errors = parse_corpus(args.content_dir, profile_path=args.profile)
    if content is not None:
        errors.extend(validate_content(content))

    if errors:
        count = len(errors)
        noun = "problem" if count == 1 else "problems"
        print(f"{count} content {noun} found:", file=sys.stderr)
        for error in sorted(errors, key=_sort_key):
            print(f"  {error}", file=sys.stderr)
        return 1

    if content is None:  # pragma: no cover — unreachable: a failure always adds an error
        print("content could not be loaded", file=sys.stderr)
        return 1

    print(
        f"content OK — {len(content.capabilities)} capabilities, "
        f"{len(content.roadmaps)} roadmaps, {len(content.milestones)} milestones, "
        f"{len(content.items)} items, {len(content.training_methods)} training methods, "
        f"{len(content.refreshers)} refreshers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
