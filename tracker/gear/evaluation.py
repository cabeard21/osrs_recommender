"""Shared exact physical-loadout validation and ordinary-attack evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.domain.types import UnlockState
from tracker.estimation.prices import PriceRecord
from tracker.gear.combat import evaluate_loadout
from tracker.gear.compact_states import EquipmentState
from tracker.gear.facts import equipment_fact, hypothetical_snapshot
from tracker.gear.models import CombatPerformance, EquipmentDefinition
from tracker.gear.support import project_catalog
from tracker.gear.vampyre_targets import PROFILES as VAMPYRES
from tracker.gear.vampyre_targets import validate_access as validate_vampyre_access
from tracker.gear.weight_reducers import normalize_reducer_request
from tracker.gear.wilderness import WildernessRisk
from tracker.gear.wilderness_ammo import idle_ammunition
from tracker.gear.wilderness_runes import wilderness_spell_runes


def resolve_bolt_context(role: Any, snapshot: AccountSnapshot) -> Any:
    """Resolve diary benefits from authoritative observations, never client flags."""
    state = snapshot.unlocks.get("diary_kandarin_hard")
    return role.model_copy(
        update={
            "bolt_diary_boost": state is UnlockState.UNLOCKED,
            "bolt_diary_known": state in {UnlockState.UNLOCKED, UnlockState.LOCKED},
        }
    )


def equipment_problems(
    equipment: Mapping[str, int], items: Mapping[int, EquipmentDefinition]
) -> tuple[str, ...]:
    problems = []
    pairs = (
        equipment.ordered_identity if isinstance(equipment, EquipmentState) else equipment.items()
    )
    for slot, item_id in pairs:
        item = items.get(item_id)
        if item is None:
            problems.append(f"Unknown physical item ID: {item_id}.")
        elif item.slot != slot:
            problems.append(f"Physical item {item_id} does not occupy {slot}.")
    weapon = items.get(equipment.get("weapon", -1))
    if weapon and weapon.two_handed and "shield" in equipment:
        problems.append("Two-handed weapon cannot be equipped with a shield.")
    return tuple(problems)


def evaluate_equipment(
    equipment: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
    role: Any,
    levels: Mapping[str, int],
) -> CombatPerformance:
    """Validate concrete slots and reuse the authoritative combat model unchanged."""
    problems = equipment_problems(equipment, items)
    if problems:
        return CombatPerformance(supported=False, limitations=problems)
    if (
        getattr(getattr(role, "prayers", None), "mode", None) == "fixed"
        and not role.active_prayer_ids
    ):
        role = role.model_copy(update={"active_prayer_ids": role.prayers.selected_ids})
    return evaluate_loadout({slot: items[i] for slot, i in equipment.items()}, role, levels)


def wilderness_prayer_problem(request: Any, snapshot: AccountSnapshot) -> str | None:
    policy = getattr(request, "wilderness", None)
    if policy is None or not policy.protect_item:
        return None
    observed = snapshot.skills.get("prayer")
    level = request.skill_overrides.get("prayer", observed.level if observed else 0)
    if level < 25:
        return "Protect Item requires level 25 Prayer. The effective level is unknown or too low."
    return None


def wilderness_provenance(request: Any) -> dict[str, Any]:
    from tracker.gear.revenant import MODEL_VERSION

    policy = getattr(request, "wilderness", None)
    context = {"revenant_weapon_model_version": MODEL_VERSION}
    if policy is None:
        return context
    return {
        **context,
        "wilderness": policy.model_dump(mode="json"),
        "wilderness_rules_revision": policy.rules_revision,
    }


def validate_request_context(
    request: Any,
    snapshot: AccountSnapshot,
    items: Mapping[int, EquipmentDefinition],
    content: Content,
) -> None:
    """Validate catalog-bound request facts for every transport, before any search."""
    from tracker.gear.defensive_rolls import required_defensive_skills

    request = normalize_reducer_request(request, items)
    objectives = getattr(request, "objectives", None)
    if objectives is None:
        required = required_defensive_skills(request.secondary_priority)
    else:
        from tracker.gear.objectives import required_objective_skills

        required = required_objective_skills(objectives)
    levels = {
        **{key: value.level for key, value in snapshot.skills.items()},
        **request.skill_overrides,
    }
    if prayer_problem := wilderness_prayer_problem(request, snapshot):
        raise ValueError(prayer_problem)
    missing = sorted(skill for skill in required if levels.get(skill, 0) < 1)
    if missing:
        raise ValueError(
            "Player defensive roll is unavailable: unknown " + ", ".join(missing) + " level"
        )
    if request.expected_snapshot_id and request.expected_snapshot_id != snapshot.fingerprint:
        raise ValueError("snapshot_changed: retrieve current account facts")
    for field, allowed in (
        ("skill_overrides", content.skills),
        ("quest_overrides", content.quests),
    ):
        if any(key not in allowed for key in getattr(request, field)):
            raise ValueError(f"unknown {field} assumption")
    for field in ("assumed_item_ids", "excluded_item_ids"):
        if any(item_id not in items for item_id in getattr(request, field)):
            raise ValueError(f"unknown physical item ID in {field}")
    for role in request.roles:
        from tracker.gear.leafy import NPC_SLAYER
        from tracker.gear.npcs import npc_catalog
        from tracker.gear.prayers import setups as prayer_setups

        if role.target_selection is not None:
            entry = npc_catalog().detail(role.target_selection.key)
            vampyre = VAMPYRES.get((entry["npc_id"], entry["name"], entry["variant"]))
            if vampyre:
                validate_vampyre_access(
                    vampyre,
                    entry["name"],
                    levels,
                    snapshot.quests,
                    request.quest_overrides,
                    role.on_slayer_task,
                )
            minimum = NPC_SLAYER.get(entry["npc_id"])
            if minimum is not None and (levels.get("slayer") or 0) < minimum:
                raise ValueError(
                    f"{entry['name']} requires {minimum} Slayer; current level is unknown or unmet."
                )

        # Policy schemas already validate IDs and conflicts. Only a fixed setup
        # requires account eligibility here; Optimize filters once in the search.
        if role.prayers.mode == "fixed":
            prayer_setups(role.prayers, snapshot, levels)
        for slot, item_id in {**request.locks, **role.locks}.items():
            if item_id is None:
                continue
            if item_id not in items:
                raise ValueError(f"unknown locked item ID: {item_id}")
            if items[item_id].slot != slot:
                raise ValueError(f"locked item {item_id} does not occupy {slot}")
            if item_id in request.excluded_item_ids:
                raise ValueError(f"locked item {item_id} is excluded")


def resolve_scenario_combat_context(role: Any, request: Any) -> Any:
    """Carry scenario-wide combat settings into immutable per-attack role copies."""
    configured = role.model_copy(update={"fire_tome_pages": request.fire_tome_pages})
    configured._in_wilderness = request.wilderness is not None
    return configured


def planning_owned(fact: Mapping[str, Any]) -> Mapping[str, Any]:
    """Planning preparation never alters the concrete account observation."""
    value: Mapping[str, Any] = fact.get("planning_ownership", fact["ownership"])
    return value


def item_problems(item_id: int, fact: Mapping[str, Any], request: Any) -> tuple[str, ...]:
    """The optimizer's unchanged access policy, with concrete exclusions applied first."""
    if item_id in request.excluded_item_ids:
        return (f"Physical item {item_id} is excluded.",)
    preparation = fact.get("preparation") or {}
    if preparation.get("source_item_id") in request.excluded_item_ids:
        return ("Preparation source is excluded.",)
    if fact["wear"]["status"] != "satisfied":
        return (f"Physical item {item_id}: equipment requirements are {fact['wear']['status']}.",)
    if planning_owned(fact)["status"] == "owned":
        return ()
    if (
        item_id not in request.assumed_item_ids
        and preparation.get("market_item_id") in request.excluded_item_ids
    ):
        return ("Preparation market form is excluded.",)
    if request.mode == "owned":
        return (f"Physical item {item_id} is not observed owned.",)
    if item_id in request.assumed_item_ids:
        return ()
    if getattr(request, "include_untradeables", False) and fact["acquisition"] == "untradeable":
        prerequisite = fact.get("acquisition_requirement")
        if prerequisite and prerequisite["status"] != "satisfied":
            return (
                f"Physical item {item_id}: acquisition requirements are {prerequisite['status']}.",
            )
        return ()
    if fact["acquisition"] != "tradeable":
        return (f"Physical item {item_id} cannot be acquired through a supported purchase.",)
    if not fact.get("budget_exempt", False) and fact["price"]["amount_gp"] is None:
        return (f"Physical item {item_id} has no usable purchase price.",)
    return ()


