"""The roadmap-scoped item id set (§8.3, §11.6).

*"Only items referenced by the active roadmap's capabilities, candidates and training
methods are fetched. The full item economy is never pulled — that would recreate the
item database §3 rules out."* This module is what keeps that promise: it walks the
authored content graph reachable from a set of active roadmap ids and returns exactly
the numeric OSRS item ids a price fetch is allowed to touch. Nothing outside this
closure is ever handed to :class:`tracker.integrations.prices.client.PricesClient`.

The closure is:

1. every capability directly weighted by one of the given roadmaps;
2. every capability transitively reachable from those through a ``capability:`` leaf
   (§10.2 — capabilities compose into a DAG, e.g. ``deep_wildy_nh`` requires
   ``ice_barrage_nh``);
3. every candidate in that closure, if the corpus has any — Step 2.5 lands the
   ``Candidate`` content type in a parallel step, so :class:`~tracker.content.loader.Content`
   may or may not carry a ``candidates`` mapping yet. This module does not hard-depend
   on that sibling step's schema landing first; it degrades to "no candidates" rather
   than failing to import;
4. every training method for a skill named by a ``skill:`` leaf anywhere in (1)-(3),
   since a method can itself require an item (e.g. a staff needed to use a spell) even
   though the capability leaf that pulled the skill in says nothing about it.

Only ``item:`` leaves within that closure contribute — never every ``Item`` the corpus
happens to declare.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from tracker.content.loader import Content
from tracker.content.requirements import (
    CapabilityLeaf,
    ItemLeaf,
    Requirement,
    RequirementNode,
    SkillLeaf,
    iter_leaves,
)


def scoped_item_ids(content: Content, roadmap_ids: Iterable[str]) -> frozenset[int]:
    """Numeric OSRS item ids referenced by the given roadmaps' transitive closure.

    Returns numeric ids (what the price API is keyed by), resolved through each
    ``Item.item_id`` — content ids that resolve to no numeric id (``price_mode:
    static`` items need none) are silently excluded rather than erroring, since a
    missing numeric id there is not a scoping bug.
    """
    capability_ids = _reachable_capability_ids(content, roadmap_ids)

    trees: list[Requirement] = []
    for capability_id in capability_ids:
        capability = content.capabilities.get(capability_id)
        if capability is not None and capability.requires is not None:
            trees.append(capability.requires)
    trees.extend(_candidate_trees(content, capability_ids))

    content_item_ids: set[str] = set()
    skill_ids: set[str] = set()
    for tree in trees:
        for leaf in iter_leaves(tree):
            if isinstance(leaf, ItemLeaf):
                content_item_ids.add(leaf.item_id)
            elif isinstance(leaf, SkillLeaf):
                skill_ids.add(leaf.skill)

    for skill_id in skill_ids:
        for method in content.methods_for_skill(skill_id):
            if method.requires is None:
                continue
            for leaf in iter_leaves(method.requires):
                if isinstance(leaf, ItemLeaf):
                    content_item_ids.add(leaf.item_id)

    numeric_ids: set[int] = set()
    for content_item_id in content_item_ids:
        item = content.items.get(content_item_id)
        if item is not None and item.item_id is not None:
            numeric_ids.add(item.item_id)
    return frozenset(numeric_ids)


def _reachable_capability_ids(content: Content, roadmap_ids: Iterable[str]) -> frozenset[str]:
    """Capabilities a roadmap weights, plus every capability reachable via
    ``capability:`` leaves from those (§10.2's capability DAG)."""
    queue: list[str] = []
    for roadmap_id in roadmap_ids:
        roadmap = content.roadmaps.get(roadmap_id)
        if roadmap is not None:
            queue.extend(roadmap.capabilities)

    seen: set[str] = set()
    while queue:
        capability_id = queue.pop()
        if capability_id in seen:
            continue
        seen.add(capability_id)
        capability = content.capabilities.get(capability_id)
        if capability is None or capability.requires is None:
            continue
        for leaf in iter_leaves(capability.requires):
            if isinstance(leaf, CapabilityLeaf):
                queue.append(leaf.capability_id)
    return frozenset(seen)


def _candidate_trees(content: Content, capability_ids: frozenset[str]) -> list[Requirement]:
    """Requirement-shaped trees off any authored ``Candidate`` (§10.6, D11).

    Guarded with ``getattr``/``hasattr`` throughout: the ``Candidate`` content type is
    Step 2.5's responsibility, developed in parallel, and this module must not assume
    its exact shape (or even its existence in ``Content``) has landed.
    """
    candidates = getattr(content, "candidates", None)
    if not candidates:
        return []
    trees: list[Requirement] = []
    for candidate in candidates.values():
        advances = getattr(candidate, "advances", ())
        if advances and not (set(advances) & capability_ids):
            continue
        for attr in ("requires", "completion"):
            node = getattr(candidate, attr, None)
            if isinstance(node, RequirementNode):
                # `node` is dynamically confirmed to be one of the concrete leaf/
                # combinator classes that make up the `Requirement` union — mypy just
                # cannot see that `RequirementNode` (checked here) and `Requirement`
                # (the discriminated union `iter_leaves` expects) describe the same
                # set of classes, since Candidate's own schema is Step 2.5's, not
                # statically known to this module.
                trees.append(cast(Requirement, node))
    return trees
