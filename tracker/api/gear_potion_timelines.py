"""Bounded read-only potion decay measurements for selected configurations."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator

from tracker.api.gear_evaluations import FixedCombatOption
from tracker.api.gear_optimizations import (
    BrowserOptimizationRequest,
    ObjectiveProjection,
    consume,
    error,
    same_origin,
    validate_scenario,
)
from tracker.api.gear_ui import DTO, GearRoute, no_cache, resources
from tracker.content.schema import ItemSlot
from tracker.gear.combat import MODEL_VERSION
from tracker.gear.optimizer import ItemId
from tracker.gear.potions import PotionPolicy
from tracker.gear.prayers import PrayerPolicy

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class UtilityTimelineLoadout(DTO):
    equipment: dict[ItemSlot, ItemId]


class TimelineLoadout(UtilityTimelineLoadout):
    combat_option: FixedCombatOption
    selected_prayer_ids: tuple[str, ...] = ()


class PotionTimelineRequest(DTO):
    scenario: BrowserOptimizationRequest
    selected_potion_ids: tuple[str, ...] = Field(max_length=16)
    loadouts: dict[str, TimelineLoadout | UtilityTimelineLoadout]
    expected_catalog_version: str = Field(min_length=1, max_length=128)
    expected_model_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def fixed_selection(self):
        PotionPolicy(mode="fixed", selected_ids=self.selected_potion_ids)
        policy = self.scenario.potions
        if policy.mode == "optimize":
            if not set(self.selected_potion_ids) <= set(policy.allowed_ids):
                raise ValueError("Selected potions must belong to the scenario allowlist")
        elif set(self.selected_potion_ids) != set(policy.selected_ids):
            raise ValueError("Selected potions must match the scenario setup")
        ordinary = {r.id for r in self.scenario.roles if r.style != "special"}
        risk = any(o.kind == "wilderness_loss_gp" for o in self.scenario.objectives or ())
        if risk and set(self.loadouts) != {r.id for r in self.scenario.roles}:
            raise ValueError("Risk previews require every loadout, including utility switches")
        if not risk and set(self.loadouts) != ordinary:
            raise ValueError("Loadouts must contain exactly the scored ordinary roles")
        for role in self.scenario.roles:
            if role.id not in ordinary:
                if role.id in self.loadouts and isinstance(self.loadouts[role.id], TimelineLoadout):
                    raise ValueError("Provide only equipment for utility switches")
                continue
            row = self.loadouts[role.id]
            if not isinstance(row, TimelineLoadout):
                raise ValueError("Provide a concrete combat option for each scored role")
            ids = row.selected_prayer_ids
            PrayerPolicy(mode="fixed", selected_ids=ids)
            if role.prayers.mode == "optimize":
                if not set(ids) <= set(role.prayers.allowed_ids):
                    raise ValueError("Selected prayers must belong to the scenario allowlist")
            elif set(ids) != set(role.prayers.selected_ids):
                raise ValueError("Selected prayers must match the scenario setup")
        return self


class FrozenPotionTimelineRequest(DTO):
    run_id: UUID
    solution_id: str = Field(min_length=1, max_length=160)


def frozen_timeline_inputs(body: FrozenPotionTimelineRequest, snapshot, gear):
    """Resolve an owner-scoped archived selection without rereading live scoring facts."""
    identity = str(snapshot.player_id)
    run_id = str(body.run_id)
    from tracker.gear.objective_store import RunUnavailable

    try:
        metadata = gear.objective_store.metadata(run_id, player_id=identity)
        context = gear.objective_store.get_context(run_id, player_id=identity)
        solution = gear.objective_store.solution(run_id, body.solution_id, player_id=identity)[
            "solution"
        ]
    except RunUnavailable as exc:
        raise error("optimization_run_unavailable", str(exc), 410) from exc
    if not context:
        raise error("run_expired", "Results expired; rerun optimization", 410)
    scenario = BrowserOptimizationRequest.model_validate(metadata["scenario"])
    special = {role.id for role in scenario.roles if role.style == "special"}
    include_risk = any(o.kind == "wilderness_loss_gp" for o in scenario.objectives or ())
    fixed = PotionTimelineRequest(
        scenario=scenario,
        selected_potion_ids=(solution.get("potions") or {}).get("selected_ids", ()),
        loadouts={
            key: {"equipment": row["equipment"]}
            if key in special
            else {
                "equipment": row["equipment"],
                "combat_option": row["combat_option"],
                "selected_prayer_ids": row.get("selected_prayer_ids", ()),
            }
            for key, row in solution["loadouts"].items()
            if include_risk or key not in special
        },
        expected_catalog_version=metadata["catalog_version"]
        if "catalog_version" in metadata
        else context["catalog"].revision,
        expected_model_version=metadata["model_version"],
    )
    frozen_gear = SimpleNamespace(
        _optimization_lock=gear._optimization_lock,
        equipment_catalog=lambda: context["catalog"],
        content=context["content"],
    )
    return (
        context["snapshot"],
        frozen_gear,
        context["prices"],
        fixed,
        context["evaluated_at"],
        (solution.get("wilderness_risk") or {}).get("loss_gp"),
    )


class RoleMeasurement(ObjectiveProjection):
    objective_values: dict[str, int | float | None] = Field(default_factory=dict)
    dps: float | None
    secondary_value: float | None
    reasons: list[str]


class TimelineMeasurement(ObjectiveProjection):
    objective_values: dict[str, int | float | None] = Field(default_factory=dict)
    time_seconds: int
    levels: dict[str, int]
    dps: float | None
    secondary_value: float | None
    roles: dict[str, RoleMeasurement]


class PotionTimelineResponse(ObjectiveProjection):
    objective_definitions: list[dict[str, Any]] = Field(default_factory=list)
    snapshot_id: str
    catalog_version: str
    model_version: str
    decay_model_version: Literal["potion-decay-v1"] = "potion-decay-v1"
    configuration_fingerprint: str
    secondary_priority: str
    baseline: TimelineMeasurement
    samples: list[TimelineMeasurement]


def direct_departure_loss(request, selections, projected, catalog, content, prices, now) -> int:
    """Validate the carried union, including utility switches, before sampling decay."""
    from tracker.gear.evaluation import loadout_problems, purchase_cost
    from tracker.gear.facts import equipment_fact
    from tracker.gear.optimizer import required_transitions
    from tracker.gear.transitions import inventory_slots, plan_transition
    from tracker.gear.wilderness import WildernessRisk

    request = request.prepared_weapon_locks()
    loadouts = {key: row.equipment for key, row in selections.items()}
    carried = {item for equipment in loadouts.values() for item in equipment.values()}
    if not carried <= catalog.items.keys():
        raise ValueError("Unknown item in the selected trip")
    from tracker.gear.revenant import FORMS as REVENANT_FORMS
    from tracker.gear.revenant_acquisition import copies_available, joint_sources, preferred_sources

    sources = {
        source
        for i in carried
        if i in REVENANT_FORMS
        for source in preferred_sources(i)
        if source in catalog.items
    }
    facts = {
        i: equipment_fact(
            projected,
            catalog.items[i],
            content,
            prices,
            now,
            excluded_item_ids=request.excluded_item_ids,
            support_assumptions=catalog.community_assumptions.get(i, ()),
        )
        for i in carried | sources
    }
    for role in request.roles:
        problems = loadout_problems(loadouts[role.id], catalog.items, facts, request, role)
        if problems:
            raise ValueError(problems[0]["message"])
    if not copies_available(joint_sources(carried, facts, request), facts, request):
        raise ValueError("The selected setups require additional ready copies of the weapon")
    if purchase_cost(carried, facts, request) > request.budget_gp:
        raise ValueError("Additional purchases exceed the scenario budget")
    options = {
        key: row.combat_option.model_dump()
        for key, row in selections.items()
        if isinstance(row, TimelineLoadout)
    }
    risk = WildernessRisk.build(
        request.wilderness,
        request.wilderness_risk_limit,
        {i: catalog.items[i] for i in carried},
        facts,
        prices,
        now,
    )
    report = risk.trip_report(
        loadouts, options, catalog.items, styles={r.id: r.style for r in request.roles}
    )
    loss = report["loss_gp"]
    if type(loss) is not int or (risk.budget_gp is not None and loss > risk.budget_gp):
        raise ValueError("The selected trip requires a known Wilderness loss within the risk cap")
    runes = sum(row["kind"] == "rune" for row in report["quantities"])
    capacity = 28 - max(request.reserved_supply_slots, runes)
    if any(inventory_slots(e, carried, catalog.items) > capacity for e in loadouts.values()):
        raise ValueError("The selected trip exceeds inventory capacity")
    for source, dest in required_transitions(request):
        transition = plan_transition(
            loadouts[source], loadouts[dest], catalog.items, carried=carried, capacity=capacity
        )
        if transition is None:
            raise ValueError("The selected trip has an infeasible transition")
    return loss


def calculate_timeline(
    snapshot,
    gear,
    prices,
    body: PotionTimelineRequest,
    stopped: Event,
    *,
    frozen_at=None,
    departure_loss_gp=None,
):
    from tracker.gear.combat_options import CombatOption
    from tracker.gear.compact_costs import CostEvaluator
    from tracker.gear.evaluation import (
        evaluate_configurations,
        resolve_bolt_context,
        resolve_scenario_combat_context,
    )
    from tracker.gear.facts import hypothetical_snapshot
    from tracker.gear.halberd_charging import cost_context
    from tracker.gear.npcs import resolve_request
    from tracker.gear.potion_timeline import decay_levels, event_times, measure
    from tracker.gear.scoring import prepare_equipment
    from tracker.gear.support import project_catalog

    if not gear._optimization_lock.acquire(blocking=False):
        raise ValueError("optimizer_busy")
    try:
        now = frozen_at or datetime.now(UTC)
        catalog = gear.equipment_catalog()
        if (
            catalog.revision != body.expected_catalog_version
            or MODEL_VERSION != body.expected_model_version
        ):
            raise error("model_changed", "Combat model or catalog changed; rerun optimization", 409)
        validate_scenario(body.scenario, gear, snapshot)
        request = resolve_request(
            body.scenario.model_copy(
                update={
                    "potions": PotionPolicy(mode="fixed", selected_ids=body.selected_potion_ids)
                }
            )
        )
        projected = hypothetical_snapshot(
            snapshot, request.skill_overrides, request.quest_overrides, now
        )
        base = {k: v.level for k, v in projected.skills.items()}
        catalog = project_catalog(catalog, request.support_policy)
        items = catalog.items
        roles, prepared = [], {}
        include_cost = any(o.kind == "gp_per_damage" for o in request.objectives or ())
        include_risk = any(o.kind == "wilderness_loss_gp" for o in request.objectives or ())
        if include_risk and departure_loss_gp is None:
            departure_loss_gp = direct_departure_loss(
                request, body.loadouts, projected, catalog, gear.content, prices, now
            )
        cost_evaluator = CostEvaluator(prices, now) if include_cost else None
        costs = {}
        for role in request.roles:
            if role.style == "special":
                continue
            row = body.loadouts[role.id]
            assert isinstance(row, TimelineLoadout)
            role = role.model_copy(
                update={
                    "prayers": PrayerPolicy(mode="fixed", selected_ids=row.selected_prayer_ids),
                    "active_prayer_ids": row.selected_prayer_ids,
                }
            )
            single = request.model_copy(
                update={
                    # Departure risk and caps are validated once on the whole trip.
                    **(
                        {
                            "wilderness": None,
                            "objectives": tuple(
                                o
                                for o in request.objectives or ()
                                if o.kind != "wilderness_loss_gp"
                            ),
                        }
                        if include_risk
                        else {}
                    ),
                    "roles": (role,),
                    "transitions": (),
                    "ordered_roles": (),
                    "loop": False,
                    "base_role": role.id,
                }
            )
            selected = row.combat_option.model_dump()
            equipment: dict[str, int] = dict(row.equipment.items())
            checked = evaluate_configurations(
                snapshot,
                single,
                equipment,
                equipment,
                catalog,
                gear.content,
                prices,
                now,
                baseline_combat_option=selected,
                proposed_combat_option=selected,
            )["proposed"]
            if checked["status"] != "valid":
                raise ValueError(
                    "Invalid selected configuration: "
                    + "; ".join(r["message"] for r in checked["reasons"])
                )
            option = CombatOption(**selected)
            configured = resolve_scenario_combat_context(
                resolve_bolt_context(role, snapshot), request
            ).model_copy(
                update={
                    "style": option.style,
                    "stance": option.stance,
                    "spell": option.spell or role.spell,
                    "powered_attack": option.powered_attack,
                    "allowed_disciplines": None,
                    "combat_options": None,
                }
            )
            roles.append(configured)
            equipment_items = {slot: items[i] for slot, i in equipment.items()}
            prepared[role.id] = prepare_equipment(equipment_items)
            if cost_evaluator is not None:
                costs[role.id] = cost_evaluator.prepare(
                    equipment_items,
                    selected,
                    on_slayer_task=configured.on_slayer_task,
                    mark_of_darkness=configured.mark_of_darkness,
                    base_magic=base.get("magic"),
                    **cost_context(request, configured),
                )

        measurements = {}

        def at(seconds, levels):
            if stopped.is_set():
                raise ValueError("evaluation_cancelled")
            effective = (
                {**levels, "_base_magic": base.get("magic", 0)}
                if levels.get("magic") != base.get("magic")
                else levels
            )
            key = tuple(sorted(effective.items()))
            if key not in measurements:
                measurements[key] = measure(
                    0,
                    effective,
                    roles,
                    prepared,
                    request.secondary_priority,
                    request.objectives,
                    costs or None,
                    departure_loss_gp,
                )
            return {**measurements[key], "time_seconds": seconds}

        from tracker.gear.objectives import objective_definitions

        return PotionTimelineResponse(
            objective_definitions=objective_definitions(request.objectives or ()),
            snapshot_id=snapshot.fingerprint,
            catalog_version=catalog.revision,
            model_version=MODEL_VERSION,
            configuration_fingerprint=hashlib.sha256(
                json.dumps(
                    {
                        **body.model_dump(mode="json"),
                        **({"departure_loss_gp": departure_loss_gp} if include_risk else {}),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            secondary_priority=request.secondary_priority,
            baseline=at(0, base),
            samples=[
                at(t, decay_levels(base, body.selected_potion_ids, t))
                for t in event_times(base, body.selected_potion_ids)
            ],
        )
    finally:
        gear._optimization_lock.release()


@router.post("/potion-timelines", response_model=PotionTimelineResponse)
async def potion_timelines(
    request: Request, body: PotionTimelineRequest | FrozenPotionTimelineRequest
):
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    frozen_at = None
    departure_loss_gp = None
    frozen = isinstance(body, FrozenPotionTimelineRequest)
    if isinstance(body, FrozenPotionTimelineRequest):
        if snapshot is None:
            raise error("account_unavailable", "Account is unavailable", 409)
        snapshot, gear, prices, timeline_body, frozen_at, departure_loss_gp = (
            frozen_timeline_inputs(body, snapshot, gear)
        )
    else:
        timeline_body = body
    if snapshot is None or snapshot.fingerprint != timeline_body.scenario.expected_snapshot_id:
        raise error("snapshot_changed", "Refresh account facts and rerun optimization", 409)
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(
            calculate_timeline,
            snapshot,
            gear,
            prices,
            timeline_body,
            stopped,
            **(
                {"frozen_at": frozen_at, "departure_loss_gp": departure_loss_gp}
                if frozen_at is not None
                else {}
            ),
        )
    )
    try:
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.05)
            if await request.is_disconnected():
                stopped.set()
                worker.add_done_callback(consume)
                raise error("evaluation_cancelled", "Timeline cancelled", 499)
        result = worker.result()
        fresh, _, _ = await asyncio.to_thread(resources, request)
        if not frozen and (fresh is None or fresh.fingerprint != snapshot.fingerprint):
            raise error(
                "snapshot_changed", "Account changed during evaluation; rerun optimization", 409
            )
        return result
    except asyncio.CancelledError:
        stopped.set()
        worker.add_done_callback(consume)
        raise
    except ValueError as exc:
        if str(exc).startswith("optimizer_busy"):
            raise error(
                "optimizer_busy", "Another equipment calculation is running; retry shortly", 503
            ) from exc
        if str(exc).startswith("evaluation_cancelled"):
            raise error("evaluation_cancelled", "Timeline cancelled", 499) from exc
        raise error("invalid_request", str(exc)) from exc