def unowned_untradeables(
    ids: set[int], facts: Mapping[int, dict[str, Any]], request: Any
) -> list[int]:
    """Hypothetical acquisitions, distinct from observations and GE purchases."""
    if not getattr(request, "include_untradeables", False) or request.mode == "owned":
        return []
    return sorted(
        i
        for i in ids
        if planning_owned(facts[i])["status"] != "owned"
        and facts[i]["acquisition"] == "untradeable"
    )


def purchase_cost(ids: set[int], facts: Mapping[int, dict[str, Any]], request: Any) -> int:
    """Count distinct gear purchases, excluding consumable ammunition and darts."""
    return sum(p["cost_gp"] or 0 for p in purchases(ids, facts, request))


def purchases(
    ids: set[int], facts: Mapping[int, dict[str, Any]], request: Any
) -> list[dict[str, Any]]:
    untradeables = set(unowned_untradeables(ids, facts, request))
    from tracker.gear.revenant_acquisition import joint_sources

    planned = joint_sources(ids, facts, request)
    result: dict[int, dict[str, Any]] = {}
    for i in sorted(ids):
        fact = facts[i]
        if (
            (planned[i] is not None if i in planned else planning_owned(fact)["status"] == "owned")
            or i in request.assumed_item_ids
            or i in untradeables
            or fact.get("budget_exempt", False)
        ):
            continue
        preparation = fact.get("preparation") or {}
        market_id = preparation.get("market_item_id") or i
        if i in planned and market_id in result:
            row = result[market_id]
            quantity = row.get("quantity", 1) + 1
            unit_price = fact["price"]["amount_gp"]
            row.update(
                quantity=quantity, cost_gp=None if unit_price is None else quantity * unit_price
            )
            continue
        result[market_id] = {
            "item_id": market_id,
            "cost_gp": fact["price"]["amount_gp"],
            "conditional": fact["ownership"]["status"] == "unknown"
            if i in planned
            else planning_owned(fact)["status"] == "unknown",
        }
    return [result[i] for i in sorted(result)]


