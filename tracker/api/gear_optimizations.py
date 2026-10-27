"""Bounded single and joint browser execution over frozen authoritative inputs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator

from tracker.api.gear_scenario_validation import validate_browser_scenario
from tracker.api.gear_ui import DTO, GearRoute, ItemResponse, no_cache, project_equipment, resources
from tracker.content.schema import ItemSlot
from tracker.gear.combat import SPELLS
from tracker.gear.evaluation import equipment_problems, evaluate_equipment
from tracker.gear.facts import hypothetical_snapshot
from tracker.gear.models import CombatPerformance
from tracker.gear.optimizer import OptimizationRequest, RoleConfig

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


def error(code: str, message: str, status: int = 422, field: str = "scenario") -> HTTPException:
    return HTTPException(
        status, {"code": code, "message": message, "fields": [{"path": field, "message": message}]}
    )


class BrowserOptimizationRequest(OptimizationRequest):
    roles: tuple[RoleConfig, ...] = Field(min_length=1, max_length=4)
    expected_snapshot_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def browser_constraints(cls, data: Any) -> Any:
        return validate_browser_scenario(data)


class Baseline(DTO):
    status: Literal["available", "unavailable"]
    equipment: dict[str, int]
    performance: CombatPerformance | None
    reasons: list[str]


class Loadout(DTO):
    equipment: dict[str, int]
    performance: CombatPerformance


class Purchase(DTO):
    item_id: int
    cost_gp: int | None
    conditional: bool


class EquipmentAction(DTO):
    operation: Literal["equip", "unequip"]
    slot: ItemSlot
    item_id: int
    automatically_removed: list[int]
    gear_inventory_slots: int


class EquipmentTransition(DTO):
    from_role: str
    to_role: str
    actions: list[EquipmentAction]
    action_count: int
    changed_slots: int
    max_gear_inventory_slots: int


class Solution(DTO):
    score: float
    loadouts: dict[str, Loadout]
    transitions: list[EquipmentTransition]
    purchase_cost_gp: int
    purchases: list[Purchase]
    carried_item_ids: list[int]
    distinct_items: int
    gear_inventory_slots: int
    max_gear_inventory_slots: int
    remaining_supply_slots: int
    remaining_inventory_slots: int
    reserved_supply_slots: int
    maximum_actions: int


class CurvePoint(DTO):
    swap_limit: int
    status: Literal["best_found", "no_feasible_solution_found"]
    solution: Solution | None
    relative_performance: float | None


class OptimizationResult(DTO):
    snapshot_id: str
    evaluated_at: datetime
    catalog_version: str
    model_version: str
    assumptions: dict[str, Any]
    assumptions_fingerprint: str
    items: list[dict[str, Any]]
    catalog_summary: dict[str, Any]
    active_time_shares: dict[str, float]
    curve: list[CurvePoint]
    unrestricted: Solution | None
    selected_solution: Solution | None
    alternatives: dict[str, list[dict[str, Any]]]
    suggested_swap_limit: int | None
    search: dict[str, Any]
    limitations: list[str]


class OptimizationResponse(DTO):
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    evaluated_at: datetime
    scenario: BrowserOptimizationRequest
    scenario_fingerprint: str
    price_revision: str
    result: OptimizationResult
    baseline: Baseline
    items: list[ItemResponse]


def same_origin(request: Request) -> None:
    """Reject cross-origin browser writes, including private-network CSRF attempts."""
    origin = request.headers.get("origin")
    expected = urlsplit(str(request.base_url))
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise error("origin_rejected", "Use the same-origin Gear application", 403)
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            raise error("origin_rejected", "Use the same-origin Gear application", 403)


def validate_scenario(body: BrowserOptimizationRequest, gear: Any, snapshot: Any) -> None:
    catalog = gear.equipment_catalog()
    for field, keys, allowed in (
        ("skill_overrides", body.skill_overrides, gear.content.skills),
        ("quest_overrides", body.quest_overrides, gear.content.quests),
    ):
        if any(k not in allowed for k in keys):
            raise error("invalid_request", f"Unknown {field} assumption", field=field)
    if any(i not in catalog.items for i in body.assumed_item_ids):
        raise error(
            "invalid_request",
            "Unknown hypothetically acquired physical item ID",
            field="assumed_item_ids",
        )
    if any(i not in catalog.items for i in body.excluded_item_ids):
        raise error(
            "invalid_request", "Unknown excluded physical item ID", field="excluded_item_ids"
        )
    for index, role in enumerate(body.roles):
        locks = {**body.locks, **role.locks}
        for slot, item_id in locks.items():
            if item_id is None:
                continue
            field = f"roles.{index}.locks.{slot}" if slot in role.locks else f"locks.{slot}"
            item = catalog.items.get(item_id)
            if item is None or item.slot != slot:
                raise error(
                    "invalid_request",
                    "Locked physical item is unknown or occupies another slot",
                    field=field,
                )
        problems = equipment_problems(
            {s: i for s, i in locks.items() if i is not None}, catalog.items
        )
        if problems:
            field = f"roles.{index}.locks.shield" if "shield" in role.locks else "locks.shield"
            raise error("invalid_request", " ".join(problems), field=field)
        level = body.skill_overrides.get(
            "magic", snapshot.skills.get("magic").level if snapshot.skills.get("magic") else 0
        )
        if role.style == "magic" and level < SPELLS[role.spell][0]:
            raise error(
                "invalid_request",
                "Selected spell Magic level is unmet",
                field=f"roles.{index}.spell",
            )


def calculate(
    snapshot: Any, gear: Any, prices: Any, body: BrowserOptimizationRequest, stopped: Event
) -> OptimizationResponse:
    now = datetime.now(UTC)
    if stopped.is_set():
        raise ValueError("optimization_cancelled")
    validate_scenario(body, gear, snapshot)
    result = gear.optimize(snapshot, body, price_records=prices, now=now, cancelled=stopped.is_set)
    if stopped.is_set():
        raise ValueError("optimization_cancelled")
    projection = project_equipment(snapshot, gear)
    projected = hypothetical_snapshot(snapshot, body.skill_overrides, body.quest_overrides, now)
    reasons = list(projection.warnings)
    if projection.status != "observed" or any(
        s.status not in ("observed", "empty") for s in projection.slots.values()
    ):
        reasons.append("Complete, unambiguous equipment observations are required.")
    baseline_items = [
        gear.physical_item(projected, i, price_records=prices, now=now)
        for i in projection.equipment.values()
    ]
    for item in baseline_items:
        if item["wear"]["status"] != "satisfied":
            reasons.append(f"{item['name']}: equipment requirements are {item['wear']['status']}.")
    if len(body.roles) > 1:
        reasons.append("Observed equipment has no joint multi-role baseline evaluation.")
    performance = None
    if not reasons:
        calculated = evaluate_equipment(
            projection.equipment,
            gear.equipment_catalog().items,
            body.roles[0],
            {k: v.level for k, v in projected.skills.items()},
        )
        if calculated.supported:
            performance = calculated
        else:
            reasons.extend(calculated.limitations)
    referenced = {r["item_id"] for r in result["items"]} | set(projection.equipment.values())
    return OptimizationResponse(
        evaluated_at=now,
        scenario=body,
        scenario_fingerprint=hashlib.sha256(
            json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        price_revision=hashlib.sha256(
            json.dumps({k: str(v) for k, v in sorted(prices.items())}, sort_keys=True).encode()
        ).hexdigest(),
        result=result,
        baseline=Baseline(
            status="available" if performance else "unavailable",
            equipment=projection.equipment,
            performance=performance,
            reasons=list(dict.fromkeys(reasons)),
        ),
        items=[
            gear.physical_item(projected, i, price_records=prices, now=now)
            for i in sorted(referenced)
        ],
    )


def consume(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


@router.post("/optimizations", response_model=OptimizationResponse)
async def optimizations(request: Request, body: BrowserOptimizationRequest) -> OptimizationResponse:
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    if snapshot is None:
        raise error("account_unavailable", "Synchronize an account before optimizing", 409)
    if snapshot.fingerprint != body.expected_snapshot_id:
        raise error(
            "snapshot_changed",
            "Account observations changed; refresh and rerun",
            409,
            "expected_snapshot_id",
        )
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(calculate, snapshot, gear, prices, body, stopped)
    )
    try:
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.05)
            if await request.is_disconnected():
                stopped.set()
                worker.add_done_callback(consume)
                raise error("optimization_cancelled", "Optimization cancelled", 499)
        result = worker.result()
        fresh, _, _ = await asyncio.to_thread(resources, request)
        if fresh is None or fresh.fingerprint != snapshot.fingerprint:
            raise error(
                "snapshot_changed",
                "Account observations changed during optimization; refresh and rerun",
                409,
                "expected_snapshot_id",
            )
        return result
    except asyncio.CancelledError:
        stopped.set()
        worker.add_done_callback(consume)
        raise
    except ValueError as exc:
        message = str(exc)
        if message.startswith("optimizer_busy"):
            raise error(
                "optimizer_busy", "Another equipment search is running; retry shortly", 503
            ) from exc
        if message.startswith("optimization_cancelled"):
            raise error("optimization_cancelled", "Optimization cancelled", 499) from exc
        raise error("invalid_request", message) from exc
