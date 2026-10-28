"""Deterministic read-only equipment coverage and candidate-retention diagnostics.

Access eligibility, combat-model support and pool retention are separate stages.
No final-loadout membership is used as evidence, and no search policy is changed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.estimation.prices import PriceRecord
from tracker.gear.catalog import REVIEWED_EQUIVALENT_FORMS, EquipmentCatalog
from tracker.gear.evaluation import equipment_problems, item_problems, validate_request_context
from tracker.gear.facts import equipment_fact, hypothetical_snapshot, observed_ownership
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search


@dataclass(frozen=True)
class _AuditPrice:
    item_id: int
    high_price_gp: int | None
    high_trade_at: datetime | None
    low_price_gp: int | None
    low_trade_at: datetime | None
    fetched_at: datetime
    source: str
    provider: str


def default_requests() -> tuple[OptimizationRequest, ...]:
    """Five independent owned-only ordinary attacks, never a five-role request."""
    return tuple(
        OptimizationRequest(roles=(RoleConfig(id=style, style=style),), mode="owned")
        for style in ("stab", "slash", "crush", "ranged", "magic")
    )


def as_of_prices(prices: Mapping[int, PriceRecord], at: datetime) -> dict[int, _AuditPrice]:
    """Retain only facts available at evaluation time; never reconstruct history."""
    return {
        i: _AuditPrice(
            i,
            p.high_price_gp if p.high_trade_at is None or p.high_trade_at <= at else None,
            p.high_trade_at if p.high_trade_at is None or p.high_trade_at <= at else None,
            p.low_price_gp if p.low_trade_at is None or p.low_trade_at <= at else None,
            p.low_trade_at if p.low_trade_at is None or p.low_trade_at <= at else None,
            p.fetched_at,
            p.source,
            getattr(p, "provider", "unknown"),
        )
        for i, p in sorted(prices.items())
        if p.fetched_at <= at
    }


def _pricing(
    item_id: int,
    fact: dict[str, Any],
    current: dict[str, Any],
    prices: Mapping[int, PriceRecord],
    at: datetime,
) -> dict[str, Any]:
    record = prices.get(item_id)
    dates = {
        "fetched": record.fetched_at if record else None,
        "high_trade": record.high_trade_at if record else None,
        "low_trade": record.low_trade_at if record else None,
    }
    return {
        "as_of": fact["price"],
        "current_cache": current["price"],
        "required_for_observed_item": fact["ownership"]["status"] != "owned",
        "flags": [f"{k}_after_evaluation" for k, v in dates.items() if v and v > at],
        "cached_timestamps": {k: v.isoformat() if v else None for k, v in dates.items()},
        "hint_policy": "Current authored hints are labeled hints, not historical market evidence.",
    }


def _observations(snapshot: AccountSnapshot, item_id: int) -> list[dict[str, Any]]:
    result = []
    for (numeric_id, container), sighting in sorted(
        snapshot.observed_items.items(), key=lambda pair: (pair[0][0], pair[0][1].value)
    ):
        if numeric_id != item_id or sighting.quantity <= 0:
            continue
        scan = snapshot.container_scans.get(container)
        result.append(
            {
                "container": container.value,
                "quantity": sighting.quantity,
                "observed_at": sighting.observed_at.isoformat(),
                "source": sighting.source,
                "scanned_at": scan.scanned_at.isoformat() if scan else None,
                "scan_status": "missing_scan"
                if scan is None
                else "accepted"
                if sighting.observed_at >= scan.scanned_at
                else "stale",
            }
        )
    return result


def _variants(item_id: int, item: EquipmentDefinition | None, content: Content) -> dict[str, Any]:
    memberships = sorted(
        entry.id for entry in content.items.values() if item_id in entry.variant_item_ids
    )
    ambiguous = bool(item and "Ambiguous source equipment variant." in item.unsupported_effects)
    reviewed = REVIEWED_EQUIVALENT_FORMS.get(item_id)
    return {
        "authored_variant_memberships": memberships,
        "reviewed_primary_id": reviewed,
        "ambiguous_source_variant": ambiguous,
        "review_needed": ambiguous
        or bool(
            memberships
            and reviewed is None
            and (item is None or not item.requirements_complete or item.unsupported_effects)
        ),
        "identity_policy": "Concrete IDs, ownership and prices remain distinct.",
    }


def _identity(item_id: int, item: EquipmentDefinition | None, content: Content) -> dict[str, Any]:
    entries = sorted(
        (entry for entry in content.items.values() if entry.item_id == item_id),
        key=lambda entry: entry.id,
    )
    authored = entries[0] if len(entries) == 1 else None
    return {
        "name": item.name
        if item
        else authored.name
        if authored
        else f"Unknown physical item {item_id}",
        "canonical_name_source": (
            "physical_catalog" if item else "authored_exact_id" if authored else "unknown"
        ),
        "authored_slot": authored.slot if authored else None,
        "authored_identity_ambiguous": len(entries) > 1,
        "authored_exact_matches": [
            {"content_id": entry.id, "name": entry.name, "slot": entry.slot} for entry in entries
        ],
        "compatibility_metadata": {
            "attack_styles": list(item.attack_styles),
            "attack_profiles": [list(profile) for profile in item.attack_profiles],
            "two_handed": item.two_handed,
            "ammo_type": item.ammo_type,
            "ammo_for": list(item.ammo_for),
        }
        if item
        else None,
    }


def _unmapped_roles(request: OptimizationRequest, scenario_id: str) -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": scenario_id,
            "role_id": role.id,
            "access_eligible": None,
            "access_problems": [],
            "access_primary_blocker": "missing_physical_catalog",
            "role_support": "unavailable",
            "role_limitations": ["Physical metadata is unavailable."],
            "scenario_problems": [],
            "initial_eligible": None,
            "candidate_retention": "not_measured",
            "marginal_dps": None,
            "later_search": "not_measured",
            "scenario_validation": "Physical metadata is unavailable.",
        }
        for role in request.roles
    ]


def _scenario_restrictions(
    item: EquipmentDefinition, role: RoleConfig, search: _Search
) -> list[str]:
    locks = {**search.request.locks, **role.locks}
    reasons = []
    if item.slot in locks and locks[item.slot] != item.id:
        reasons.append(f"The {item.slot} slot is locked to another item or empty.")
    locked_equipment: dict[str, int] = {s: i for s, i in locks.items() if i is not None}
    reasons.extend(equipment_problems({**locked_equipment, item.slot: item.id}, search.items))
    if item.id in search.eligible and search.cost({item.id}) > search.request.budget_gp:
        reasons.append("Individual acquisition cost exceeds the scenario budget.")
    return list(dict.fromkeys(reasons))


def _access_category(item_id: int, fact: dict[str, Any], search: _Search) -> str:
    """Mirror category names only; the authoritative gate supplies the result/reason."""
    if item_id in search.request.excluded_item_ids:
        return "scenario_restriction"
    if not fact["wear"]["requirements_complete"]:
        return "incomplete_requirements"
    if fact["wear"]["status"] != "satisfied":
        return f"{fact['wear']['status'].replace('unsatisfied', 'unmet')}_requirements"
    if search.request.mode == "owned":
        return "ownership_not_observed"
    if fact["acquisition"] != "tradeable":
        return "unsupported_acquisition"
    return "missing_purchase_price"


def _locked_scaffold_support(
    item: EquipmentDefinition, role: RoleConfig, search: _Search, bases: list[dict[str, int]]
) -> bool:
    locks: dict[str, int | None] = {
        str(slot): i for slot, i in {**search.request.locks, **role.locks}.items()
    }
    for base in bases:
        equipment = {
            slot: i for slot, i in {**base, **locks, item.slot: item.id}.items() if i is not None
        }
        if any(i not in search.eligible for i in equipment.values()):
            continue
        if (
            not equipment_problems(equipment, search.items)
            and search.performance(equipment, role)["supported"]
        ):
            return True
    return False


def _role_result(
    item: EquipmentDefinition,
    fact: dict[str, Any],
    role: RoleConfig,
    search: _Search,
    scenario_id: str,
    bases: list[dict[str, int]],
) -> dict[str, Any]:
    access = list(item_problems(item.id, fact, search.request))
    evaluations = [
        search.performance({**base, item.slot: item.id}, role)
        for base in bases
        if search.compatible({**base, item.slot: item.id})
    ]
    supported = any(p["supported"] for p in evaluations)
    effects = list(item.unsupported_effects)
    limitations = sorted(
        set(
            effects
            + [reason for p in evaluations if not p["supported"] for reason in p["limitations"]]
        )
    )
    if role.style == "special":
        support = "unavailable"
        limitations = ["Special utility role is unscored; no damage benefit is modeled."]
    else:
        support = "supported" if supported else "unsupported" if effects or bases else "unavailable"
        if not bases:
            limitations.append(
                "No supported weapon/ammunition scaffold is available for this role."
            )
    restrictions = _scenario_restrictions(item, role, search)
    if supported and not access and not _locked_scaffold_support(item, role, search, bases):
        restrictions.append(
            "No supported scaffold satisfies configured locks/hand/ammunition constraints."
        )
    retained = item.id in search.pools[item.slot]
    return {
        "scenario_id": scenario_id,
        "role_id": role.id,
        "access_eligible": not access,
        "access_problems": access,
        "access_primary_blocker": _access_category(item.id, fact, search) if access else "none",
        "role_support": support,
        "role_limitations": limitations,
        "scenario_problems": restrictions,
        "initial_eligible": not access and support == "supported" and not restrictions,
        "candidate_retention": "not_eligible" if access else "retained" if retained else "omitted",
        "marginal_dps": search.marginals.get((role.id, item.id)),
        "later_search": "not_measured",
        "scenario_validation": (
            "Item restrictions and supported scaffolds only; complete loadout not measured."
        ),
    }


def _primary(row: dict[str, Any]) -> str:
    fact = row["fact"]
    if row["classification"] == "unclassified":
        return "unclassified_observation"
    if fact is None:
        return "missing_physical_catalog"
    roles = row["scenario_results"]
    if roles and all(r["access_problems"] for r in roles):
        return str(roles[0]["access_primary_blocker"])
    if not fact["wear"]["requirements_complete"]:
        return "incomplete_requirements"
    if fact["wear"]["status"] != "satisfied":
        return f"{fact['wear']['status'].replace('unsatisfied', 'unmet')}_requirements"
    if fact["limitations"]:
        return "unsupported_effects"
    eligible = [r for r in roles if r["initial_eligible"]]
    if eligible:
        return (
            "none"
            if any(r["candidate_retention"] == "retained" for r in eligible)
            else "candidate_retention"
        )
    if any(r["access_problems"] or r["scenario_problems"] for r in roles):
        return "scenario_restriction"
    return "role_support_unavailable"


def _catalog_summary(
    items: Mapping[int, EquipmentDefinition],
    facts: Mapping[int, dict[str, Any]],
) -> dict[str, Any]:
    gaps = sorted(
        i
        for i, f in facts.items()
        if f["acquisition"] == "tradeable" and f["price"]["amount_gp"] is None
    )
    return {
        "physical_items": len(items),
        "requirements_complete": sum(i.requirements_complete for i in items.values()),
        "effects_clear": sum(not i.unsupported_effects for i in items.values()),
        "requirements_complete_and_effects_clear": sum(
            i.requirements_complete and not i.unsupported_effects for i in items.values()
        ),
        "incomplete_requirements": sum(not i.requirements_complete for i in items.values()),
        "effect_review_or_model_limitations": sum(
            bool(i.unsupported_effects) for i in items.values()
        ),
        "missing_tradeable_prices": len(gaps),
        "missing_tradeable_price_ids": gaps,
        "pricing_affects_acquisition_ids": [
            i for i in gaps if facts[i]["ownership"]["status"] != "owned"
        ],
        "acquisition_unknown": sum(i.tradeable is None for i in items.values()),
    }


def _account_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in rows if r["accepted_observation"]]
    equipment = [r for r in accepted if r["classification"] == "equipment"]
    known = [r for r in equipment if r["fact"] is not None]
    return {
        "positive_observed_ids": len(rows),
        "accepted_observed_ids": len(accepted),
        "confirmed_equipment_ids": len(equipment),
        "catalog_equipment_ids": len(known),
        "unclassified_ids": sum(r["classification"] == "unclassified" for r in accepted),
        "missing_scan_ids": sum(
            any(o["scan_status"] == "missing_scan" for o in r["observations"]) for r in rows
        ),
        "stale_observation_ids": sum(
            any(o["scan_status"] == "stale" for o in r["observations"]) for r in rows
        ),
        "fully_supported": sum(r["fully_supported"] for r in equipment),
        "incomplete_requirements": sum(
            not r["fact"]["wear"]["requirements_complete"] for r in known
        ),
        "effect_review_or_model_limitations": sum(bool(r["fact"]["limitations"]) for r in known),
        "physical_variants_requiring_review": sum(
            r["variant_review"]["review_needed"] for r in equipment
        ),
        "valid_items_excluded_by_scenario": sum(
            any(
                s["role_support"] == "supported"
                and (s["scenario_problems"] or s["access_problems"])
                for s in r["scenario_results"]
            )
            and r["fact"]["wear"]["status"] == "satisfied"
            and not r["fact"]["limitations"]
            for r in known
        ),
        "eligible_items_omitted_during_retention": sum(
            any(
                s["initial_eligible"] and s["candidate_retention"] == "omitted"
                for s in r["scenario_results"]
            )
            for r in known
        ),
        "primary_blockers": dict(sorted(Counter(r["primary_blocker"] for r in equipment).items())),
    }


def audit_snapshot(
    snapshot: AccountSnapshot,
    content: Content,
    catalog: EquipmentCatalog,
    prices: Mapping[int, PriceRecord],
    at: datetime,
    requests: Sequence[OptimizationRequest] | None = None,
) -> dict[str, Any]:
    """Audit immutable input facts, using actual eligibility and candidate construction."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Evaluation time must include a timezone")
    definitions = dict(sorted(catalog.items.items()))
    historical = as_of_prices(prices, at)
    facts = {
        i: equipment_fact(snapshot, item, content, historical, at)
        for i, item in definitions.items()
    }
    rows = []
    for item_id in sorted({i for (i, _), f in snapshot.observed_items.items() if f.quantity > 0}):
        item = definitions.get(item_id)
        observations = _observations(snapshot, item_id)
        identity = _identity(item_id, item, content)
        classification = (
            "equipment"
            if item
            or any(entry["slot"] is not None for entry in identity["authored_exact_matches"])
            or any(o["container"] == "equipment" for o in observations)
            else "unclassified"
        )
        fact = facts.get(item_id)
        row: dict[str, Any] = {
            "item_id": item_id,
            **identity,
            "catalog_present": item is not None,
            "classification": classification,
            "observations": observations,
            "accepted_observation": any(o["scan_status"] == "accepted" for o in observations),
            "slot": item.slot if item else None,
            "fact": fact,
            "ownership": fact["ownership"] if fact else observed_ownership(snapshot, item_id),
            "variant_review": _variants(item_id, item, content),
            "scenario_results": [],
            "pricing": _pricing(
                item_id, fact, equipment_fact(snapshot, item, content, prices, at), prices, at
            )
            if item and fact
            else None,
        }
        rows.append(row)
    scenarios = []
    for number, request in enumerate(default_requests() if requests is None else requests, 1):
        validate_request_context(request, snapshot, definitions, content)
        projected = hypothetical_snapshot(
            snapshot, request.skill_overrides, request.quest_overrides, at
        )
        projected_facts = {
            i: equipment_fact(projected, item, content, historical, at)
            for i, item in definitions.items()
        }
        search = _Search(projected, request, definitions, projected_facts, None)
        scenario_id = f"scenario_{number}"
        bases = {role.id: search.baselines(role) for role in request.roles}
        for row in rows:
            if row["item_id"] in definitions:
                row["scenario_results"].extend(
                    _role_result(
                        definitions[row["item_id"]],
                        projected_facts[row["item_id"]],
                        role,
                        search,
                        scenario_id,
                        bases[role.id],
                    )
                    for role in request.roles
                )
            elif row["classification"] == "equipment":
                row["scenario_results"].extend(_unmapped_roles(request, scenario_id))
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "request": request.model_dump(mode="json"),
                "pools": search.pools,
                "candidate_truncation": search.truncated,
                "access_eligible_items": len(search.eligible),
                "role_scaffold_counts": {k: len(v) for k, v in sorted(bases.items())},
            }
        )
    for row in rows:
        row["fully_supported"] = bool(
            row["fact"]
            and row["fact"]["wear"]["status"] == "satisfied"
            and not row["fact"]["limitations"]
            and any(s["initial_eligible"] for s in row["scenario_results"])
        )
        row["primary_blocker"] = _primary(row)
        row["secondary_limitations"] = sorted(
            set(
                (
                    ["Observation lacks an accepted full-container scan."]
                    if not row["accepted_observation"]
                    else []
                )
                + (
                    row["fact"]["limitations"]
                    if row["fact"]
                    else ["Physical metadata is unavailable."]
                )
                + (
                    ["Incomplete requirement metadata."]
                    if row["fact"] and not row["fact"]["wear"]["requirements_complete"]
                    else []
                )
                + [
                    reason
                    for s in row["scenario_results"]
                    for reason in [
                        *s["access_problems"],
                        *s["role_limitations"],
                        *s["scenario_problems"],
                    ]
                ]
            )
        )
    return {
        "evaluated_at": at.isoformat(),
        "snapshot_id": snapshot.fingerprint,
        "catalog_revision": catalog.revision,
        "catalog_summary": _catalog_summary(definitions, facts),
        "current_account_summary": _account_summary(rows),
        "items": rows,
        "scenarios": scenarios,
        "price_policy": (
            "As-of facts only; raw current-cache diagnostic is separate. "
            "Authored hints are current."
        ),
        "variant_review_policy": (
            "Review-needed counts cover only authored variant memberships and explicit source "
            "ambiguity. Zero does not establish that other unreviewed physical forms are absent."
        ),
    }
