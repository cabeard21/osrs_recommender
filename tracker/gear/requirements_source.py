"""Partial community level gates; never evidence of complete wear eligibility."""

from collections.abc import Container
from typing import Any

from tracker.content.requirements import AllOf, CombatLevelLeaf, Requirement, SkillLeaf


def requirement_state(row: dict[str, Any] | None) -> str:
    if row is None:
        return "unmatched"
    if not isinstance(row, dict):
        return "invalid_record"
    equipment = row.get("equipment")
    if not isinstance(equipment, dict):
        return "no_equipment"
    if "requirements" not in equipment:
        return "missing"
    levels = equipment["requirements"]
    if levels is None:
        return "null"
    return "empty" if levels == {} else "populated"


def requirement_from_levels(levels: Any, skills: Container[str]) -> Requirement:
    """Reject entire maps with unknown keys or invalid values, including booleans."""
    if not isinstance(levels, dict) or not levels:
        raise ValueError("Expected nonempty requirement map")
    if not all(isinstance(key, str) for key in levels):
        raise ValueError("Requirement keys must be skill names")
    children: list[Requirement] = []
    for key, level in sorted(levels.items()):
        if key not in skills and key != "combat":
            raise ValueError(f"Unknown requirement key: {key}")
        minimum, maximum = (3, 126) if key == "combat" else (1, 99)
        if type(level) is not int or not minimum <= level <= maximum:
            raise ValueError(f"Invalid requirement level: {key}")
        children.append(
            CombatLevelLeaf(level=level) if key == "combat" else SkillLeaf(skill=key, level=level)
        )
    return children[0] if len(children) == 1 else AllOf(children=tuple(children))
