"""Cross-object content validation — the §10.7 rules a single model cannot check.

*"Unvalidated YAML fails at runtime with an unhelpful ``KeyError``, typically months
later."* — §10.7

The §10.7 assertions are enforced in three places, chosen by how much of the corpus each
rule needs to see:

| §10.7 rule | Enforced by |
|---|---|
| id uniqueness across the corpus (per kind) | :func:`tracker.content.loader.parse_corpus` |
| referential integrity of capability/quest/item/skill/milestone ids | here |
| every ``grants`` target is a declared capability | here |
| every candidate ``advances`` target is a declared capability | here |
| every ``practiced_by`` entry is a declared practice domain | ``PracticeDomain`` enum |
| every refresher's ``practice_group`` has an execution member | here |
| every refresher declares ``suggested_session_hours`` | ``RefresherTemplate`` field |
| every candidate declares a non-empty ``completion`` | ``Candidate`` model validator |
| only ``class: execution`` milestones practice | ``Milestone`` model validator |
| ``price_mode: live`` implies a numeric ``item_id`` | here |
| a gear ``tier`` implies a ``slot`` and ``style``, and each rung is unique | here |
| a numeric item id is claimed by one *piece* (two rows only as placements of it) | here |
| an item's wear gate resolves its referenced ids (§23.2) | here |
| no item declares both `requires` and `gate_unknown` | here |
| capability and requirement graphs are acyclic | here |
| weights, ``pvp_value``, ``advances`` and roadmap weights ∈ [0,1] | model validators |
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
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

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
from tracker.content.schema import Item
from tracker.domain.types import MilestoneClass

#: §9.6's validation block, restated so a retune cannot quietly leave the sane range.
KAPPA_MIN_GP = 1_000_000
KAPPA_MAX_GP = 250_000_000


def validate_content(content: Content) -> list[ContentError]:
    """Every cross-object §10.7 rule. Returns all violations; never raises."""
    errors: list[ContentError] = []
    errors.extend(_check_references(content))
    errors.extend(_check_grants(content))
    errors.extend(_check_candidate_advances(content))
    errors.extend(_check_roadmap_guides(content))
    errors.extend(_check_unique_skill_targets(content))
    errors.extend(_check_practice_groups(content))
    errors.extend(_check_live_prices(content))
    errors.extend(_check_gear_ladders(content))
    errors.extend(_check_item_requirements(content))
    errors.extend(_check_item_acquisition(content))
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
            yield "training_method", method.id, method.requires
    # A candidate carries up to three trees (§10.6). All three name game objects, so all
    # three need referential integrity — `grants_facts` especially, since a fact naming
    # an item nobody declared would silently contribute nothing to `leverage` rather than
    # failing.
    for candidate in content.candidates.values():
        for tree in (candidate.requires, candidate.completion, candidate.grants_facts):
            if tree is not None:
                yield "candidate", candidate.id, tree
    # §23.2's wear gates. Without this loop an item's tree gets no referential integrity at
    # all, and a mistyped quest id becomes a gate that evaluates UNKNOWN forever rather than
    # an error — which renders as "requirements not checked" on an item whose requirements
    # *were* checked. Silent in both directions, so it is worth the one loop.
    for item in content.items.values():
        if item.requires is not None:
            yield "item", item.id, item.requires
    for guide in content.roadmap_guides.values():
        for tier in guide.tiers:
            for step in tier.preparation:
                if step.completion is not None:
                    yield "roadmap_guide", guide.id, step.completion
            for encounter in tier.encounters:
                for tree in (encounter.access, encounter.recommendations):
                    if tree is not None:
                        yield "roadmap_guide", guide.id, tree


def _check_references(content: Content) -> list[ContentError]:
    """Every referenced capability, quest, item, skill and milestone id resolves.

    ``unlock:`` leaves are deliberately **not** checked: §6.3 makes the unlock key space
    open, with reserved ``spellbook_``/``diary_``/``ca_`` prefixes supplied by the
    plugin rather than declared in content.
    """
    errors: list[ContentError] = []

    def missing(kind: str, owner_id: str, what: str, referenced: str) -> ContentError:
        return ContentError(
            f"references {what} {referenced!r}, which is not declared anywhere in the corpus",
            content.location_of(kind, owner_id).with_path(owner_id),
        )

    for kind, owner_id, requirement in _requirement_sources(content):
        for leaf in iter_leaves(requirement):
            if isinstance(leaf, SkillLeaf) and leaf.skill not in content.skills:
                errors.append(missing(kind, owner_id, "skill", leaf.skill))
            elif isinstance(leaf, QuestLeaf) and leaf.quest_id not in content.quests:
                errors.append(missing(kind, owner_id, "quest", leaf.quest_id))
            elif isinstance(leaf, ItemLeaf) and leaf.item_id not in content.items:
                errors.append(missing(kind, owner_id, "item", leaf.item_id))
            elif isinstance(leaf, MilestoneLeaf) and leaf.key not in content.milestones:
                errors.append(missing(kind, owner_id, "milestone", leaf.key))
            elif (
                isinstance(leaf, CapabilityLeaf) and leaf.capability_id not in content.capabilities
            ):
                errors.append(missing(kind, owner_id, "capability", leaf.capability_id))

    for method in content.training_methods.values():
        if method.skill not in content.skills:
            errors.append(missing("training_method", method.id, "skill", method.skill))

    for roadmap in content.roadmaps.values():
        for capability_id in roadmap.capabilities:
            if capability_id not in content.capabilities:
                errors.append(missing("roadmap", roadmap.id, "capability", capability_id))

    for refresher in content.refreshers.values():
        for capability_id in refresher.advances:
            if capability_id not in content.capabilities:
                errors.append(missing("refresher", refresher.id, "capability", capability_id))

    return errors


def _check_grants(content: Content) -> list[ContentError]:
    """Every ``grants`` target is a declared capability (§10.7)."""
    return [
        ContentError(
            f"grants {granted!r}, which is not a declared capability",
            content.location_of("capability", capability.id).with_path(capability.id),
        )
        for capability in content.capabilities.values()
        for granted in capability.grants
        if granted not in content.capabilities
    ]


def _check_candidate_advances(content: Content) -> list[ContentError]:
    """Every candidate ``advances`` target is a declared capability (§10.6, §10.7).

    A dangling target does not merely mis-score: ``pvp_value`` looks the capability up in
    the §9.3 effective-weight map, misses, and contributes ``0`` — so a typo makes a
    candidate quietly less relevant instead of loudly wrong, which is the failure mode
    §10.7 exists to prevent.
    """
    return [
        ContentError(
            f"advances {capability_id!r}, which is not a declared capability",
            content.location_of("candidate", candidate.id).with_path(candidate.id),
        )
        for candidate in content.candidates.values()
        for capability_id in candidate.advances
        if capability_id not in content.capabilities
    ]


def _check_roadmap_guides(content: Content) -> list[ContentError]:
    """Validate guide references, nested identity, and safe external links."""
    errors: list[ContentError] = []

    def problem(guide_id: str, message: str) -> ContentError:
        return ContentError(
            message,
            content.location_of("roadmap_guide", guide_id).with_path(guide_id),
        )

    def check_https(guide_id: str, label: str, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None:
            errors.append(
                problem(guide_id, f"{label} must use HTTPS without credentials; got {url!r}")
            )

    for guide in content.roadmap_guides.values():
        roadmap = content.roadmaps.get(guide.roadmap_id)
        if roadmap is None:
            errors.append(
                problem(
                    guide.id,
                    f"references roadmap {guide.roadmap_id!r}, which is not declared anywhere "
                    "in the corpus",
                )
            )
        check_https(guide.id, "source.url", guide.source.url)

        tier_ids: set[str] = set()
        preparation_ids: set[str] = set()
        encounter_ids: set[str] = set()
        for tier in guide.tiers:
            if tier.id in tier_ids:
                errors.append(problem(guide.id, f"duplicate tier id {tier.id!r}"))
            tier_ids.add(tier.id)

            if tier.capability_id not in content.capabilities:
                errors.append(
                    problem(
                        guide.id,
                        f"tier {tier.id!r} references capability {tier.capability_id!r}, "
                        "which is not declared anywhere in the corpus",
                    )
                )
            elif roadmap is not None and tier.capability_id not in roadmap.capabilities:
                errors.append(
                    problem(
                        guide.id,
                        f"tier {tier.id!r} capability {tier.capability_id!r} is not included "
                        f"in roadmap {roadmap.id!r}",
                    )
                )

            for step in tier.preparation:
                if step.id in preparation_ids:
                    errors.append(problem(guide.id, f"duplicate preparation id {step.id!r}"))
                preparation_ids.add(step.id)
                if step.wiki_url is not None:
                    check_https(guide.id, f"preparation {step.id!r} wiki_url", step.wiki_url)
                if len(set(step.candidate_ids)) != len(step.candidate_ids):
                    errors.append(
                        problem(guide.id, f"preparation {step.id!r} repeats a candidate reference")
                    )
                for candidate_id in step.candidate_ids:
                    if candidate_id not in content.candidates:
                        errors.append(
                            problem(
                                guide.id,
                                f"preparation {step.id!r} references candidate {candidate_id!r}, "
                                "which is not declared anywhere in the corpus",
                            )
                        )

            for encounter in tier.encounters:
                if encounter.id in encounter_ids:
                    errors.append(problem(guide.id, f"duplicate encounter id {encounter.id!r}"))
                encounter_ids.add(encounter.id)
                check_https(guide.id, f"encounter {encounter.id!r} wiki_url", encounter.wiki_url)

    return errors


def _check_unique_skill_targets(content: Content) -> list[ContentError]:
    """No two candidates complete on the same ``(skill, level)`` target.

    Two candidates whose ``completion`` names the same skill level are the same action
    written twice: they become satisfied on the same sync, they are estimated over the
    same band, and until then they occupy two slots on a list that holds
    ``max_primary_entries``. The failure is silent without this check — nothing raises,
    the user simply sees "Train Magic to 94" twice.

    Introduced with generated skill bands (Step 5). The generator skips any target an
    authored candidate already claims, and this is the rule that makes that skip
    load-bearing rather than merely polite: a hand-authored duplicate fails here too.
    """
    seen: dict[tuple[str, int], str] = {}
    errors: list[ContentError] = []
    for candidate in sorted(content.candidates.values(), key=lambda c: c.id):
        for leaf in iter_leaves(candidate.completion):
            if not isinstance(leaf, SkillLeaf):
                continue
            key = (leaf.skill, leaf.level)
            first = seen.setdefault(key, candidate.id)
            if first != candidate.id:
                errors.append(
                    ContentError(
                        f"completes on {leaf.skill} {leaf.level}, which {first!r} already "
                        "completes on. Two candidates finishing on the same fact are the "
                        "same action listed twice (§10.7)",
                        content.location_of("candidate", candidate.id).with_path(candidate.id),
                    )
                )
    return errors


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
        location = content.location_of("refresher", refresher.id).with_path(refresher.id)
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
                            content.location_of("capability", target).with_path(target),
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
        f"{len(content.candidates)} candidates, {len(content.roadmaps)} roadmaps, "
        f"{len(content.milestones)} milestones, {len(content.items)} items, "
        f"{len(content.training_methods)} training methods, "
        f"{len(content.refreshers)} refreshers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
