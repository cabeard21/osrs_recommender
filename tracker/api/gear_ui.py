"""Read-only browser projections within the private dashboard network boundary.

These routes deliberately do not inherit /api bearer authentication. Never expose
this application publicly; the same Settings bind policy protects NiceGUI.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from tracker.accounts.requirements import RequirementResult
from tracker.accounts.snapshot import AccountSnapshot
from tracker.api.deps import get_session_factory
from tracker.content.schema import ItemSlot
from tracker.domain.types import Container
from tracker.gear.combat import SPELLS
from tracker.gear.combat_options import enumerate_combat_options
from tracker.gear.encounters import encounter_presets
from tracker.gear.models import EquipmentDefinition
from tracker.gear.npcs import npc_catalog
from tracker.gear.optimizer import SLOTS
from tracker.gear.service import GearService
from tracker.gear.support import SupportPolicy
from tracker.ui.staleness import scan_note


def no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class GearRoute(APIRoute):
    """Keep browser errors local; /api sync keeps its existing authentication contract."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": exc.detail
                        if isinstance(exc.detail, dict)
                        else {
                            "code": "item_not_found"
                            if exc.status_code == 404
                            else "invalid_request",
                            "message": str(exc.detail),
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
            except RequestValidationError as exc:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": {
                            "code": "invalid_request",
                            "message": "Invalid Gear browser request",
                            "fields": [
                                {
                                    "path": ".".join(str(v) for v in entry["loc"] if v != "body"),
                                    "message": entry["msg"],
                                }
                                for entry in exc.errors()
                            ],
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
            except Exception:
                logging.getLogger(__name__).exception("Gear browser request failed")
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "gear_unavailable",
                            "message": "Gear account or item data unavailable",
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )

        return handle


router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlotObservation(DTO):
    status: Literal["observed", "empty", "unknown", "ambiguous"]
    item_id: int | None = None
    candidate_item_ids: list[int] = []


class EquipmentObservation(DTO):
    item_id: int
    quantity: int
    observed_at: datetime
    source: str


class EquipmentProjection(DTO):
    status: Literal["observed", "partial", "unknown"]
    scanned_at: datetime | None
    equipment: dict[str, int]
    slots: dict[str, SlotObservation]
    unmapped_item_ids: list[int]
    observations: list[EquipmentObservation]
    warnings: list[str]


class ScanFact(DTO):
    scanned_at: datetime
    source: str
    note: str | None = None


class Sighting(DTO):
    container: Container
    quantity: int
    observed_at: datetime
    source: str


class Ownership(DTO):
    status: Literal["owned", "unowned", "unknown"]
    quantity: int
    meaning: str
    sightings: list[Sighting]
    container_scans: dict[str, ScanFact]


class Wear(DTO):
    status: Literal["satisfied", "unsatisfied", "unknown"]
    known_status: Literal["satisfied", "unsatisfied", "unknown"] = "unknown"
    requirements_complete: bool
    requirements: RequirementResult | None
    unmet: list[RequirementResult]


class Price(DTO):
    amount_gp: int | None
    layer: str
    selected_trade_at: datetime | None
    selection_reason: str
    confidence: Literal["low", "medium", "high"] | None
    policy: str | None
    source: str | None
    provider: str | None
    fetched_at: datetime | None
    high_price_gp: int | None
    low_price_gp: int | None
    high_trade_at: datetime | None
    low_trade_at: datetime | None


class ItemResponse(DTO):
    item_id: int
    numeric_item_id: int
    name: str
    slot: ItemSlot
    equipment: EquipmentDefinition
    ownership: Ownership
    wear: Wear
    acquisition: Literal["tradeable", "untradeable", "unknown"]
    acquisition_descriptions: list[str]
    price: Price
    limitations: list[str]
    catalog_version: str
    support_status: Literal["verified", "community_assumed", "unreviewed"] = "unreviewed"
    support_assumptions: list[str] = []
    effect_status: Literal[
        "community_assumed", "unsupported_mechanic", "generic_unreviewed", "reviewed_ordinary"
    ] = "generic_unreviewed"


class ContextResponse(DTO):
    data_source: dict[str, str] | None = None
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    evaluated_at: datetime
    account: dict[str, Any] | None
    container_scans: dict[str, ScanFact | None]
    current_equipment: EquipmentProjection
    items: list[ItemResponse]
    capabilities: dict[str, Any]
    catalog_version: str
    model_version: str
    price_revision: str


class ItemsResponse(DTO):
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    snapshot_id: str | None
    catalog_version: str
    items: list[ItemResponse]
    total: int
    offset: int
    limit: int
    next_offset: int | None


