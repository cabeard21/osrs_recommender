"""Before-trip acquisition and allocation of separately prepared weapon forms."""

from collections import Counter
from collections.abc import Mapping, Set
from datetime import datetime
from functools import cache
from typing import Any

from tracker.content.loader import Content
from tracker.estimation.prices import PriceRecord, resolve_price
from tracker.gear.revenant import ACTIVATION_RESERVE, ETHER_ID, FORMS


@cache
def preferred_sources(item: int) -> tuple[int, ...]:
    form = FORMS[item]
    return tuple(
        sorted(
            (i for i, f in FORMS.items() if f.market_id == form.market_id),
            key=lambda i: (
                i != item,
                (i == FORMS[i].charged_id) != (item == form.charged_id),
                FORMS[i].kind != form.kind,
                i,
            ),
        )
    )


def market_form(
    item: int,
    content: Content,
    prices: Mapping[int, PriceRecord],
    now: datetime,
    excluded: tuple[int, ...],
) -> int:
    form = FORMS[item]
    markets = {FORMS[i].uncharged_id for i in preferred_sources(item)}.difference(excluded)
    if len(markets) < 2:
        return next(iter(markets), form.market_id)

    def rank(i: int) -> tuple[float, bool, int]:
        authored = next((entry for entry in content.items.values() if entry.item_id == i), None)
        gp = resolve_price(authored, prices.get(i), now=now).gp
        return (gp if gp is not None else float("inf"), i != form.uncharged_id, i)

    return min(markets, key=rank)


def form_preparation(item: int, source_id: int | None, market: int) -> dict[str, Any]:
    form = FORMS[item]
    charged = item == form.charged_id
    start = source_id or market
    source = FORMS[start]
    source_charged = start == source.charged_id
    charging = charged and not source_charged
    steps = []
    if source.kind != form.kind:
        steps.append(
            f"Swap the sceptre to {'autocasting' if form.kind == 'autocast' else 'powered'} mode."
        )
    if charging:
        steps.append("Activate with 1,000 revenant ether, then load one ether per planned attack.")
    if source_charged and not charged:
        steps.append("Uncharge the weapon to recover its stored revenant ether.")
    if charged:
        steps.append("Actual remaining charges are unknown.")
    return {
        "source_item_id": source_id,
        "usable_item_id": item,
        "market_item_id": market,
        "charging_required": charging,
        "charges": "unknown",
        "activation_reserve": [{"item_id": ETHER_ID, "quantity": ACTIVATION_RESERVE}]
        if charging
        else [],
        "message": " ".join(steps) or "Use the uncharged form.",
    }


def joint_sources(
    ids: Set[int], facts: Mapping[int, dict[str, Any]], request: Any
) -> dict[int, int | None]:
    """Allocate one copy to each distinct ready form used by the joint loadout.

    Single-form families already have an exact projection in the item facts.
    Prefer an exact observation, then another form with the same charge state.
    """
    plans: dict[int, int | None] = {}
    selected = FORMS.keys() & ids
    if len(selected) < 2:
        return plans
    excluded = getattr(request, "excluded_item_ids", ())
    for base in {FORMS[i].market_id for i in selected}:
        ready = sorted(i for i in selected if FORMS[i].market_id == base)
        if len(ready) < 2:
            continue
        stock: Counter[int] = Counter()
        for i in preferred_sources(base):
            if i in facts and i not in excluded:
                stock[i] = facts[i]["ownership"].get("quantity", 0)
        for i in ready:
            # A fixed/timeline context may only contain selected gear in facts.
            prep = facts[i].get("preparation") or {}
            source = prep.get("source_item_id")
            if source is not None and source not in excluded:
                stock[source] = max(
                    stock[source], facts[i].get("planning_ownership", {}).get("quantity", 0)
                )
        for i in ready:
            if stock[i]:
                plans[i] = i
                stock[i] -= 1
        for i in ready:
            if i in plans:
                continue
            if request.mode != "owned" and i in request.assumed_item_ids:
                plans[i] = None
                continue
            source = next((s for s in preferred_sources(i) if stock[s]), None)
            plans[i] = source
            if source is not None:
                stock[source] -= 1
    return plans


def copies_available(
    plans: Mapping[int, int | None], facts: Mapping[int, dict[str, Any]], request: Any
) -> bool:
    return all(
        source is not None
        or (
            request.mode != "owned"
            and (
                i in request.assumed_item_ids
                or (
                    facts[i]["price"]["amount_gp"] is not None
                    and facts[i]["preparation"]["market_item_id"]
                    not in getattr(request, "excluded_item_ids", ())
                )
            )
        )
        for i, source in plans.items()
    )


def loadout_preparations(
    ids: Set[int], facts: Mapping[int, dict[str, Any]], request: Any
) -> dict[int, dict[str, Any]]:
    sources = joint_sources(ids, facts, request)
    return {
        i: form_preparation(i, sources[i], prep["market_item_id"]) if i in sources else prep
        for i in ids
        if (prep := facts[i].get("preparation"))
    }
