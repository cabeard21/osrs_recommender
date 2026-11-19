"""Build one loose stack per rune from the concrete Wilderness combat setups."""

from collections import Counter
from collections.abc import Mapping
from typing import Any

from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import SPELL_RECIPES, STAFF_RUNES

RUNE_IDS = frozenset(item_id for recipe in SPELL_RECIPES.values() for item_id in recipe)


def wilderness_spell_runes(
    loadouts: Mapping[str, Mapping[str, int]],
    combat_options: Mapping[str, Mapping[str, Any] | None],
    items: Mapping[int, EquipmentDefinition],
    spell_casts: int | None,
) -> dict[int, int] | None:
    """Return fixed loose rune quantities, or None for an unreviewed spell recipe."""
    if spell_casts is None:
        return {}
    runes: Counter[int] = Counter()
    for role, equipment in loadouts.items():
        option = combat_options.get(role) or {}
        if option.get("attack_type") != "magic" or option.get("powered_attack"):
            continue
        if (recipe := SPELL_RECIPES.get(option.get("spell") or "")) is None:
            return None
        shield = items.get(equipment.get("shield", 0))
        supplied = STAFF_RUNES.get(equipment.get("weapon", 0), frozenset())
        tome_rune = shield.tome_effect.rune_id if shield and shield.tome_effect else None
        runes.update(
            {
                item_id: quantity * spell_casts
                for item_id, quantity in recipe.items()
                if item_id not in supplied and item_id != tome_rune
            }
        )
    return dict(runes)
