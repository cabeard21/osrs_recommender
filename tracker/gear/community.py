"""Conservative ordinary-equipment evidence for the optional community policy.

Category labels alone never qualify an item. Each candidate also needs exact-ID
community wear gates, a normal GE/player form, and independently captured physical
statistics and compatibility. Unresolved non-skill gates remain an explicit user
assumption; this classification does not certify their absence.
"""

from __future__ import annotations

import re
from typing import Any

POLICY_VERSION = "ordinary-v2"
GENERIC_UNREVIEWED = "Offensive effects have not been validated."

# Narrow ordinary categories, combined with the independent evidence below.
# Do not extend this to arbitrary charged, set, location-specific or effect gear.
_METALS = "Bronze|Iron|Steel|Black|Mithril|Adamant|Rune|White"
_CATEGORIES = (
    rf"(?:{_METALS}) (?:2h sword|axe|battleaxe|claws|crossbow|dagger|dart|halberd|"
    r"hasta|knife|longsword|mace|pickaxe|scimitar|spear|sword|thrownaxe|warhammer)",
    r"(?:Oak|Willow|Maple|Yew|Magic) (?:shortbow|longbow|comp bow)",
    rf"(?:{_METALS}|Dragon|Gilded) (?:med helm|full helm|chainbody|platebody|platelegs|"
    r"plateskirt|sq shield|kiteshield|boots|gloves)(?: \((?:g|t)\))?",
    r"(?:Blue|Red|Black|Green) d'hide (?:body|chaps|vambraces|shield)(?: \((?:g|t)\))?",
    r"(?:Mystic|Enchanted|Splitbark|Infinity) (?:hat|hood|robe top|robe bottom|top|"
    r"bottoms|gloves|boots)(?: \((?:light|dark|blue|dusk)\))?",
    r"3rd Age (?:full helmet|kiteshield|platebody|platelegs|plateskirt|range coif|"
    r"range top|range legs|vambraces|mage hat|robe top|robe|amulet)",
)
_MECHANICS = re.compile(
    r"poison|venom|charg|degrad|broken|crumbl|set effect|special attack|wilderness|"
    r"barrows|ahrim|dharok|guthan|karil|torag|verac|slayer|crystal|moon|"
    r"void|obsidian|dragonfire|serpentine|enchanted bolt|deadman|last man standing",
    re.IGNORECASE,
)
_WEAPON_TYPES = {
    "axe": "Axe",
    "pickaxe": "Pickaxe",
    "slash_sword": "Slash Sword",
    "stab_sword": "Stab Sword",
    "spiked": "Spiked",
    "blunt": "Blunt",
    "2h_sword": "2h Sword",
    "spear": "Spear",
    "polearm": "Polearm",
    "claw": "Claw",
    "bow": "Bow",
    "crossbow": "Crossbow",
    "thrown": "Thrown",
}
_PHYSICAL_FIELDS = (
    "id",
    "slot",
    "bonuses",
    "attack_speed",
    "attack_styles",
    "attack_profiles",
    "two_handed",
    "ammo_type",
    "ammo_for",
    "stackable",
)
# Rune thrownaxe Chainhit and rune claws Impale have unmodeled special damage.
# Exact physical IDs, not inferred aliases. Wiki: /w/Rune_thrownaxe, /w/Rune_claws.
_KNOWN_SPECIAL_IDS = frozenset({805, 3101})


def classify_ordinary(
    physical: dict[str, Any],
    external: dict[str, Any] | None,
    capture: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return positive evidence or one exclusion reason, without changing inputs."""
    if any(x != GENERIC_UNREVIEWED for x in physical.get("unsupported_effects", [])):
        return None, "explicit_unsupported_mechanic"
    if physical["id"] in _KNOWN_SPECIAL_IDS:
        return None, "known_special_attack_mechanic"
    if not isinstance(external, dict) or type(external.get("id")) is not int:
        return None, "missing_source_identity"
    if external["id"] != physical["id"]:
        return None, "identity_mismatch"
    if any(
        external.get(k) is not False
        for k in ("incomplete", "noted", "placeholder", "duplicate", "quest_item")
    ) or any(
        external.get(k) is not True for k in ("equipable_by_player", "tradeable", "tradeable_on_ge")
    ):
        return None, "source_form_or_acquisition_unknown"
    equipment = external.get("equipment")
    if not isinstance(equipment, dict):
        return None, "missing_requirement_evidence"
    levels = equipment.get("requirements")
    assumed_ungated = levels is None or levels == {}
    if not assumed_ungated and not isinstance(levels, dict):
        return None, "invalid_requirement_evidence"
    source_slot = equipment.get("slot")
    if ("weapon" if source_slot == "2h" else source_slot) != physical["slot"] or (
        source_slot == "2h" and physical.get("two_handed") is not True
    ):
        return None, "slot_mismatch"
    if not capture or capture.get("id") != physical["id"]:
        return None, "missing_physical_capture"
    if capture.get("version") not in {"", "Unpoisoned"}:
        return None, "unresolved_variant_or_mechanic"
    normalized = capture.get("normalized", {})
    if any(normalized.get(k) != physical.get(k) for k in _PHYSICAL_FIELDS):
        return None, "physical_capture_mismatch"
    name, examine = external.get("name", ""), external.get("examine", "")
    if not isinstance(name, str) or not isinstance(examine, str) or not examine:
        return None, "missing_category_evidence"
    # Steel ring has only +24 melee defence; its enchanted examine is flavour.
    # https://oldschool.runescape.wiki/w/Steel_ring
    steel_ring = physical["id"] == 30895 and name == "Steel ring" and physical["slot"] == "ring"
    if not steel_ring and _MECHANICS.search(name + " " + examine):
        return None, "known_or_conditional_mechanic"
    if not steel_ring and not any(re.fullmatch(pattern, name) for pattern in _CATEGORIES):
        return None, "outside_ordinary_categories"
    if physical["slot"] == "weapon":
        weapon = external.get("weapon")
        if not isinstance(weapon, dict) or weapon.get("weapon_type") not in _WEAPON_TYPES:
            return None, "unsupported_weapon_category"
        if capture.get("category") != _WEAPON_TYPES[weapon["weapon_type"]]:
            return None, "weapon_category_mismatch"
        if weapon.get("attack_speed") != physical["attack_speed"]:
            return None, "weapon_speed_mismatch"
        if not physical.get("attack_profiles") or not physical.get("attack_styles"):
            return None, "missing_weapon_compatibility"
        if "ranged" in physical["attack_styles"] and (
            weapon["weapon_type"] in {"bow", "crossbow"} and not physical.get("ammo_for")
        ):
            return None, "missing_ammunition_compatibility"
    if not any(value > 0 for value in physical["bonuses"].values()):
        return None, "no_combat_benefit"
    return {
        "classification": "ordinary",
        "evidence": [
            "exact physical ID in both pinned sources",
            "normal player-equippable GE form with absent equip requirements assumed ungated"
            if assumed_ungated
            else "normal player-equippable GE form with nonempty skill gates",
            "independent physical statistics, slot and compatibility agree",
            "narrow ordinary category with no indicated conditional mechanic",
        ],
        "tradeable": True,
        **({"requirements_assumed_absent": True} if assumed_ungated else {}),
        "cosmetic_variant": bool(re.search(r"\((?:g|t)\)$", name) or name.startswith("Gilded ")),
    }, None
