"""Optimizer projections retain account requirements and observed ownership semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from tracker.accounts.requirements import evaluate_requirement
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.content.requirements import Requirement
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.estimation.prices import PriceRecord, resolve_price
from tracker.gear.powered import MARKET_FORMS, REVIEWS, review
from tracker.gear.ranged_resources import CONSUMABLE_WEAPON_IDS
from tracker.gear.revenant import FORMS as REVENANT_FORMS
from tracker.gear.revenant_acquisition import form_preparation, market_form, preferred_sources
from tracker.gear.salve import FORMS as SALVE_FORMS
from tracker.gear.salve import acquisition_requirement
from tracker.gear.tomes import ASSUMPTION as TOME_ASSUMPTION
from tracker.gear.tomes import review as tome_review
from tracker.gear.vampyres import ACQUISITION_REQUIREMENTS as VAMPYRE_ACQUISITION
from tracker.gear.void_ranged import ELITE_ROBES, ELITE_TOPS, ELITE_UPGRADE

# New purchases use ordinary editions; owned editions keep exact preparation routes.
_POWERED_MARKET_FORMS = MARKET_FORMS

GENERIC_UNREVIEWED = "Offensive effects have not been validated."


def budget_exempt(item: Any) -> bool:
    """Consumable ammo is a running expense, separate from gear purchases."""
    # The source catalog incorrectly labels Peaceful blessing as a bolt.
    return (item.slot == "ammunition" and bool(item.ammo_type) and item.id != 20226) or (
        item.slot == "weapon" and item.id in CONSUMABLE_WEAPON_IDS
    )


def observed_ownership(snapshot: AccountSnapshot, item_id: int) -> dict[str, Any]:
    """Concrete usable forms only; asynchronous container quantities are not added."""
    sightings = [
        fact
        for (numeric_id, container), fact in snapshot.observed_items.items()
        if numeric_id == item_id
        and fact.quantity > 0
        and (
            (scan := snapshot.container_scans.get(container)) is None
            or fact.observed_at >= scan.scanned_at
        )
    ]
    complete = set(Container) <= snapshot.container_scans.keys()
    return {
        "status": "owned" if sightings else "unowned" if complete else "unknown",
        "quantity": max((fact.quantity for fact in sightings), default=0),
        "meaning": "observed concrete usable form"
        if sightings
        else "not observed in latest accepted scans"
        if complete
        else "incomplete scan coverage",
        "sightings": [
            {
                "container": f.container.value,
                "quantity": f.quantity,
                "observed_at": f.observed_at.isoformat(),
                "source": f.source,
            }
            for f in sorted(sightings, key=lambda f: f.container.value)
        ],
        "container_scans": {
            c.value: {"scanned_at": s.scanned_at.isoformat(), "source": s.source}
            for c, s in snapshot.container_scans.items()
        },
    }


def hypothetical_snapshot(
    snapshot: AccountSnapshot, skills: Mapping[str, int], quests: Mapping[str, str], now: datetime
) -> AccountSnapshot:
    """Copy explicit request-local assumptions without touching account observations."""
    return replace(
        snapshot,
        skills={
            **snapshot.skills,
            **{key: SkillState(value, None, Source.MANUAL, now) for key, value in skills.items()},
        },
        quests={**snapshot.quests, **{key: QuestStatus(value) for key, value in quests.items()}},
    )


def equipment_fact(
    snapshot: AccountSnapshot,
    item: Any,
    content: Content,
    prices: Mapping[int, PriceRecord],
    now: datetime,
    *,
    support_assumptions: tuple[str, ...] = (),
    excluded_item_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    """No progression order or score is involved in eligibility/acquisition facts."""
    requirement = (
        evaluate_requirement(
            snapshot,
            item.requires,
            item_ids_by_key={k: v.owned_item_ids for k, v in content.items.items()},
        )
        if item.requires is not None
        else None
    )
    wear_status = requirement.status.value if requirement is not None else "satisfied"
    known_status = (
        wear_status if requirement is not None or item.requirements_complete else "unknown"
    )
    if not item.requirements_complete and not support_assumptions:
        wear_status = "unknown"
    ownership = observed_ownership(snapshot, item.id)
    planning_ownership = ownership
    preparation = None
    staff = review(item.id)
    market_id = item.id if item.tradeable else None
    if item.id in REVENANT_FORMS:
        market_id = market_form(item.id, content, prices, now, excluded_item_ids)
        source_id = None
        for candidate in preferred_sources(item.id):
            if candidate in excluded_item_ids:
                continue
            observed = (
                ownership if candidate == item.id else observed_ownership(snapshot, candidate)
            )
            if observed["status"] == "owned":
                source_id = candidate
                if candidate != item.id:
                    planning_ownership = {
                        **observed,
                        "meaning": "Owned equivalent weapon form; preparation required",
                    }
                break
        preparation = form_preparation(item.id, source_id, market_id)
    elif staff is not None and (item.id != staff.uncharged_id or item.id == staff.charged_id):
        observed_sources = [
            (i, observed_ownership(snapshot, i)) for i, record in REVIEWS.items() if record == staff
        ]
        source_id, source = next(
            ((i, fact) for i, fact in observed_sources if fact["status"] == "owned"),
            (staff.uncharged_id, ownership),
        )
        prepare_owned = ownership["status"] != "owned" and source["status"] == "owned"
        if prepare_owned:
            planning_ownership = {
                **source,
                "meaning": "Owned equivalent weapon form; actual charges unknown",
            }
        market_id = staff.uncharged_id if staff.uncharged_id in _POWERED_MARKET_FORMS else None
        charging_required = (
            source_id == staff.uncharged_id if prepare_owned else ownership["status"] != "owned"
        )
        preparation = {
            "source_item_id": source_id
            if prepare_owned
            else item.id
            if ownership["status"] == "owned"
            else None,
            "usable_item_id": item.id,
            "market_item_id": market_id,
            "charging_required": charging_required,
            "charges": "unknown",
            "activation_reserve": [{"item_id": 21820, "quantity": staff.reserve}]
            if staff.reserve
            else [],
            "message": "Charging required; actual charge availability is unknown."
            if charging_required
            else "Actual charge availability is unknown.",
        }
    tome = tome_review(item.id)
    if tome is not None and item.id == tome.charged_id:
        empty = observed_ownership(snapshot, tome.uncharged_id)
        prepare_owned = ownership["status"] != "owned" and empty["status"] == "owned"
        if prepare_owned:
            planning_ownership = {**empty, "meaning": "Owned empty tome; charged use assumed"}
        market_id = tome.uncharged_id
        preparation = {
            "source_item_id": tome.uncharged_id
            if prepare_owned
            else item.id
            if ownership["status"] == "owned"
            else None,
            "usable_item_id": item.id,
            "market_item_id": market_id,
            "charging_required": ownership["status"] != "owned",
            "charges": "unknown",
            "activation_reserve": [],
            "message": TOME_ASSUMPTION,
        }
    if item.id == 21255 and getattr(item, "slayer_staff_enchanted", False):
        base = observed_ownership(snapshot, 4170)
        prepare_owned = ownership["status"] != "owned" and base["status"] == "owned"
        if prepare_owned:
            planning_ownership = {**base, "meaning": "Owned Slayer's staff; enchanting required"}
        market_id = 4170
        preparation = {
            "source_item_id": 4170
            if prepare_owned
            else item.id
            if ownership["status"] == "owned"
            else None,
            "usable_item_id": item.id,
            "market_item_id": market_id,
            "charging_required": ownership["status"] != "owned",
            "charges": "unknown",
            "activation_reserve": [],
            "message": "Enchanting requires one Slayer's enchantment for 2,500 charges; "
            "enchantment consumption is a running expense. Actual charges unknown."
            if ownership["status"] != "owned"
            else "Actual enchantment charges unknown.",
        }
    if item.id == 23987:
        seed = observed_ownership(snapshot, 4207)
        prepare_owned = ownership["status"] != "owned" and seed["status"] == "owned"
        if prepare_owned:
            planning_ownership = {
                **seed,
                "meaning": "Owned crystal weapon seed; preparation required",
            }
        preparation = {
            "source_item_id": 4207
            if prepare_owned
            else 23987
            if ownership["status"] == "owned"
            else None,
            "usable_item_id": 23987,
            "market_item_id": None,
            "charging_required": ownership["status"] != "owned",
            "charges": "unknown",
            "activation_reserve": [],
            "message": "Crystal halberd consumes one charge per attack. "
            "Seed preparation/recharging required; actual remaining charges unknown."
            if ownership["status"] != "owned"
            else "Crystal halberd consumes one charge per attack; remaining charges unknown.",
        }
    if item.id == 12931:
        empty = observed_ownership(snapshot, 12929)
        prepare_owned = ownership["status"] != "owned" and empty["status"] == "owned"
        if prepare_owned:
            planning_ownership = {**empty, "meaning": "Owned uncharged helm; charging required"}
        market_id = 12929
        preparation = {
            "source_item_id": 12929
            if prepare_owned
            else 12931
            if ownership["status"] == "owned"
            else None,
            "usable_item_id": 12931,
            "market_item_id": 12929,
            "charging_required": ownership["status"] != "owned",
            "charges": "unknown",
            "activation_reserve": [],
            "message": "Charged serpentine helm use assumed; actual remaining scales unknown.",
        }
    authored = next((entry for entry in content.items.values() if entry.item_id == market_id), None)
    price = (
        resolve_price(authored, prices.get(market_id), now=now) if market_id is not None else None
    )
    acquisition_gate: Requirement | None = VAMPYRE_ACQUISITION.get(item.id)
    if item.id in SALVE_FORMS:
        acquisition_gate = acquisition_requirement(item.id)
    elif item.id in ELITE_TOPS or item.id in ELITE_ROBES:
        acquisition_gate = ELITE_UPGRADE
    return {
        "item_id": item.id,
        **(
            {
                "acquisition_requirement": evaluate_requirement(
                    snapshot, acquisition_gate
                ).model_dump(mode="json")
            }
            if acquisition_gate is not None and ownership["status"] != "owned"
            else {}
        ),
        "name": item.name,
        "slot": item.slot,
        "budget_exempt": budget_exempt(item),
        "support_status": "community_assumed"
        if support_assumptions
        else "verified"
        if item.requirements_complete and not item.unsupported_effects
        else "unreviewed",
        "support_assumptions": list(support_assumptions),
        "effect_status": "community_assumed"
        if support_assumptions
        else "unsupported_mechanic"
        if any(effect != GENERIC_UNREVIEWED for effect in item.unsupported_effects)
        else "generic_unreviewed"
        if item.unsupported_effects
        else "reviewed_ordinary",
        "ownership": ownership,
        "planning_ownership": planning_ownership,
        "preparation": preparation,
        "wear": {
            "status": wear_status,
            "known_status": known_status,
            "requirements_complete": item.requirements_complete,
            "requirements": requirement.model_dump(mode="json") if requirement else None,
            "unmet": [r.model_dump(mode="json") for r in requirement.unmet()]
            if requirement
            else [],
        },
        "acquisition": "tradeable"
        if market_id is not None
        else "untradeable"
        if item.tradeable is False
        else "unknown",
        "price": {
            "amount_gp": price.gp if price else None,
            "layer": price.layer.value if price else "not_tradeable",
            "selected_trade_at": price.trade_at.isoformat() if price and price.trade_at else None,
            "selection_reason": price.selection_reason if price else "not a GE purchase",
        },
        "limitations": [
            *item.unsupported_effects,
            *item.omitted_set_effects,
            *([preparation["message"]] if preparation else []),
        ],
    }