def loadout_problems(
    equipment: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
    facts: Mapping[int, dict[str, Any]],
    request: Any,
    role: Any,
) -> tuple[dict[str, str], ...]:
    """Complete physical/access/lock legality shared with final search validation."""
    problems = [
        {"path": "equipment", "message": reason} for reason in equipment_problems(equipment, items)
    ]
    for slot, item_id in equipment.items():
        if item_id in facts:
            problems.extend(
                {"path": f"equipment.{slot}", "message": reason}
                for reason in item_problems(item_id, facts[item_id], request)
            )
    for slot, item_id in {**request.locks, **role.locks}.items():
        if equipment.get(slot) != item_id:
            problems.append(
                {
                    "path": f"equipment.{slot}",
                    "message": f"Equipment does not satisfy the {slot} lock.",
                }
            )
    from tracker.gear.attack_reach import safe_spotting_problem

    reach_problem = safe_spotting_problem(items.get(equipment.get("weapon", -1)), role)
    if reach_problem:
        problems.append({"path": "equipment.weapon", "message": reach_problem})
    return tuple(problems)


def _configured_attack(role: Any) -> dict[str, Any]:
    return {
        "attack_type": role.style,
        "stance": role.stance,
        "spell": role.spell if role.style == "magic" else None,
        "powered_attack": role.powered_attack,
    }