def project_equipment(snapshot: AccountSnapshot | None, gear: GearService) -> EquipmentProjection:
    scan = snapshot.container_scans.get(Container.EQUIPMENT) if snapshot else None
    candidates: dict[str, list[int]] = {slot: [] for slot in SLOTS}
    unmapped = []
    observations = []
    invalid_quantities: set[str] = set()
    catalog = gear.equipment_catalog()
    if snapshot:
        for (item_id, container), fact in snapshot.observed_items.items():
            if container != Container.EQUIPMENT:
                continue
            if scan and fact.observed_at < scan.scanned_at:
                continue
            observations.append(
                EquipmentObservation(
                    item_id=item_id,
                    quantity=fact.quantity,
                    observed_at=fact.observed_at,
                    source=fact.source,
                )
            )
            if fact.quantity <= 0:
                continue
            item = catalog.items.get(item_id)
            if item is None:
                unmapped.append(item_id)
            else:
                candidates[item.slot].append(item_id)
                if fact.quantity > 1 and not item.stackable:
                    invalid_quantities.add(item.slot)
    warnings = []
    if scan is None:
        warnings.append("No equipment scan; missing observations do not mean empty slots.")
    if unmapped:
        warnings.append("Unmapped equipped items may occupy any unresolved slot.")
    slots = {}
    for slot, ids in candidates.items():
        ids.sort()
        status = (
            "observed"
            if len(ids) == 1
            else "ambiguous"
            if ids
            else ("empty" if scan and not unmapped else "unknown")
        )
        slots[slot] = SlotObservation(
            status=status, item_id=ids[0] if len(ids) == 1 else None, candidate_item_ids=ids
        )
    for slot in invalid_quantities:
        slots[slot] = SlotObservation(status="ambiguous", candidate_item_ids=candidates[slot])
    # Two individually unique slots can still describe an impossible observation.
    weapon = slots["weapon"].item_id
    if weapon and catalog.items[weapon].two_handed and candidates["shield"]:
        for slot in ("weapon", "shield"):
            slots[slot] = SlotObservation(status="ambiguous", candidate_item_ids=candidates[slot])
        warnings.append("Two-handed weapon and offhand observations conflict.")
    if any(s.status == "ambiguous" for s in slots.values()):
        warnings.append("Conflicting items cannot be assigned to equipment slots.")
    status = "unknown" if not scan else "partial" if unmapped or warnings else "observed"
    return EquipmentProjection(
        status=status,
        scanned_at=scan.scanned_at if scan else None,
        equipment={s: f.item_id for s, f in slots.items() if f.item_id is not None},
        slots=slots,
        unmapped_item_ids=sorted(unmapped),
        observations=sorted(observations, key=lambda f: f.item_id),
        warnings=warnings,
    )


def resources(request: Request):
    source = getattr(request.app.state, "gear_data_source", None)
    if source is not None:
        snapshot, prices = source.load()
        return snapshot, request.app.state.gear_service, prices
    from tracker.gear.data_source import LocalGearDataSource

    snapshot, prices = LocalGearDataSource(get_session_factory(request)).load()
    return snapshot, request.app.state.gear_service, prices


def combat_option_capabilities(
    snapshot: AccountSnapshot | None, gear: GearService
) -> dict[str, Any]:
    """Account-facing controls; weapon pairing remains checked during optimization."""
    account = snapshot or AccountSnapshot(0, "")
    levels = {key: state.level for key, state in account.skills.items()}
    powered_longrange = any(
        weapon.powered_attack
        and weapon.powered_attack_base_max_hit
        and "longrange" in weapon.powered_attack_stances
        for weapon in gear.equipment_catalog().items.values()
    )
    attack_types: list[dict[str, Any]] = []
    stances: list[dict[str, Any]] = []
    for category, names, skill in (
        ("melee", ("stab", "slash", "crush"), "attack"),
        ("ranged", ("light", "standard", "heavy"), "ranged"),
        ("magic", ("magic",), "magic"),
    ):
        known = skill in levels and levels[skill] >= 1
        attack_types.extend(
            {
                "id": name,
                "category": category,
                "available": known,
                "reason": None if known else f"{skill.title()} level is unknown",
            }
            for name in names
        )
        for stance in (
            ("accurate", "aggressive", "defensive", "controlled")
            if category == "melee"
            else ("accurate", "rapid", "longrange")
            if category == "ranged"
            else ("accurate", "defensive", "longrange")
        ):
            longrange_missing = (
                category == "magic" and stance == "longrange" and not powered_longrange
            )
            stance_available = known and not longrange_missing
            stance_reason = (
                None
                if stance_available
                else "No reviewed powered staff supports longrange"
                if longrange_missing and known
                else f"{skill.title()} level is unknown"
            )
            stances.append(
                {
                    "id": stance,
                    "category": category,
                    "available": stance_available,
                    "reason": stance_reason,
                }
            )
    spells: list[dict[str, Any]] = []
    for option in enumerate_combat_options(None, account, discipline="magic", levels=levels):
        if option.spell is None:
            continue
        spells.append(
            {
                "id": option.spell,
                "level": SPELLS[option.spell][0],
                "available": option.available,
                "reason": option.reason,
            }
        )
    for weapon in gear.equipment_catalog().items.values():
        if (
            not weapon.powered_attack
            or not weapon.powered_attack_base_max_hit
            or not weapon.powered_attack_stances
        ):
            continue
        options = enumerate_combat_options(weapon, account, discipline="magic", levels=levels)
        powered_option = next(
            (row for row in options if row.powered_attack == weapon.powered_attack), None
        )
        if powered_option is not None:
            spells.append(
                {
                    "id": f"powered:{weapon.id}",
                    "level": 1,
                    "available": powered_option.available,
                    "reason": powered_option.reason,
                }
            )
    return {"attack_types": attack_types, "stances": stances, "spells": spells}


