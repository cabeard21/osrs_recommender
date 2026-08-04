"""Time and GP for one candidate — the §8 subsystem's entry point.

*"Train Magic 87 → 94, ~4.5 hours, ~1.8M gp"* (§8). This module assembles that line from
the two halves the rest of the package computes: :mod:`tracker.estimation.methods` for the
level bands and their rates, :mod:`tracker.estimation.prices` for what the items cost.

Which kinds get which number
----------------------------

``Estimate.hours`` and ``Estimate.gp`` are both ``| None``, and the reason is that §10.6
authors neither. There is no ``hours`` field and no ``gp_cost`` field on a candidate —
deliberately, so *"an author cannot make a candidate look cheap by saying it is"* — which
means every figure here has to be derived from something the corpus states for another
reason. The derivations, and therefore the answer per kind:

* **hours** come from ``skill:`` leaves in ``completion``. §8.2's algorithm is defined
  over *"remaining XP to target"*, and a completion predicate naming ``skill: {magic: 94}``
  is the only place a corpus states a target. This is a rule about the predicate rather
  than about ``kind``, which is why ``unlock_protect_item`` — ``kind: unlock``, completion
  ``skill: {prayer: 25}`` plus the unlock — gets real hours: the work *is* the Prayer
  levels. ``requires`` is never used for hours: it is a gate, and training toward it is a
  different candidate.
* **hours for ``kind: practice``** come from the refresher template's
  ``suggested_session_hours`` (§10.4, A8) — mandatory precisely so a refresher cannot
  score a perfect ``effort_decay``.
* **gp** is the training cost of the bands (``cost_per_hour_gp × hours``, §8.1) plus the
  acquisition cost of every ``item:`` leaf in ``completion`` or ``requires`` that the
  player is not already observed to hold. ``kind: practice`` is ``0`` (§10.4).
* **Neither** for a candidate whose completion names no skill and no item — a ``quest:``
  candidate is the corpus's example. ``None`` is the honest answer: the SDD authors no
  quest duration anywhere, and a fabricated *"3 hours"* would feed §9.4's ``effort_decay``
  a number no content supports and no test could ever be wrong about.

Confidence
----------

§8.4: ``estimate_confidence`` is the **minimum** of price confidence and training-method
confidence — *"an estimate is only as good as its weakest input"*. Either half may be
absent (a pure acquisition trains nothing; a pure training candidate buys nothing), in
which case the other stands alone. When both are absent there is no estimate to qualify
and the answer is ``low``: a page showing nothing has not earned ``high``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from tracker.content.loader import Content
from tracker.content.requirements import ItemLeaf, Requirement, SkillLeaf, iter_leaves
from tracker.content.schema import Candidate, Item
from tracker.domain.types import (
    BandEstimate,
    CandidateKind,
    Confidence,
    Estimate,
    PlayerState,
    Tri,
)
from tracker.estimation.methods import method_confidence, plan_bands
from tracker.estimation.prices import PriceRecord, ResolvedPrice, resolve_price
from tracker.estimation.xp_table import xp_for_level
from tracker.progression.evaluate import Evaluator


def estimate(
    candidate: Candidate,
    state: PlayerState,
    content: Content,
    prices: Mapping[int, PriceRecord],
    now: datetime,
    *,
    evaluator: Evaluator | None = None,
) -> Estimate:
    """Estimate hours and GP for one candidate (§8). Pure — no I/O, no clock.

    ``prices`` is keyed by **numeric** OSRS item id, matching ``Item.item_id`` and the
    mapping :func:`tracker.integrations.prices.cache.resolve_prices` returns. Prices are
    passed in, never fetched: Step 7 owns fetching and Step 9 owns persisting, and §16.1
    forbids this package from importing either.

    ``evaluator`` is optional so that Step 6, which estimates every candidate against one
    account, can share a single memo table — a ``capability:`` prerequisite shared by ten
    method gates is then walked once rather than ten times.
    """
    session = evaluator if evaluator is not None else Evaluator(state, content)

    bands, hours, training_gp, method_conf = _training(candidate, state, content, session)
    charges = _acquisition_charges(candidate, state, content, prices, now, session)

    gp = _total_gp(training_gp, charges)
    price_conf = _minimum(charge.price.confidence for charge in charges)

    return Estimate(
        hours=hours,
        gp=gp,
        confidence=_estimate_confidence(price_conf, method_conf),
        bands=bands,
        price_selection_reason=_selection_reason(charges),
    )


# ---------------------------------------------------------------------------
# Time (§8.2)
# ---------------------------------------------------------------------------


def _training(
    candidate: Candidate, state: PlayerState, content: Content, session: Evaluator
) -> tuple[tuple[BandEstimate, ...], float | None, int | None, Confidence | None]:
    """``(bands, hours, training gp, method confidence)`` for one candidate.

    Two different absences reach the caller as ``hours is None``, and the fourth element
    tells them apart: a candidate with no training targets at all contributes **no**
    method confidence (``None``, so the price half decides the estimate alone), while a
    candidate whose target skill has never been observed contributes ``low`` — there is a
    training half here and we cannot size it.
    """
    if candidate.kind is CandidateKind.PRACTICE:
        return _practice(candidate, content)

    targets = _skill_targets(candidate.completion)
    if not targets:
        return (), None, None, None

    bands: list[BandEstimate] = []
    for skill, target_level in targets.items():
        snapshot = state.skills.get(skill)
        if snapshot is None:
            # §4.5: absence of evidence is not evidence. Assuming level 1 would quote
            # forty hours the account may not owe; assuming the target is met would quote
            # zero. Neither is a fact, so the estimate is withheld and flagged `low` —
            # *"sync this"*, which is the same answer §9.1 gives the requirement leaf.
            return (), None, None, Confidence.LOW
        current_xp = snapshot.xp if snapshot.xp is not None else xp_for_level(snapshot.level)
        bands.extend(
            plan_bands(
                skill,
                current_xp=current_xp,
                from_level=snapshot.level,
                to_level=target_level,
                content=content,
                evaluator=session,
            )
        )

    ordered = tuple(bands)
    return (
        ordered,
        sum(band.hours for band in ordered),
        sum(band.gp for band in ordered),
        method_confidence(ordered),
    )


def _practice(
    candidate: Candidate, content: Content
) -> tuple[tuple[BandEstimate, ...], float | None, int | None, Confidence | None]:
    """§10.4 — a refresher's hours are authored on its template, and it costs nothing.

    The template is looked up by the candidate's own id because §9.8 synthesizes one
    candidate per template. A ``kind: practice`` candidate with no matching template is
    not an error here (Step 6 may synthesize one from a group directly), but it has no
    authored session length, and A8 is explicit about what happens to a refresher with no
    hours: ``effort_decay = exp(0) = 1.0``, a perfect effort mark. ``None`` keeps that
    decision with the caller instead of manufacturing it here.
    """
    template = content.refreshers.get(candidate.id)
    if template is None:
        return (), None, 0, Confidence.LOW
    return (), template.suggested_session_hours, 0, Confidence.HIGH


def _skill_targets(completion: Requirement) -> dict[str, int]:
    """The highest level each ``skill:`` leaf of ``completion`` asks for.

    The maximum, not the sum or the last: a completion predicate naming the same skill
    twice (an ``any_of`` over two routes, say) is done when the higher target is met.
    """
    targets: dict[str, int] = {}
    for leaf in iter_leaves(completion):
        if isinstance(leaf, SkillLeaf):
            targets[leaf.skill] = max(targets.get(leaf.skill, 0), leaf.level)
    return targets


# ---------------------------------------------------------------------------
# GP (§8.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Charge:
    """One item the candidate has to acquire, and what the §8.3 cascade said it costs."""

    item_id: str
    price: ResolvedPrice


def _acquisition_charges(
    candidate: Candidate,
    state: PlayerState,
    content: Content,
    prices: Mapping[int, PriceRecord],
    now: datetime,
    session: Evaluator,
) -> tuple[_Charge, ...]:
    """Price every ``item:`` leaf of ``completion`` and ``requires`` the player lacks.

    **A leaf that already evaluates ``satisfied`` is not charged.** Billing a player for
    a Voidwaker sitting in their bank would inflate the very candidate they are closest
    to finishing. ``unknown`` *is* charged, and that asymmetry is deliberate: §8.3's
    selection order is conservative because *"a recommendation to buy something should
    estimate cost conservatively"*, and an item nobody has scanned for is one we cannot
    claim they hold (§4.5).

    Order is completion-then-requires, first mention wins, so the reason string reads in
    the order the author wrote the predicate.
    """
    charges: list[_Charge] = []
    seen: set[str] = set()

    for tree in (candidate.completion, candidate.requires):
        if tree is None:
            continue
        for leaf in iter_leaves(tree):
            if not isinstance(leaf, ItemLeaf) or leaf.item_id in seen:
                continue
            seen.add(leaf.item_id)
            if session.evaluate(leaf).value is Tri.SATISFIED:
                continue
            item = content.items.get(leaf.item_id)
            price = resolve_price(item, _record(item, prices), now=now)
            charges.append(_Charge(item_id=leaf.item_id, price=price))

    return tuple(charges)


def _record(item: Item | None, prices: Mapping[int, PriceRecord]) -> PriceRecord | None:
    """The price row for an item, if it has a numeric id and one was supplied.

    An item with no ``item_id`` (``price_mode: static``, §10.5) can never appear in the
    feed, so it goes straight to the static-hint layer rather than being looked up under
    a key it does not have.
    """
    if item is None or item.item_id is None:
        return None
    return prices.get(item.item_id)


def _total_gp(training_gp: int | None, charges: tuple[_Charge, ...]) -> int | None:
    """Training cost plus acquisition cost, or ``None`` when neither exists.

    A charged item whose price resolved ``unknown`` contributes nothing to the sum and
    ``low`` to the confidence. Dropping the whole figure instead would discard the prices
    we *do* have — §8.4's answer to a partially-known cost is to qualify it, not to hide
    it, and the ``low`` badge is what the UI must render (*"visually distinguish anything
    below high"*).
    """
    parts = [training_gp, *(charge.price.gp for charge in charges)]
    known = [part for part in parts if part is not None]
    if not known:
        return None
    return sum(known)


def _selection_reason(charges: tuple[_Charge, ...]) -> str | None:
    """§8.3: *"``selection_reason`` records which layer supplied the number, so the UI can
    explain any figure it shows."* Every charged item is named, because an estimate over
    two items whose prices came from two different layers is explained by neither alone."""
    if not charges:
        return None
    return "; ".join(f"{charge.item_id}: {charge.price.selection_reason}" for charge in charges)


# ---------------------------------------------------------------------------
# Confidence (§8.4)
# ---------------------------------------------------------------------------


def _estimate_confidence(price: Confidence | None, method: Confidence | None) -> Confidence:
    """The **minimum** of the two sub-confidences (§8.4), skipping the absent ones."""
    present = [value for value in (price, method) if value is not None]
    if not present:
        return Confidence.LOW
    return min(present)


def _minimum(values: Iterable[Confidence]) -> Confidence | None:
    """``min`` over confidences, or ``None`` when there are none.

    ``None`` and ``Confidence.LOW`` are different answers and the difference is the whole
    reason this returns an optional: a candidate that buys nothing has *no* price
    confidence, and defaulting it to ``low`` would drag every pure-training estimate down
    to ``low`` through the §8.4 minimum. ``Confidence`` is an ``IntEnum`` whose ``LOW`` is
    ``0``, so the two would also be indistinguishable to any truthiness test downstream.
    """
    materialized = list(values)
    if not materialized:
        return None
    return min(materialized)