def evaluate_configuration(
    equipment: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
    facts: Mapping[int, dict[str, Any]],
    request: Any,
    role: Any,
    levels: Mapping[str, int],
    *,
    wilderness: WildernessRisk | None = None,
    combat_resolved: bool = True,
) -> dict[str, Any]:
    """Evaluate one fixed ordinary loadout without generating or repairing candidates."""
    reasons = list(loadout_problems(equipment, items, facts, request, role))
    ids = set(equipment.values())
    required = purchases(ids, facts, request)
    cost = (
        None if any(p["cost_gp"] is None for p in required) else purchase_cost(ids, facts, request)
    )
    risk = None
    runes: dict[int, int] | None = {}
    trip = wilderness is not None and wilderness.policy.attacks_per_setup is not None
    if wilderness is not None and trip and combat_resolved:
        risk = wilderness.trip_report(
            {role.id: equipment},
            {role.id: _configured_attack(role)},
            items,
            styles={role.id: role.style},
        )
    elif wilderness is not None and not trip:
        loadouts = {role.id: equipment}
        casts = wilderness.policy.spell_casts
        if casts is not None:
            runes = (
                wilderness_spell_runes(loadouts, {role.id: _configured_attack(role)}, items, casts)
                if combat_resolved
                else None
            )
        risk = wilderness.report(
            loadouts,
            base_role=role.id,
            idle_ammunition=idle_ammunition(((equipment, role.style),), items),
            runes=runes,
        )
    purchase_budget = request.purchase_budget
    if purchase_budget is not None and cost is not None and cost > purchase_budget:
        reasons.append(
            {
                "path": "budget_gp",
                "message": "Additional purchase cost exceeds the scenario budget.",
            }
        )
    if (
        wilderness is not None
        and risk is not None
        and (not wilderness.trip_fits(risk) if trip else not wilderness.rune_feasible(ids, runes))
    ):
        loss = risk["loss_gp"]
        if loss is not None and wilderness.budget_gp is not None and loss > wilderness.budget_gp:
            reason = "Wilderness gear loss exceeds the risk budget."
        elif trip:
            reason = (
                "A loss could not be verified for the required starting equipment and supplies."
            )
        elif runes and loss is not None:
            reason = "Carried runes or ammunition can displace protected gear."
        else:
            reason = "Wilderness risk cannot be verified for this equipment and budget."
        reasons.append(
            {
                "path": (
                    "wilderness.attacks_per_setup"
                    if trip and loss is None
                    else "budget_gp"
                    if purchase_budget is None
                    else "wilderness.max_loss_gp"
                ),
                "message": reason,
            }
        )
    performance = evaluate_equipment(equipment, items, role, levels) if not reasons else None
    status = "invalid" if reasons else "valid"
    if performance is not None and not performance.supported:
        status = "unsupported"
        reasons.extend(
            {"path": "performance", "message": reason} for reason in performance.limitations
        )
        performance = None
    return {
        "status": status,
        "equipment": dict(equipment),
        "preparations": [
            facts[i]["preparation"] for i in sorted(ids) if facts[i].get("preparation")
        ],
        "performance": performance.model_dump(mode="json") if performance else None,
        "reasons": reasons,
        "purchase_cost_gp": cost,
        "purchases": required,
        "assumed_item_ids": sorted(ids.intersection(request.assumed_item_ids)),
        "unowned_untradeable_item_ids": unowned_untradeables(ids, facts, request),
        **({"wilderness_risk": risk} if risk is not None else {}),
    }


