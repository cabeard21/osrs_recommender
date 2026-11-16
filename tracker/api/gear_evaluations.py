"""Exact fixed-loadout comparisons over one frozen, single-role browser scenario."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from threading import Event
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator

from tracker.api.gear_optimizations import (
    BrowserOptimizationRequest,
    ObjectiveProjection,
    Purchase,
    RunningCost,
    consume,
    error,
    same_origin,
    scenario_fingerprint,
    validate_scenario,
)
from tracker.api.gear_ui import DTO, GearRoute, ItemResponse, Preparation, no_cache, resources
from tracker.content.schema import ItemSlot
from tracker.gear.combat import MODEL_VERSION
from tracker.gear.demonbane import MODEL_VERSION as DEMONBANE_MODEL_VERSION
from tracker.gear.dragonbane import MODEL_VERSION as DRAGONBANE_MODEL_VERSION
from tracker.gear.elemental_amulets import MODEL_VERSION as ELEMENTAL_AMULET_MODEL_VERSION
from tracker.gear.facts import hypothetical_snapshot
from tracker.gear.hopper import MODEL_VERSION as HOPPER_MODEL_VERSION
from tracker.gear.leafy import MODEL_VERSION as LEAFY_MODEL_VERSION
from tracker.gear.models import CombatPerformance
from tracker.gear.optimizer import ItemId
from tracker.gear.prayers import CATALOG_REVISION as PRAYER_CATALOG_REVISION
from tracker.gear.prayers import MODEL_VERSION as PRAYER_MODEL_VERSION
from tracker.gear.running_frontier import running_cost_assumptions
from tracker.gear.slayer import MODEL_VERSION as SLAYER_MODEL_VERSION
from tracker.gear.support import SupportPolicy, support_context
from tracker.gear.tomes import MODEL_VERSION as TOME_MODEL_VERSION

router = APIRouter(
    prefix="/ui-api/gear",
    tags=["Gear browser"],
    dependencies=[Depends(no_cache)],
    route_class=GearRoute,
)


class FixedCombatOption(DTO):
    attack_type: str = Field(max_length=20)
    stance: str = Field(max_length=20)
    spell: str | None = Field(default=None, max_length=40)
    powered_attack: str | None = Field(default=None, max_length=40)


class EquipmentEvaluationRequest(DTO):
    selected_potion_ids: tuple[str, ...] | None = None
    selected_prayer_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    scenario: BrowserOptimizationRequest
    baseline_loadouts: dict[str, dict[ItemSlot, ItemId]]
    proposed_loadouts: dict[str, dict[ItemSlot, ItemId]]
    baseline_combat_options: dict[str, FixedCombatOption] = Field(default_factory=dict)
    proposed_combat_options: dict[str, FixedCombatOption] = Field(default_factory=dict)

    @model_validator(mode="after")
    def exact_role(self) -> EquipmentEvaluationRequest:
        if self.scenario.potions.mode == "optimize" and self.selected_potion_ids is None:
            raise ValueError("Fixed evaluation requires the selected fixed potion setup")
        if self.selected_potion_ids is not None:
            from tracker.gear.potions import PotionPolicy

            PotionPolicy(mode="fixed", selected_ids=self.selected_potion_ids)
            if self.scenario.potions.mode == "optimize" and not set(
                self.selected_potion_ids
            ) <= set(self.scenario.potions.allowed_ids):
                raise ValueError("Selected potions must belong to the scenario allowlist")
            if self.scenario.potions.mode != "optimize" and tuple(
                self.selected_potion_ids
            ) != tuple(self.scenario.potions.selected_ids):
                raise ValueError("Selected potions must match the scenario setup")
        if (
            len(self.scenario.roles) != 1
            or self.scenario.roles[0].style == "special"
            or self.scenario.transitions
            or self.scenario.ordered_roles
            or self.scenario.loop
        ):
            raise ValueError(
                "Exact evaluation supports one ordinary-attack role without transitions"
            )
        expected = {self.scenario.roles[0].id}
        if set(self.selected_prayer_ids) - expected:
            raise ValueError("Selected prayers must reference the submitted role")
        from tracker.gear.prayers import PrayerPolicy

        for role in self.scenario.roles:
            ids = self.selected_prayer_ids.get(role.id)
            if role.prayers.mode == "optimize" and ids is None:
                raise ValueError("Fixed evaluation requires the selected fixed prayer setup")
            if ids is not None:
                PrayerPolicy(mode="fixed", selected_ids=ids)
                if role.prayers.mode == "optimize":
                    if not set(ids) <= set(role.prayers.allowed_ids):
                        raise ValueError("Selected prayers must belong to the scenario allowlist")
                elif set(ids) != set(role.prayers.selected_ids):
                    raise ValueError("Selected prayers must match the scenario setup")
        if set(self.baseline_loadouts) != expected or set(self.proposed_loadouts) != expected:
            raise ValueError("Both fixed configurations must contain exactly the submitted role")
        if (
            set(self.baseline_combat_options) - expected
            or set(self.proposed_combat_options) - expected
        ):
            raise ValueError("Combat options must reference the submitted role")
        return self


class EvaluationReason(DTO):
    path: str
    message: str


class FixedEvaluation(ObjectiveProjection):
    objective_values: dict[str, float] = Field(default_factory=dict)
    preparations: list[Preparation] = Field(default_factory=list)
    unowned_untradeable_item_ids: list[int] = Field(default_factory=list)
    selected_prayer_ids: list[str] = Field(default_factory=list)
    potions: dict[str, Any] | None = None
    status: Literal["valid", "invalid", "unsupported"]
    equipment: dict[ItemSlot, int]
    performance: CombatPerformance | None
    reasons: list[EvaluationReason]
    purchase_cost_gp: int | None
    purchases: list[Purchase]
    assumed_item_ids: list[int]
    discipline: Literal["melee", "ranged", "magic"] | None = None
    combat_option: FixedCombatOption | None = None
    running_cost: RunningCost | None = None


class EquipmentChange(DTO):
    slot: ItemSlot
    baseline_item_id: int | None
    proposed_item_id: int | None


class EvaluationDeltas(ObjectiveProjection):
    objective_values: dict[str, float] = Field(default_factory=dict)
    dps: float
    max_hit: int
    accuracy: float
    attack_interval: float
    purchase_cost_gp: int
    equipment_changes: list[EquipmentChange]
    added_purchase_ids: list[int]
    removed_purchase_ids: list[int]


class EquipmentEvaluationResponse(ObjectiveProjection):
    objective_definitions: list[dict[str, Any]] = Field(default_factory=list)
    support_policy: SupportPolicy = "verified_only"
    support_provenance: str = ""
    api_version: Literal["gear-ui-v1"] = "gear-ui-v1"
    evaluated_at: datetime
    scenario: BrowserOptimizationRequest
    scenario_fingerprint: str
    snapshot_id: str
    catalog_version: str
    model_version: str
    assumptions_fingerprint: str
    price_revision: str
    items: list[ItemResponse]
    baseline: FixedEvaluation
    proposed: FixedEvaluation
    deltas: EvaluationDeltas | None


def calculate_evaluation(
    snapshot: Any, gear: Any, prices: Any, body: EquipmentEvaluationRequest, stopped: Event
) -> EquipmentEvaluationResponse:
    if stopped.is_set():
        raise ValueError("evaluation_cancelled")
    now = datetime.now(UTC)
    scenario = body.scenario
    if body.selected_prayer_ids:
        from tracker.gear.prayers import PrayerPolicy

        scenario = scenario.model_copy(
            update={
                "roles": tuple(
                    role.model_copy(
                        update={
                            "prayers": PrayerPolicy(
                                mode="fixed", selected_ids=body.selected_prayer_ids[role.id]
                            )
                        }
                    )
                    if role.id in body.selected_prayer_ids
                    else role
                    for role in scenario.roles
                )
            }
        )
    if body.selected_potion_ids is not None:
        from tracker.gear.potions import PotionPolicy

        scenario = scenario.model_copy(
            update={"potions": PotionPolicy(mode="fixed", selected_ids=body.selected_potion_ids)}
        )
    validate_scenario(scenario, gear, snapshot)
    catalog = gear.equipment_catalog()
    role_id = scenario.roles[0].id
    for field, loadouts in (
        ("baseline_loadouts", body.baseline_loadouts),
        ("proposed_loadouts", body.proposed_loadouts),
    ):
        for slot, item_id in loadouts[role_id].items():
            if item_id not in catalog.items:
                raise error(
                    "invalid_request", "Unknown physical item ID", field=f"{field}.{role_id}.{slot}"
                )
            if catalog.items[item_id].slot != slot:
                raise error(
                    "invalid_request",
                    f"Physical item {item_id} does not occupy {slot}",
                    field=f"{field}.{role_id}.{slot}",
                )
    result = gear.evaluate(
        snapshot,
        scenario,
        body.baseline_loadouts[role_id],
        body.proposed_loadouts[role_id],
        price_records=prices,
        now=now,
        cancelled=stopped.is_set,
        baseline_combat_option=(
            body.baseline_combat_options[role_id].model_dump()
            if role_id in body.baseline_combat_options
            else None
        ),
        proposed_combat_option=(
            body.proposed_combat_options[role_id].model_dump()
            if role_id in body.proposed_combat_options
            else None
        ),
    )
    projected = hypothetical_snapshot(
        snapshot, scenario.skill_overrides, scenario.quest_overrides, now
    )
    referenced = set(body.baseline_loadouts[role_id].values()) | set(
        body.proposed_loadouts[role_id].values()
    )
    referenced.update(
        p["item_id"] for side in (result["baseline"], result["proposed"]) for p in side["purchases"]
    )
    from tracker.gear.evaluation import resolve_bolt_context
    from tracker.gear.potions import potion_summary

    bolt_context = resolve_bolt_context(scenario.roles[0], snapshot)
    from tracker.gear.attack_reach import policy_context

    assumptions = {
        **policy_context(scenario),
        "tome_model_version": TOME_MODEL_VERSION,
        "fire_tome_pages": scenario.fire_tome_pages,
        "elemental_amulet_model_version": ELEMENTAL_AMULET_MODEL_VERSION,
        "slayer_model_version": SLAYER_MODEL_VERSION,
        "leafy_model_version": LEAFY_MODEL_VERSION,
        "demonbane_model_version": DEMONBANE_MODEL_VERSION,
        "dragonbane_model_version": DRAGONBANE_MODEL_VERSION,
        "slayer_tasks": {role.id: role.on_slayer_task for role in scenario.roles},
        "marks_of_darkness": {role.id: role.mark_of_darkness for role in scenario.roles},
        "bolt_model_version": "enchanted-bolts-v1",
        "aquanite_hopper_model_version": HOPPER_MODEL_VERSION,
        "bolt_diary": {
            "boosted": bolt_context.bolt_diary_boost,
            "known": bolt_context.bolt_diary_known,
        },
        "include_untradeables": scenario.include_untradeables,
        "prayer_model_version": PRAYER_MODEL_VERSION,
        "prayer_catalog_revision": PRAYER_CATALOG_REVISION,
        "prayers": {role.id: role.prayers.model_dump(mode="json") for role in scenario.roles},
        **(
            {
                "potions": scenario.potions.model_dump(mode="json"),
                "potion_setup": potion_summary(
                    {k: v.level for k, v in projected.skills.items()},
                    scenario.potions.selected_ids,
                    prices,
                    now,
                ),
            }
            if scenario.potions.mode != "disabled"
            else {}
        ),
        **support_context(catalog, scenario.support_policy),
        "skills": dict(scenario.skill_overrides),
        "quests": dict(scenario.quest_overrides),
        "assumed_item_ids": scenario.assumed_item_ids,
        **running_cost_assumptions(scenario, prices, scenario.optimization_mode == "thorough"),
    }
    if scenario.objectives is not None:
        from tracker.gear.objectives import objective_definitions, objective_values

        result = {
            **result,
            **{
                side: {
                    **result[side],
                    "objective_values": objective_values(
                        scenario.objectives, result[side]["performance"]
                    )
                    if result[side]["status"] == "valid"
                    else {},
                }
                for side in ("baseline", "proposed")
            },
        }
        definitions = objective_definitions(scenario.objectives)
        if result["deltas"] is not None:
            result = {
                **result,
                "deltas": {
                    **result["deltas"],
                    "objective_values": {
                        key: result["proposed"]["objective_values"][key] - value
                        for key, value in result["baseline"]["objective_values"].items()
                    },
                },
            }
    else:
        definitions = []
    return EquipmentEvaluationResponse(
        objective_definitions=definitions,
        **support_context(catalog, scenario.support_policy),
        evaluated_at=now,
        scenario=body.scenario,
        scenario_fingerprint=scenario_fingerprint(body.scenario),
        snapshot_id=snapshot.fingerprint,
        catalog_version=catalog.revision,
        model_version=MODEL_VERSION,
        assumptions_fingerprint=hashlib.sha256(
            json.dumps(assumptions, sort_keys=True).encode()
        ).hexdigest(),
        price_revision=hashlib.sha256(
            json.dumps({k: str(v) for k, v in sorted(prices.items())}, sort_keys=True).encode()
        ).hexdigest(),
        items=[
            gear.physical_item(
                projected, i, price_records=prices, now=now, support_policy=scenario.support_policy
            )
            for i in sorted(referenced)
        ],
        **result,
    )


@router.post("/evaluations", response_model=EquipmentEvaluationResponse)
async def evaluations(
    request: Request, body: EquipmentEvaluationRequest
) -> EquipmentEvaluationResponse:
    same_origin(request)
    snapshot, gear, prices = await asyncio.to_thread(resources, request)
    if snapshot is None:
        raise error("account_unavailable", "Synchronize an account before evaluating", 409)
    if snapshot.fingerprint != body.scenario.expected_snapshot_id:
        raise error(
            "snapshot_changed",
            "Account observations changed; refresh and rerun",
            409,
            "scenario.expected_snapshot_id",
        )
    stopped = Event()
    worker = asyncio.create_task(
        asyncio.to_thread(calculate_evaluation, snapshot, gear, prices, body, stopped)
    )
    try:
        while not worker.done():
            await asyncio.wait({worker}, timeout=0.05)
            if await request.is_disconnected():
                stopped.set()
                worker.add_done_callback(consume)
                raise error("evaluation_cancelled", "Evaluation cancelled", 499)
        result = worker.result()
        fresh, _, _ = await asyncio.to_thread(resources, request)
        if fresh is None or fresh.fingerprint != snapshot.fingerprint:
            raise error(
                "snapshot_changed",
                "Account observations changed during evaluation; refresh and rerun",
                409,
                "scenario.expected_snapshot_id",
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
                "optimizer_busy", "Another equipment calculation is running; retry shortly", 503
            ) from exc
        if message.startswith("evaluation_cancelled"):
            raise error("evaluation_cancelled", "Evaluation cancelled", 499) from exc
        raise error("invalid_request", message) from exc
