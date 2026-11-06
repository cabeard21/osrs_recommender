"""Shared exact physical-loadout validation and ordinary-attack evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.estimation.prices import PriceRecord
from tracker.gear.combat import evaluate_loadout
from tracker.gear.facts import equipment_fact, hypothetical_snapshot
from tracker.gear.models import CombatPerformance, EquipmentDefinition
from tracker.gear.support import project_catalog


def equipment_problems(
    equipment: Mapping[str, int], items: Mapping[int, EquipmentDefinition]
) -> tuple[str, ...]:
    problems = []
    for slot, item_id in equipment.items():
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


def validate_request_context(
    request: Any,
    snapshot: AccountSnapshot,
    items: Mapping[int, EquipmentDefinition],
    content: Content,
) -> None:
    """Validate catalog-bound request facts for every transport, before any search."""
    from tracker.gear.defensive_rolls import required_defensive_skills

    required = required_defensive_skills(request.secondary_priority)
    levels = {
        **{key: value.level for key, value in snapshot.skills.items()},
        **request.skill_overrides,
    }
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
        from tracker.gear.prayers import setups as prayer_setups

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


def planning_owned(fact: Mapping[str, Any]) -> Mapping[str, Any]:
    """Planning preparation never alters the concrete account observation."""
    value: Mapping[str, Any] = fact.get("planning_ownership", fact["ownership"])
    return value


def item_problems(item_id: int, fact: Mapping[str, Any], request: Any) -> tuple[str, ...]:
    """The optimizer's unchanged access policy, with concrete exclusions applied first."""
    if item_id in request.excluded_item_ids:
        return (f"Physical item {item_id} is excluded.",)
    if fact["wear"]["status"] != "satisfied":
        return (f"Physical item {item_id}: equipment requirements are {fact['wear']['status']}.",)
    if planning_owned(fact)["status"] == "owned":
        return ()
    if request.mode == "owned":
        return (f"Physical item {item_id} is not observed owned.",)
    if item_id in request.assumed_item_ids:
        return ()
    if getattr(request, "include_untradeables", False) and fact["acquisition"] == "untradeable":
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
    result = {}
    for i in sorted(ids):
        fact = facts[i]
        if (
            planning_owned(fact)["status"] == "owned"
            or i in request.assumed_item_ids
            or i in untradeables
            or fact.get("budget_exempt", False)
        ):
            continue
        preparation = fact.get("preparation") or {}
        market_id = preparation.get("market_item_id") or i
        result[market_id] = {
            "item_id": market_id,
            "cost_gp": fact["price"]["amount_gp"],
            "conditional": planning_owned(fact)["status"] == "unknown",
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
    return tuple(problems)


def evaluate_configuration(
    equipment: Mapping[str, int],
    items: Mapping[int, EquipmentDefinition],
    facts: Mapping[int, dict[str, Any]],
    request: Any,
    role: Any,
    levels: Mapping[str, int],
) -> dict[str, Any]:
    """Evaluate one fixed ordinary loadout without generating or repairing candidates."""
    reasons = list(loadout_problems(equipment, items, facts, request, role))
    ids = set(equipment.values())
    required = purchases(ids, facts, request)
    cost = (
        None if any(p["cost_gp"] is None for p in required) else purchase_cost(ids, facts, request)
    )
    if cost is not None and cost > request.budget_gp:
        reasons.append(
            {
                "path": "budget_gp",
                "message": "Additional purchase cost exceeds the scenario budget.",
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
    request = request.prepared_weapon_locks()
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
    role = request.roles[0]
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
            support_assumptions=getattr(catalog, "community_assumptions", {}).get(i, ()),
        )
        for i in referenced
    }
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
        selected_option = option or {
            "attack_type": configured.style,
            "stance": configured.stance,
            "spell": configured.spell if configured.style == "magic" else None,
            "powered_attack": configured.powered_attack,
        }
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
            ),
        }

    def fixed(equipment: Mapping[str, int], selected: Mapping[str, Any] | None) -> dict[str, Any]:
        configured = role
        if role.allowed_disciplines is not None:
            from tracker.gear.auto import resolve_auto_role

            resolved = resolve_auto_role(
                role, equipment, catalog.items, projected, levels, selected
            )
            if resolved is None:
                result = evaluate_configuration(
                    equipment, catalog.items, facts, request, role, levels
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
                equipment, catalog.items, facts, request, configured, levels
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
                    equipment, catalog.items, facts, request, role, levels
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
            equipment, catalog.items, facts, request, configured, levels
        )
        if configured.style == "magic" and configured.powered_attack is None:
            from tracker.gear.combat_options import ancient_spell_problem

            problem = ancient_spell_problem(
                catalog.items.get(equipment.get("weapon", -1)),
                projected,
                configured.spell,
                configured.stance,
                levels,
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