def evaluate_configurations(
    snapshot: AccountSnapshot,
    request: Any,
    baseline: Mapping[str, int],
    proposed: Mapping[str, int],
    catalog: Any,
    content: Content,
    price_records: Mapping[int, PriceRecord],
    now: datetime,
    *,
    baseline_combat_option: Mapping[str, Any] | None = None,
    proposed_combat_option: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Both sides share exactly one account projection, price set and calculation time."""
    request = normalize_reducer_request(request, catalog.items).prepared_weapon_locks()
    if request.potions.mode == "optimize":
        raise ValueError("Fixed evaluation requires an explicit fixed potion setup")
    if (
        len(request.roles) != 1
        or request.roles[0].style == "special"
        or request.transitions
        or request.ordered_roles
        or request.loop
    ):
        raise ValueError("Exact evaluation supports one ordinary-attack role without transitions")
    catalog = project_catalog(catalog, request.support_policy)
    validate_request_context(request, snapshot, catalog.items, content)
    role = resolve_scenario_combat_context(
        resolve_bolt_context(request.roles[0], snapshot), request
    )
    if role.prayers.mode == "optimize":
        raise ValueError("Fixed evaluation requires an explicit fixed prayer setup")
    if role.prayers.mode == "fixed":
        role = role.model_copy(update={"active_prayer_ids": role.prayers.selected_ids})
    referenced = set(baseline.values()) | set(proposed.values())
    if any(type(i) is not int or i <= 0 for i in referenced):
        raise ValueError("Fixed equipment requires positive integer physical item IDs")
    if any(i not in catalog.items for i in referenced):
        raise ValueError("unknown physical item ID in fixed configuration")
    projected = hypothetical_snapshot(
        snapshot, request.skill_overrides, request.quest_overrides, now
    )
    facts = {
        i: equipment_fact(
            projected,
            catalog.items[i],
            content,
            price_records,
            now,
            excluded_item_ids=request.excluded_item_ids,
            support_assumptions=getattr(catalog, "community_assumptions", {}).get(i, ()),
        )
        for i in referenced
    }
    risk_limit = request.wilderness_risk_limit
    wilderness = (
        WildernessRisk.build(
            request.wilderness,
            risk_limit,
            {i: catalog.items[i] for i in referenced},
            facts,
            price_records,
            now,
        )
        if request.wilderness is not None
        else None
    )
    from tracker.gear.potions import boosted_levels, potion_summary

    base_levels = {k: v.level for k, v in projected.skills.items()}
    levels = boosted_levels(base_levels, request.potions.selected_ids)
    if levels.get("magic") != base_levels.get("magic"):
        levels = {**levels, "_base_magic": base_levels.get("magic", 0)}

    def priced(
        result: dict[str, Any],
        equipment: Mapping[str, int],
        configured: Any,
        option: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        from tracker.gear.running_costs import evaluate_running_cost

        if result["status"] != "valid":
            return result
        selected_option = option or _configured_attack(configured)
        return {
            **result,
            "selected_prayer_ids": list(configured.active_prayer_ids),
            "potions": potion_summary(
                base_levels, request.potions.selected_ids, price_records, now
            ),
            "running_cost": evaluate_running_cost(
                {slot: catalog.items[i] for slot, i in equipment.items()},
                selected_option,
                result["performance"],
                price_records,
                now,
                on_slayer_task=configured.on_slayer_task,
                fight_duration_seconds=getattr(configured, "fight_duration_seconds", 60),
                crystal_halberd_charging=getattr(request, "crystal_halberd_charging", None),
                mark_of_darkness=configured.mark_of_darkness,
                base_magic=base_levels.get("magic"),
            ),
        }

    def fixed(equipment: Mapping[str, int], selected: Mapping[str, Any] | None) -> dict[str, Any]:
        configured = role
        if role.allowed_disciplines is not None:
            from tracker.gear.auto import resolve_auto_role

            def within_rune_budget(option: Mapping[str, Any]) -> bool:
                if wilderness is not None and wilderness.policy.attacks_per_setup is not None:
                    report = wilderness.trip_report(
                        {role.id: equipment},
                        {role.id: option},
                        catalog.items,
                        styles={role.id: str(option["attack_type"])},
                    )
                    return wilderness.trip_fits(report)
                if wilderness is None or wilderness.policy.spell_casts is None:
                    return True
                runes = wilderness_spell_runes(
                    {role.id: equipment},
                    {role.id: option},
                    catalog.items,
                    wilderness.policy.spell_casts,
                )
                return wilderness.rune_feasible(set(equipment.values()), runes)

            resolved = resolve_auto_role(
                role,
                equipment,
                catalog.items,
                projected,
                levels,
                selected,
                prefer=within_rune_budget if selected is None else None,
            )
            if resolved is None:
                result = evaluate_configuration(
                    equipment,
                    catalog.items,
                    facts,
                    request,
                    role,
                    levels,
                    wilderness=wilderness,
                    combat_resolved=False,
                )
                return {
                    **result,
                    "status": "invalid",
                    "performance": None,
                    "reasons": [
                        *result["reasons"],
                        {
                            "path": "combat_option",
                            "message": (
                                "No legal combat option satisfies the Auto "
                                "discipline allowlist and filters."
                            ),
                        },
                    ],
                }
            configured, chosen_option = resolved
            result = evaluate_configuration(
                equipment, catalog.items, facts, request, configured, levels, wilderness=wilderness
            )
            return {
                **priced(result, equipment, configured, chosen_option),
                "discipline": "melee"
                if configured.style in {"stab", "slash", "crush"}
                else configured.style,
                "combat_option": chosen_option,
            }
        if selected is not None:
            from tracker.gear.combat_options import eligible_combat_options

            weapon = catalog.items.get(equipment.get("weapon", -1))
            discipline = "melee" if role.style in {"stab", "slash", "crush"} else role.style
            allowed = role.combat_options
            options = eligible_combat_options(
                weapon, projected, discipline=discipline, levels=levels
            )
            legal = [
                o
                for o in options
                if o.available
                and o.model_dump(include={"attack_type", "stance", "spell", "powered_attack"})
                == dict(selected)
            ]
            if legal:
                chosen = legal[0]
                spell_id = chosen.spell or (
                    f"powered:{weapon.id}" if chosen.powered_attack and weapon else None
                )
                if allowed is not None:
                    legal = [
                        o
                        for o in legal
                        if o.attack_type in allowed.attack_types
                        and o.stance in allowed.stances
                        and (spell_id is None or spell_id in allowed.spells)
                    ]
                elif (
                    chosen.style != role.style
                    or chosen.stance != role.stance
                    or (chosen.spell is not None and chosen.spell != role.spell)
                    or chosen.powered_attack != role.powered_attack
                ):
                    legal = []
            if not legal:
                result = evaluate_configuration(
                    equipment,
                    catalog.items,
                    facts,
                    request,
                    role,
                    levels,
                    wilderness=wilderness,
                    combat_resolved=False,
                )
                return {
                    **result,
                    "status": "invalid",
                    "performance": None,
                    "reasons": [
                        *result["reasons"],
                        {
                            "path": "combat_option",
                            "message": (
                                "Selected combat option is not legal "
                                "for this equipment and scenario."
                            ),
                        },
                    ],
                }
            chosen = legal[0]
            configured = role.model_copy(
                update={
                    "style": chosen.style,
                    "stance": chosen.stance,
                    "spell": chosen.spell or role.spell,
                    "powered_attack": chosen.powered_attack,
                    "combat_options": None,
                }
            )
        result = evaluate_configuration(
            equipment, catalog.items, facts, request, configured, levels, wilderness=wilderness
        )
        if configured.style == "magic" and configured.powered_attack is None:
            from tracker.gear.combat_options import ancient_spell_problem

            problem = ancient_spell_problem(
                catalog.items.get(equipment.get("weapon", -1)),
                projected,
                configured.spell,
                configured.stance,
                levels,
                mark_of_darkness=configured.mark_of_darkness,
            )
            if problem:
                return {
                    **result,
                    "status": "invalid",
                    "performance": None,
                    "reasons": [*result["reasons"], {"path": "spell", "message": problem}],
                }
        return priced(result, equipment, configured, selected)

    first = fixed(baseline, baseline_combat_option)
    second = fixed(proposed, proposed_combat_option)
    deltas = None
    if first["status"] == second["status"] == "valid":
        deltas = {
            key: second["performance"][key] - first["performance"][key]
            for key in ("dps", "max_hit", "accuracy", "attack_interval")
        }
        deltas.update(
            purchase_cost_gp=second["purchase_cost_gp"] - first["purchase_cost_gp"],
            equipment_changes=[
                {
                    "slot": slot,
                    "baseline_item_id": baseline.get(slot),
                    "proposed_item_id": proposed.get(slot),
                }
                for slot in sorted(set(baseline) | set(proposed))
                if baseline.get(slot) != proposed.get(slot)
            ],
            added_purchase_ids=sorted(
                {p["item_id"] for p in second["purchases"]}
                - {p["item_id"] for p in first["purchases"]}
            ),
            removed_purchase_ids=sorted(
                {p["item_id"] for p in first["purchases"]}
                - {p["item_id"] for p in second["purchases"]}
            ),
        )
    return {"baseline": first, "proposed": second, "deltas": deltas}
