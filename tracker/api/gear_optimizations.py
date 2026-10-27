"""Bounded single-role browser execution over frozen authoritative inputs."""

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

from tracker.api.gear_ui import DTO, GearRoute, ItemResponse, no_cache, project_equipment, resources
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
    roles: tuple[RoleConfig, ...] = Field(min_length=1, max_length=1)
    expected_snapshot_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="before")
    @classmethod
    def strict_numbers(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = data.get("skill_overrides", {})
        if isinstance(values, dict) and any(type(v) is not int for v in values.values()):
            raise ValueError("skill_overrides requires integer levels")
        roles = data.get("roles", [])
        if not isinstance(roles, list | tuple):
            return data
        for role in roles:
            if not isinstance(role, dict) or not isinstance(role.get("target"), dict):
                continue
            target = role["target"]
            values = {
                k: v
                for k, v in target.items()
                if k
                in {
                    "defence_level",
                    "magic_level",
                    "ranged_light",
                    "ranged_standard",
                    "ranged_heavy",
                    "weakness_percent",
                    "damage_cap",
                }
            }
            bonuses = target.get("bonuses", {})
            if isinstance(bonuses, dict):
                values.update(bonuses)
            if any(v is not None and type(v) is not int for v in values.values()):
                raise ValueError("target values require integers")
            if isinstance(bonuses, dict) and any(type(v) is not int for v in bonuses.values()):
                raise ValueError("target defence bonuses require integers")
            if isinstance(bonuses, dict) and any(not -64 <= v <= 10000 for v in bonuses.values()):
                raise ValueError("target defence bonuses must be between -64 and 10000")
            if any(
                target.get(k) is not None and not -64 <= target[k] <= 10000
                for k in ("ranged_light", "ranged_standard", "ranged_heavy")
            ):
                raise ValueError("target ranged defence must be between -64 and 10000")
        return data

    @model_validator(mode="after")
    def ordinary_role(self) -> BrowserOptimizationRequest:
        role = self.roles[0]
        if role.style == "special" or role.parent_role is not None:
            raise ValueError("Only one ordinary-attack combat role is supported")
        if self.transitions or self.ordered_roles or self.loop:
            raise ValueError("Multi-role transitions are unavailable")
        allowed = (
            {"accurate", "rapid", "longrange"}
            if role.style == "ranged"
            else (
                {"accurate", "defensive"}
                if role.style == "magic"
                else {"accurate", "aggressive", "controlled", "defensive"}
            )
        )
        if role.stance not in allowed:
            raise ValueError("Selected attack type and stance are incompatible")
        if role.style == "magic" and role.spell not in SPELLS:
            raise ValueError("Unknown standard spell")
        if role.target and role.target.unsupported_mechanics:
            raise ValueError("Target mechanics are unsupported for ordinary attacks")
        return self


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


class Solution(DTO):
    score: float
    loadouts: dict[str, Loadout]
    transitions: list[dict[str, Any]]
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
    locks = {**body.locks, **body.roles[0].locks}
    problems = equipment_problems({s: i for s, i in locks.items() if i is not None}, catalog.items)
    if problems:
        raise error("invalid_request", " ".join(problems), field="locks")
    role = body.roles[0]
    level = body.skill_overrides.get(
        "magic", snapshot.skills.get("magic").level if snapshot.skills.get("magic") else 0
    )
    if role.style == "magic" and level < SPELLS[role.spell][0]:
        raise error("invalid_request", "Selected spell Magic level is unmet", field="roles.0.spell")


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
