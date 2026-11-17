"""Field-local browser validation over the existing optimizer request shape."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from pydantic_core import InitErrorDetails

from tracker.gear.combat import SPELLS

Issue = Callable[[tuple[str | int, ...], str], None]


def validate_browser_scenario(data: Any) -> Any:
    """Report editable constraint locations before domain cross-field validation."""
    if not isinstance(data, dict):
        return data
    issues: list[InitErrorDetails] = []

    def issue(path: tuple[str | int, ...], message: str) -> None:
        issues.append(
            {
                "type": "value_error",
                "loc": path,
                "input": None,
                "ctx": {"error": ValueError(message)},
            }
        )

    roles = data.get("roles", [])
    if not isinstance(roles, list | tuple):
        return data
    known = {r["id"] for r in roles if isinstance(r, dict) and isinstance(r.get("id"), str)}
    _validate_roles(data, roles, known, issue)
    base = data.get("base_role")
    if base is not None and (not isinstance(base, str) or base not in known):
        issue(("base_role",), "Base role must reference a configured role")
    _validate_topology(data, known, issue)
    overrides = data.get("skill_overrides", {})
    if isinstance(overrides, dict):
        for name, level in overrides.items():
            if type(level) is not int or not 1 <= level <= 99:
                issue(
                    ("skill_overrides", name),
                    "Skill assumptions require integer levels from 1 to 99",
                )
    if roles and all(isinstance(r, dict) for r in roles):
        weights = [r.get("weight", 1) for r in roles if r.get("style") != "special"]
        if all(type(w) in (int, float) for w in weights) and not any(w > 0 for w in weights):
            issue(("roles",), "At least one scored role must have positive active time")
    if issues:
        raise ValidationError.from_exception_data("BrowserOptimizationRequest", issues)
    return data


def _validate_roles(
    data: dict[str, Any], roles: list[Any] | tuple[Any, ...], known: set[str], issue: Issue
) -> None:
    locks = data.get("locks", {})
    locks = locks if isinstance(locks, dict) else {}
    excluded = data.get("excluded_item_ids", [])
    excluded = excluded if isinstance(excluded, list | tuple) else []
    for slot, item_id in locks.items():
        if item_id is not None and item_id in excluded:
            issue(("locks", slot), "Global lock conflicts with excluded_item_ids")
    scored = {
        r["id"]
        for r in roles
        if isinstance(r, dict) and r.get("style") != "special" and isinstance(r.get("id"), str)
    }
    seen: set[str] = set()
    for index, role in enumerate(roles):
        if not isinstance(role, dict):
            continue
        role_id = role.get("id")
        if isinstance(role_id, str):
            if role_id in seen:
                issue(("roles", index, "id"), "Role IDs must be unique")
            seen.add(role_id)
        _validate_role(role, ("roles", index), known, scored, issue)
        role_locks = role.get("locks", {})
        if isinstance(role_locks, dict):
            for slot, item_id in role_locks.items():
                if slot in locks and locks[slot] != item_id:
                    issue(("roles", index, "locks", slot), "Conflicting global and role locks")
                if item_id is not None and item_id in excluded:
                    issue(
                        ("roles", index, "locks", slot),
                        "Role lock conflicts with excluded_item_ids",
                    )
        _validate_target(role.get("target"), ("roles", index), issue)


def _validate_role(
    role: dict[str, Any],
    path: tuple[str | int, ...],
    known: set[str],
    scored: set[str],
    issue: Issue,
) -> None:
    parent, style = role.get("parent_role"), role.get("style")
    if parent is not None and (
        not isinstance(parent, str) or parent not in known or parent == role.get("id")
    ):
        issue((*path, "parent_role"), "Parent must reference another configured role")
    if style == "special":
        if not isinstance(parent, str) or parent not in scored:
            issue(
                (*path, "parent_role"), "Unscored utility role requires an ordinary combat parent"
            )
        locks = role.get("locks", {})
        if not isinstance(locks, dict) or locks.get("weapon") is None:
            issue((*path, "locks", "weapon"), "Unscored utility role requires a weapon lock")
    elif role.get("allowed_disciplines") is None and style in (
        "stab",
        "slash",
        "crush",
        "ranged",
        "magic",
    ):
        allowed = (
            {"accurate", "rapid", "longrange"}
            if style == "ranged"
            else (
                {"accurate", "defensive"}
                if style == "magic"
                else {"accurate", "aggressive", "controlled", "defensive"}
            )
        )
        stance = role.get("stance", "accurate")
        if not isinstance(stance, str) or stance not in allowed:
            issue((*path, "stance"), "Selected attack type and stance are incompatible")
        spell = role.get("spell", "fire_strike")
        if style == "magic" and (not isinstance(spell, str) or spell not in SPELLS):
            issue((*path, "spell"), "Unknown standard spell")


def _validate_topology(data: dict[str, Any], known: set[str], issue: Issue) -> None:
    edges, ordered = data.get("transitions", []), data.get("ordered_roles", [])
    if isinstance(edges, list | tuple):
        if len(edges) > 16:
            issue(("transitions",), "At most 16 directed transitions are supported")
        for index, edge in enumerate(edges):
            if not isinstance(edge, list | tuple) or len(edge) != 2:
                continue
            for endpoint, value in enumerate(edge):
                if not isinstance(value, str) or value not in known:
                    issue(
                        ("transitions", index, endpoint),
                        "Transition must reference a configured role",
                    )
            if edge[0] == edge[1]:
                issue(("transitions", index), "Directed transitions require different roles")
    if isinstance(ordered, list | tuple):
        if len(ordered) > 100:
            issue(("ordered_roles",), "At most 100 ordered phases are supported")
        for index, role_id in enumerate(ordered):
            if not isinstance(role_id, str) or role_id not in known:
                issue(("ordered_roles", index), "Phase must reference a configured role")
    if edges and ordered:
        issue(("transitions",), "Choose explicit transitions or ordered phases")
    if data.get("loop") and not ordered:
        issue(("loop",), "Looping requires ordered phases")


def _validate_target(target: Any, path: tuple[str | int, ...], issue: Issue) -> None:
    if not isinstance(target, dict):
        return
    if target.get("unsupported_mechanics"):
        issue((*path, "target", "unsupported_mechanics"), "Target mechanics are unsupported")
    numeric = {
        "size",
        "defence_level",
        "magic_level",
        "ranged_light",
        "ranged_standard",
        "ranged_heavy",
        "weakness_percent",
        "damage_cap",
        "flat_armour",
    }
    for name in numeric & target.keys():
        if target[name] is not None and type(target[name]) is not int:
            issue((*path, "target", name), "Target values require integers")
        elif name == "size" and (target[name] is None or not 0 <= target[name] <= 64):
            issue((*path, "target", name), "Target size must be between 0 and 64")
        elif name == "flat_armour" and (
            target[name] is None or not -10000 <= target[name] <= 10000
        ):
            issue((*path, "target", name), "Flat armour must be between -10000 and 10000")
        elif (
            name.startswith("ranged_")
            and target[name] is not None
            and not -64 <= target[name] <= 10000
        ):
            issue((*path, "target", name), "Target ranged defence must be between -64 and 10000")
    bonuses = target.get("bonuses", {})
    if isinstance(bonuses, dict):
        for name, value in bonuses.items():
            if type(value) is not int or not -64 <= value <= 10000:
                issue(
                    (*path, "target", "bonuses", name),
                    "Target defence bonuses require integers between -64 and 10000",
                )