@router.get("/context", response_model=ContextResponse)
def context(request: Request) -> ContextResponse:
    snapshot, gear, prices = resources(request)
    now = datetime.now(UTC)
    projection = project_equipment(snapshot, gear)

    return ContextResponse(
        evaluated_at=now,
        data_source={"label": "Homelab Pi", "fetched_at": now.isoformat()}
        if getattr(request.app.state, "gear_data_source", None) is not None
        else None,
        account={**snapshot.summary(), "snapshot_id": snapshot.fingerprint} if snapshot else None,
        container_scans={
            c.value: {
                "scanned_at": s.scanned_at.isoformat(),
                "source": s.source,
                "note": scan_note(c, s.scanned_at, now),
            }
            if snapshot and (s := snapshot.container_scans.get(c))
            else None
            for c in Container
        },
        current_equipment=projection,
        items=[
            gear.physical_item(snapshot, i, price_records=prices, now=now)
            for i in sorted({i for s in projection.slots.values() for i in s.candidate_item_ids})
        ],
        capabilities={
            "objectives": [
                {
                    "id": "weighted_dps",
                    "available": True,
                    "reason": "Single-style ordinary-attack DPS optimization",
                }
            ],
            "access_modes": ["owned", "usable", "future"],
            "max_roles": 4,
            "max_equipment_actions": 12,
            "slots": list(SLOTS),
            "spells": [{"id": k, "level": v[0], "base_max_hit": v[1]} for k, v in SPELLS.items()],
            "combat_options": combat_option_capabilities(snapshot, gear),
            "encounter_presets": [p.__dict__ for p in encounter_presets()],
            "npc_catalog": {"available": True, "catalog_revision": npc_catalog().revision},
            "configurations": ["melee", "ranged", "magic"],
        },
        catalog_version=gear.equipment_catalog().revision,
        model_version="normal-attacks-v1",
        price_revision=hashlib.sha256(
            json.dumps({k: str(v) for k, v in sorted(prices.items())}, sort_keys=True).encode()
        ).hexdigest(),
    )


@router.get("/items", response_model=ItemsResponse)
def items(
    request: Request,
    q: str = Query("", max_length=200),
    slot: str | None = None,
    style: str | None = None,
    ownership: str | None = None,
    wear_status: str | None = None,
    acquisition: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    support_policy: SupportPolicy = "verified_only",
) -> ItemsResponse:
    snapshot, gear, prices = resources(request)
    try:
        page = gear.optimizer_catalog(
            snapshot or AccountSnapshot(0, ""),
            style=style,
            slot=slot,
            ownership=ownership,
            wear_status=wear_status,
            acquisition=acquisition,
            query=q,
            offset=offset,
            limit=limit,
            price_records=prices,
            support_policy=support_policy,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return ItemsResponse(
        snapshot_id=snapshot.fingerprint if snapshot else None,
        catalog_version=page["catalog_version"],
        total=page["total"],
        offset=offset,
        limit=limit,
        next_offset=page["next_offset"],
        items=[
            gear.physical_item(
                snapshot, row["item_id"], price_records=prices, support_policy=support_policy
            )
            for row in page["items"]
        ],
    )


@router.get("/items/{item_id}", response_model=ItemResponse)
def item(
    request: Request, item_id: int, support_policy: SupportPolicy = "verified_only"
) -> dict[str, Any]:
    snapshot, gear, prices = resources(request)
    try:
        return gear.physical_item(
            snapshot, item_id, price_records=prices, support_policy=support_policy
        )
    except KeyError as exc:
        raise HTTPException(404, "Physical item metadata unavailable") from exc


@router.get("/targets")
def search_targets(
    q: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return npc_catalog().search(q, offset, limit)


@router.get("/targets/{key}")
def target_detail(key: str) -> dict[str, Any]:
    try:
        return npc_catalog().detail(key)
    except ValueError as exc:
        raise HTTPException(404, {"code": "target_not_found", "message": str(exc)}) from exc
