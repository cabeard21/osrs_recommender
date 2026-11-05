"""Bounded single and joint browser execution over frozen authoritative inputs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

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
from tracker.gear.potions import boosted_levels
from tracker.gear.potions import catalog as potion_catalog
from tracker.gear.priorities import SecondaryPriority
from tracker.gear.support import SupportPolicy

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
    optimization_mode: Literal["fast", "thorough"] = "fast"

    @model_validator(mode="before")
    @classmethod
    def browser_constraints(cls, data: Any) -> Any:
        return validate_browser_scenario(data)


class Baseline(DTO):
    status: Literal["available", "unavailable"]
    equipment: dict[str, int]
    performance: CombatPerformance | None
    reasons: list[str]


class WorkBudgetPolicy(DTO):
    policy: Literal["baseline-v1", "local-refinement-v1"]
    complete_assignment_limit: Literal[0, 10000]
    targeted_head_refinement: Literal[False] = False
    budget_scope: Literal["per_discipline"] = "per_discipline"
    discipline_count: int = Field(default=1, ge=1, le=3)


def work_budget_policy(body: BrowserOptimizationRequest) -> WorkBudgetPolicy:
    thorough = body.optimization_mode == "thorough"
    return WorkBudgetPolicy(
        policy="local-refinement-v1" if thorough else "baseline-v1",
        complete_assignment_limit=10000 if thorough else 0,
        discipline_count=len(body.roles[0].allowed_disciplines or ()) or 1,
    )


def frontier_policy(body: BrowserOptimizationRequest) -> dict[str, Any] | None:
    from tracker.gear.finalist_refinement import ASSIGNMENT_LIMIT

    if body.secondary_priority == "default":
        return None
    thorough = body.optimization_mode == "thorough"
    return {
        "policy": "tradeoff-frontier-v2",
        **(
            {"defensive_roll_model": "player-defence-roll-v1"}
            if body.secondary_priority.endswith("_defence_roll")
            else {}
        ),
        "metric_lane_equipment_fraction": 0.25,
        "expansion_limit": 1500000 if thorough else 500000,
        "refinement_assignment_limit": 10000 if thorough else 0,
        "finalist_assignment_limit": ASSIGNMENT_LIMIT,
    }


def scenario_fingerprint(body: BrowserOptimizationRequest) -> str:
    """Identify both requested inputs and the effective, server-owned search policy."""
    from tracker.gear.running_frontier import running_cost_policy

    return hashlib.sha256(
        json.dumps(
            {
                "scenario": body.model_dump(mode="json"),
                "potion_catalog": potion_catalog(),
                "work_budget_policy": work_budget_policy(body).model_dump(mode="json"),
                "frontier_policy": frontier_policy(body),
                "running_cost_policy": running_cost_policy(
                    body, thorough=body.optimization_mode == "thorough"
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class RunningResource(DTO):
    item_id: int
    name: str
    required_quantity: float
    consumed_quantity: float
    supplied_quantity: float
    supplied_by: str | None = None
    unit_price_gp: float | None = None
    price_layer: str
    price_confidence: str | None = None
    price_trade_at: str | None = None


class RunningCost(DTO):
    status: Literal["known", "unavailable"]
    model_version: str | None = None
    gp_per_attack: float | None
    gp_per_second: float | None = None
    gp_per_hour: float | None
    gp_per_damage: float | None
    resources: list[RunningResource]
    reasons: list[str]


class Loadout(DTO):
    selected_prayer_ids: list[str] = Field(default_factory=list)
    equipment: dict[str, int]
    performance: CombatPerformance
    combat_option: dict[str, Any] | None = None
    discipline: Literal["melee", "ranged", "magic"] | None = None
    running_cost: RunningCost | None = None


class DisciplineComparison(DTO):
    discipline: Literal["melee", "ranged", "magic"]
    status: Literal["best_found", "no_feasible_solution_found"]
    score: float | None
    purchase_cost_gp: int | None
    reasons: list[str]


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
    potions: dict[str, Any] | None = None
    score: float
    secondary_priority: SecondaryPriority
    secondary_value: float | None
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
    running_cost: RunningCost | None = None


class CurvePoint(DTO):
    swap_limit: int
    status: Literal["best_found", "no_feasible_solution_found"]
    solution: Solution | None
    relative_performance: float | None


class FrontierPoint(DTO):
    id: str
    solution: Solution
    dps_loss: float
    dps_loss_pct: float | None
    secondary_gain: float


class SecondaryFrontier(DTO):
    swap_limit: int | None
    baseline_dps: float | None
    points: list[FrontierPoint]
    sampled: bool = False


class RunningCostPoint(DTO):
    id: str
    solution: Solution
    dps_loss: float
    dps_loss_pct: float | None


class RunningCostFrontier(DTO):
    swap_limit: int | None
    baseline_dps: float | None
    baseline_solution: Solution | None = None
    points: list[RunningCostPoint]
    sampled: bool = False


class DisciplineResult(DisciplineComparison):
    selected_solution: Solution | None
    secondary_frontiers: list[SecondaryFrontier]
    search: dict[str, Any]
    alternatives: dict[str, list[dict[str, Any]]]
    limitations: list[str]
    running_cost_frontiers: list[RunningCostFrontier] = Field(default_factory=list)
    running_cost_policy: dict[str, Any] | None = None


class OptimizationResult(DTO):
    support_policy: SupportPolicy = "verified_only"
    support_provenance: str = ""
    optimization_mode: Literal["fast", "thorough"]
    secondary_priority: SecondaryPriority
    work_budget_policy: WorkBudgetPolicy
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
    secondary_frontiers: list[SecondaryFrontier] = Field(default_factory=list)
    frontier_policy: dict[str, Any] | None = None
    search: dict[str, Any]
    limitations: list[str]
    discipline_comparison: list[DisciplineComparison] = Field(default_factory=list)
    discipline_results: list[DisciplineResult] = Field(default_factory=list)
    running_cost_frontiers: list[RunningCostFrontier] = Field(default_factory=list)
    running_cost_policy: dict[str, Any] | None = None


class OptimizationResponse(DTO):
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    evaluated_at: datetime
    optimization_mode: Literal["fast", "thorough"]
    secondary_priority: SecondaryPriority
    work_budget_policy: WorkBudgetPolicy
    frontier_policy: dict[str, Any] | None = None
    running_cost_policy: dict[str, Any] | None = None
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
    from tracker.gear.npcs import resolve_target

    for index, role in enumerate(body.roles):
        try:
            resolve_target(role)
            if role.target_selection is not None and role.target is None:
                raise ValueError("NPC selection requires an explicit effective target snapshot.")
        except ValueError as exc:
            stale = "revision" in str(exc)
            raise error(
                "target_revision_changed" if stale else "invalid_target",
                str(exc),
                409 if stale else 422,
                f"roles.{index}.target_selection",
            ) from exc
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
        if body.potions.mode != "disabled":
            # Validation may use the strongest permitted setup; the search still
            # checks each fixed setup independently.
            ids = (
                body.potions.selected_ids
                if body.potions.mode == "fixed"
                else body.potions.allowed_ids
            )
            level = boosted_levels({"magic": level}, ids).get("magic", level)
        if role.style == "magic" and role.combat_options is None and level < SPELLS[role.spell][0]:
            raise error(
                "invalid_request",
                "Selected spell Magic level is unmet",
                field=f"roles.{index}.spell",
            )


def calculate(
    snapshot: Any,
    gear: Any,
    prices: Any,
    body: BrowserOptimizationRequest,
    stopped: Event,
    *,
    progress_identity: str | None = None,
) -> OptimizationResponse:
    now = datetime.now(UTC)
    if stopped.is_set():
        raise ValueError("optimization_cancelled")
    validate_scenario(body, gear, snapshot)
    result = gear.optimize(
        snapshot,
        body,
        price_records=prices,
        now=now,
        cancelled=stopped.is_set,
        **(
            {
                "progress_identity": progress_identity,
                "progress_fingerprint": scenario_fingerprint(body),
            }
            if progress_identity is not None
            else {}
        ),
        **({"local_refinement": True} if body.optimization_mode == "thorough" else {}),
    )
    policy = work_budget_policy(body)
    result = {
        **result,
        "optimization_mode": body.optimization_mode,
        "work_budget_policy": policy.model_dump(mode="json"),
        "frontier_policy": frontier_policy(body),
    }
    if stopped.is_set():
        raise ValueError("optimization_cancelled")
    projection = project_equipment(snapshot, gear)
    projected = hypothetical_snapshot(snapshot, body.skill_overrides, body.quest_overrides, now)
    baseline_body = body
    if body.potions.mode == "optimize":
        chosen_ids = (
            (result.get("selected_solution") or {}).get("potions", {}).get("selected_ids", ())
        )
        baseline_body = body.model_copy(
            update={
                "potions": body.potions.model_copy(
                    update={"mode": "fixed", "selected_ids": tuple(chosen_ids), "allowed_ids": ()}
                )
            }
        )
    reasons = list(projection.warnings)
    from tracker.gear.prayers import PrayerPolicy

    selected_loadouts = (result.get("selected_solution") or {}).get("loadouts", {})
    baseline_body = baseline_body.model_copy(
        update={
            "roles": tuple(
                role.model_copy(
                    update={
                        "prayers": PrayerPolicy(
                            mode="fixed",
                            selected_ids=tuple(
                                selected_loadouts.get(role.id, {}).get("selected_prayer_ids", ())
                            ),
                        )
                    }
                )
                if role.prayers.mode == "optimize"
                else role
                for role in baseline_body.roles
            )
        }
    )
    if projection.status != "observed" or any(
        s.status not in ("observed", "empty") for s in projection.slots.values()
    ):
        reasons.append("Complete, unambiguous equipment observations are required.")
    baseline_items = [
        gear.physical_item(
            projected, i, price_records=prices, now=now, support_policy=body.support_policy
        )
        for i in projection.equipment.values()
    ]
    for item in baseline_items:
        if item["wear"]["status"] != "satisfied":
            reasons.append(f"{item['name']}: equipment requirements are {item['wear']['status']}.")
    if len(body.roles) > 1:
        reasons.append("Observed equipment has no joint multi-role baseline evaluation.")
    performance = None
    if not reasons and body.roles[0].allowed_disciplines is not None:
        evaluated = gear.evaluate(
            snapshot,
            baseline_body,
            projection.equipment,
            projection.equipment,
            price_records=prices,
            now=now,
            cancelled=stopped.is_set,
        )["baseline"]
        if evaluated["status"] == "valid":
            performance = CombatPerformance.model_validate(evaluated["performance"])
        else:
            reasons.extend(reason["message"] for reason in evaluated["reasons"])
    elif not reasons:
        calculated = evaluate_equipment(
            projection.equipment,
            gear.supported_catalog(body.support_policy).items,
            baseline_body.roles[0],
            boosted_levels(
                {k: v.level for k, v in projected.skills.items()},
                baseline_body.potions.selected_ids,
            ),
        )
        if calculated.supported:
            performance = calculated
        else:
            reasons.extend(calculated.limitations)
    referenced = {r["item_id"] for r in result["items"]} | set(projection.equipment.values())
    for branch in [result, *result.get("discipline_results", [])]:
        for group in branch.get("running_cost_frontiers", []):
            solutions = [p["solution"] for p in group["points"]]
            if group.get("baseline_solution") is not None:
                solutions.append(group["baseline_solution"])
            referenced.update(i for solution in solutions for i in solution["carried_item_ids"])
    return OptimizationResponse(
        evaluated_at=now,
        optimization_mode=body.optimization_mode,
        secondary_priority=body.secondary_priority,
        work_budget_policy=policy,
        frontier_policy=frontier_policy(body),
        running_cost_policy=result.get("running_cost_policy"),
        scenario=body,
        scenario_fingerprint=scenario_fingerprint(body),
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
            gear.physical_item(
                projected, i, price_records=prices, now=now, support_policy=body.support_policy
            )
            for i in sorted(referenced)
        ],
    )


def consume(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


class OptimizationProgressResponse(DTO):
    progress_id: str
    progress: dict[str, Any] | None


@router.get("/optimizations/progress", response_model=OptimizationProgressResponse)
def optimization_progress(request: Request, progress_id: UUID) -> OptimizationProgressResponse:
    """Read the latest bounded service snapshot for exactly one browser attempt."""
    gear = request.app.state.gear_service
    identity = str(progress_id)
    return OptimizationProgressResponse(
        progress_id=identity, progress=gear.optimization_progress(identity)
    )


@router.post("/optimizations", response_model=OptimizationResponse)
async def optimizations(
    request: Request, body: BrowserOptimizationRequest, progress_id: UUID | None = None
) -> OptimizationResponse:
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
        asyncio.to_thread(
            calculate,
            snapshot,
            gear,
            prices,
            body,
            stopped,
            **({"progress_identity": str(progress_id)} if progress_id is not None else {}),
        )
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
        if message.startswith("optimizer_worker_"):
            raise error(
                "optimizer_worker_unavailable",
                "A desktop optimizer worker is unavailable; retry the calculation",
                503,
            ) from exc
        raise error("invalid_request", message) from exc
