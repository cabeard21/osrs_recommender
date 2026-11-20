"""Bundled equipment statistics with reviewed authored requirement overlays."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from tracker.content.loader import Content
from tracker.content.requirements import AllOf, MembersLeaf, SkillLeaf
from tracker.gear.bolts_catalog import REQUIREMENTS as BOLT_REQUIREMENTS
from tracker.gear.bolts_catalog import REVISION as BOLT_REVISION
from tracker.gear.bolts_catalog import TRADEABLE as BOLT_TRADEABLE
from tracker.gear.bolts_catalog import apply_review as bolt_review
from tracker.gear.combat import ANCIENT_SPELLS, ELEMENTAL_SPELLS, IBAN_STAVES
from tracker.gear.demonbane import AUTOCAST_STAVES as DEMONBANE_STAVES
from tracker.gear.demonbane import FORMS as DEMONBANE_FORMS
from tracker.gear.demonbane import REQUIREMENTS as DEMONBANE_REQUIREMENTS
from tracker.gear.demonbane import REVISION as DEMONBANE_REVISION
from tracker.gear.demonbane import SPELLS as DEMONBANE_SPELLS
from tracker.gear.demonbane import TRADEABLE as DEMONBANE_TRADEABLE
from tracker.gear.demonbane import apply_review as demonbane_review
from tracker.gear.dragonbane import FORMS as DRAGONBANE_FORMS
from tracker.gear.dragonbane import REVISION as DRAGONBANE_REVISION
from tracker.gear.dragonbane import TRADEABLE as DRAGONBANE_TRADEABLE
from tracker.gear.dragonbane import apply_review as dragonbane_review
from tracker.gear.dragonbane import requirement as dragonbane_requirement
from tracker.gear.elemental_amulets import FORMS as ELEMENTAL_AMULETS
from tracker.gear.elemental_amulets import REVISION as ELEMENTAL_AMULET_REVISION
from tracker.gear.elemental_amulets import apply_review as elemental_amulet_review
from tracker.gear.halberds import FORMS as HALBERD_FORMS
from tracker.gear.halberds import REVISION as HALBERD_REVISION
from tracker.gear.halberds import TRADEABLE as HALBERD_TRADEABLE
from tracker.gear.halberds import apply_review as halberd_review
from tracker.gear.halberds import requirement as halberd_requirement
from tracker.gear.hopper import REVISION as HOPPER_REVISION
from tracker.gear.hopper_catalog import apply_review as hopper_review
from tracker.gear.leafy import FORMS as LEAFY_FORMS
from tracker.gear.leafy import REQUIREMENTS as LEAFY_REQUIREMENTS
from tracker.gear.leafy import REVISION as LEAFY_REVISION
from tracker.gear.leafy import TRADEABLE as LEAFY_TRADEABLE
from tracker.gear.leafy import apply_review as leafy_review
from tracker.gear.models import EquipmentDefinition
from tracker.gear.obsidian import REVISION as OBSIDIAN_REVISION
from tracker.gear.obsidian import apply_review as obsidian_review
from tracker.gear.powered import REVISION as POWERED_REVISION
from tracker.gear.powered import review as powered_review
from tracker.gear.requirements_source import requirement_from_levels
from tracker.gear.revenant import FORMS as REVENANT_FORMS
from tracker.gear.revenant import REVISION as REVENANT_REVISION
from tracker.gear.revenant import apply_review as revenant_review
from tracker.gear.reviewed_attacks import DOUBLE_ATTACKS, DUAL_PROFILES
from tracker.gear.salve import FORMS as SALVE_FORMS
from tracker.gear.salve import REVISION as SALVE_REVISION
from tracker.gear.salve import apply_review as salve_review
from tracker.gear.size_damage import COLOSSAL_BLADE
from tracker.gear.size_damage import REVISION as SIZE_DAMAGE_REVISION
from tracker.gear.size_damage import apply_review as size_damage_review
from tracker.gear.slayer import FORMS as SLAYER_FORMS
from tracker.gear.slayer import MAGIC_DART_STAVES
from tracker.gear.slayer import REVISION as SLAYER_REVISION
from tracker.gear.slayer import apply_review as slayer_review
from tracker.gear.tomes import FORMS as TOME_FORMS
from tracker.gear.tomes import MARKET_FORMS as TOME_MARKET_FORMS
from tracker.gear.tomes import REVISION as TOME_REVISION
from tracker.gear.tomes import apply_review as tome_review

# Reviewed ordinary forms only, not general ownership aliases. The pinned Wiki
# equipment_aliases.json maps these Soul Wars/Emir's Arena rings to 11773.
# Their physical rows must still match before sharing requirements/effects review.
# Glory charges power teleports; all six ordinary charged forms retain the same
# combat bonuses and wear gates. https://oldschool.runescape.wiki/w/Amulet_of_glory
REVIEWED_EQUIVALENT_FORMS: Mapping[int, int] = MappingProxyType(
    {
        25264: 11773,
        26770: 11773,
        1706: 1704,
        1708: 1704,
        1710: 1704,
        1712: 1704,
        11976: 1704,
        11978: 1704,
        # Wearable locked defenders share combat stats and wear gates with the
        # ordinary form. Broken forms need repair and are excluded.
        24136: 8844,
        24137: 8845,
        24138: 8846,
        24139: 8847,
        24140: 8848,
        24141: 8849,
        24142: 8850,
        24143: 12954,
        24186: 22322,
        27008: 19722,
        27009: 23230,
        27551: 27550,
        27553: 27552,
    }
)

# Exact physical staves with reviewed Standard spellbook autocast.
# https://oldschool.runescape.wiki/w/Autocast
# https://oldschool.runescape.wiki/w/Mystic_air_staff
# https://oldschool.runescape.wiki/w/Ancient_staff
REVIEWED_STANDARD_STAVES = frozenset(
    {1381, 1383, 1385, 1387, 1401, 1403, 1405, 1407, 4675, 6526, 27785, 27788, 27676, 27679, 30070}
)
# Exact ordinary Ancient autocast review; no blessing of special staff effects.
# https://oldschool.runescape.wiki/w/Ancient_staff
REVIEWED_ANCIENT_STAVES = frozenset({4675, 27785, 27788, 27676, 27679, 30070})
REVIEWED_POWERED_TRADEABLE = frozenset(
    {28585, 11905, 11908, 12900, 22481, 22552, 27662, 31115, 27277, 22290, 22294}
)


def _reviewed_spells(item_id: int) -> tuple[str, ...]:
    return (
        (tuple(ELEMENTAL_SPELLS) if item_id in REVIEWED_STANDARD_STAVES else ())
        + (tuple(ANCIENT_SPELLS) if item_id in REVIEWED_ANCIENT_STAVES else ())
        + (tuple(DEMONBANE_SPELLS) if item_id in DEMONBANE_STAVES else ())
        + (tuple(ELEMENTAL_SPELLS) if item_id == 29594 else ())
        + (("iban_blast",) if item_id in IBAN_STAVES else ())
        + (
            ("magic_dart", *(s for s in ELEMENTAL_SPELLS if s.endswith(("_wave", "_surge"))))
            if item_id in MAGIC_DART_STAVES
            else ()
        )
    )


def _reviewed_equivalent(
    row: dict[str, Any], rows: Mapping[int, dict[str, Any]]
) -> dict[str, Any] | None:
    primary_id = REVIEWED_EQUIVALENT_FORMS.get(row["id"])
    if primary_id is None:
        return None
    primary = rows.get(primary_id)
    ignored = {"id", "unsupported_effects"}
    if primary is None or {k: v for k, v in row.items() if k not in ignored} != {
        k: v for k, v in primary.items() if k not in ignored
    }:
        raise ValueError(f"Reviewed equipment form differs from primary: {row['id']}")
    return primary


@dataclass(frozen=True)
class EquipmentCatalog:
    items: Mapping[int, EquipmentDefinition]
    revision: str = "custom"
    community_items: Mapping[int, dict[str, Any]] = field(default_factory=dict)
    community_provenance: str = ""
    community_assumptions: Mapping[int, tuple[str, ...]] = field(default_factory=dict)
    verified_catalog: EquipmentCatalog | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", MappingProxyType(dict(self.items)))
        object.__setattr__(self, "community_items", MappingProxyType(dict(self.community_items)))
        object.__setattr__(
            self, "community_assumptions", MappingProxyType(dict(self.community_assumptions))
        )


def load_catalog(
    content: Content, root: Path | None = None, *, use_requirements_source: bool = True
) -> EquipmentCatalog:
    """Retain physical statistics; only reviewed equal forms may share wear gates."""
    root = root or Path("content/equipment")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload = (root / "catalog.json").read_bytes()
    if sha256(payload).hexdigest() != manifest["catalog_sha256"]:
        raise ValueError("Equipment catalog checksum mismatch")
    source_path = root / "requirements.json"
    source_payload = (
        source_path.read_bytes() if use_requirements_source and source_path.exists() else b""
    )
    source_requirements = {
        int(key): requirement_from_levels(levels, content.skills)
        for key, levels in (json.loads(source_payload)["items"] if source_payload else {}).items()
        # A reduced/custom skill registry cannot evaluate these partial maps.
        if not isinstance(levels, dict) or set(levels) <= set(content.skills) | {"combat"}
    }
    overlays = defaultdict(list)
    for item in content.items.values():
        if item.item_id:
            overlays[item.item_id].append(item)
    rows = json.loads(payload)
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Duplicate physical equipment ID")
    result = {}
    for row in rows:
        row = slayer_review(
            tome_review(hopper_review(elemental_amulet_review(obsidian_review(bolt_review(row)))))
        )
        row = salve_review(row)
        review = DOUBLE_ATTACKS.get(row["id"])
        if review:
            if row["name"] != review[0] or row["slot"] != "weapon" or not row["two_handed"]:
                raise ValueError(f"Reviewed attack physical form changed: {row['id']}")
            row = {
                **row,
                "attack_pattern": review[1],
                "unsupported_effects": []
                if row["unsupported_effects"] == ["Offensive effects have not been validated."]
                else row["unsupported_effects"],
                **(
                    {"attack_styles": ("crush", "stab"), "attack_profiles": DUAL_PROFILES}
                    if row["id"] == 28997
                    else {}
                ),
            }
        powered = powered_review(row["id"])
        powered_charged = powered is not None and (
            row["id"] != powered.uncharged_id or powered.charged_id == powered.uncharged_id
        )
        if powered_charged and powered is not None:
            row = {
                **row,
                "powered_attack": powered.model,
                "powered_attack_model": powered.model,
                "powered_attack_stances": ("accurate", "longrange"),
                "attack_styles": ("magic",),
                "attack_profiles": (("magic", "accurate"), ("magic", "longrange")),
                "attack_speed": powered.speed,
                "unsupported_effects": [
                    effect
                    for effect in row["unsupported_effects"]
                    if effect != "Offensive effects have not been validated."
                ],
            }
        elif row["id"] == 22516:
            row = {
                **row,
                "unsupported_effects": ["Dawnbringer requires its raid encounter context."],
            }
        revenant = REVENANT_FORMS.get(row["id"])
        row = revenant_review(row)
        row = size_damage_review(
            dragonbane_review(demonbane_review(halberd_review(leafy_review(row))))
        )
        if row["id"] == 12931:
            if row["slot"] != "head" or row["name"] != "Serpentine helm":
                raise ValueError("Reviewed serpentine physical form changed")
            row = {
                **row,
                "unsupported_effects": [
                    e
                    for e in row["unsupported_effects"]
                    if e != "Offensive effects have not been validated."
                ],
            }
        entries = overlays.get(row["id"], [])
        primary = _reviewed_equivalent(row, by_id)
        if primary is not None:
            entries = [
                *entries,
                *(
                    item
                    for item in overlays.get(primary["id"], [])
                    if row["id"] in item.variant_item_ids
                ),
            ]
            if row["unsupported_effects"] == ["Offensive effects have not been validated."]:
                row = {**row, "unsupported_effects": primary["unsupported_effects"]}
        requirements = tuple(item.requires for item in entries if item.requires is not None)
        requirement = (
            AllOf(children=requirements)
            if len(requirements) > 1
            else requirements[0]
            if requirements
            else None
        )
        # An authored overlay (including approved ungated or unknown) always wins.
        # Community skill maps cannot certify absent quest/unlock gates.
        if not entries:
            requirement = source_requirements.get(row["id"])
        if review:
            reviewed_requirements = tuple(SkillLeaf(skill=k, level=v) for k, v in review[2])
            requirement = AllOf(
                children=(
                    *((requirement,) if requirement is not None else ()),
                    *reviewed_requirements,
                )
            )
        if powered is not None:
            # Equipment access is a wear gate; crafting/drop requirements are not.
            requirement = SkillLeaf(skill="magic", level=powered.level)
        if revenant is not None:
            requirement = SkillLeaf(skill=revenant.skill, level=revenant.level)
        if row["id"] == 32879:
            requirement = SkillLeaf(skill="ranged", level=60)
        if row["id"] == COLOSSAL_BLADE:
            requirement = SkillLeaf(skill="attack", level=60)
        if row["id"] in ELEMENTAL_AMULETS:
            requirement = SkillLeaf(skill="magic", level=59)
        if row["id"] in SALVE_FORMS:
            requirement = MembersLeaf(members=True)
        if row["id"] in BOLT_REQUIREMENTS:
            requirement = SkillLeaf(skill="ranged", level=BOLT_REQUIREMENTS[row["id"]])
        if row["id"] in TOME_FORMS:
            requirement = SkillLeaf(skill="magic", level=50)
        if row["id"] in SLAYER_FORMS:
            if row["slot"] == "weapon":
                gates = {"magic": 75 if row["id"] == 21255 else 50, "slayer": 55}
            elif row["name"].startswith("Black mask"):
                gates = {"defence": 10, "strength": 20, "combat": 40}
            else:
                gates = {"defence": 10}
            requirement = requirement_from_levels(gates, set(content.skills) | set(gates))
        if row["id"] in LEAFY_REQUIREMENTS:
            leafy_gates = LEAFY_REQUIREMENTS[row["id"]]
            requirement = requirement_from_levels(
                dict(leafy_gates), set(content.skills) | set(leafy_gates)
            )
        if row["id"] in HALBERD_FORMS:
            requirement = halberd_requirement(row["id"])
        if row["id"] in DEMONBANE_REQUIREMENTS:
            demonbane_gates = DEMONBANE_REQUIREMENTS[row["id"]]
            requirement = (
                requirement_from_levels(
                    dict(demonbane_gates), set(content.skills) | set(demonbane_gates)
                )
                if demonbane_gates
                else None
            )
        if row["id"] in DRAGONBANE_FORMS:
            requirement = dragonbane_requirement(row["id"])
        acquisition = {item.acquisition for item in entries}
        result[row["id"]] = EquipmentDefinition.model_validate(
            {
                **row,
                "spell_compatibility": (
                    _reviewed_spells(row["id"]) or row.get("spell_compatibility", ())
                ),
                "requires": requirement,
                "requirements_complete": bool(
                    entries
                    or row["id"] in DRAGONBANE_FORMS
                    or row["id"] in DEMONBANE_FORMS
                    or row["id"] in LEAFY_FORMS
                    or row["id"] in HALBERD_FORMS
                    or row["id"] in SLAYER_FORMS
                    or row["id"] in SALVE_FORMS
                    or review
                    or powered
                    or revenant
                    or row["id"] in BOLT_REQUIREMENTS
                    or row["id"] in ELEMENTAL_AMULETS
                    or row["id"] in TOME_FORMS
                    or row["id"] in {32879, 12931, COLOSSAL_BLADE}
                )
                and not any(i.gate_unknown for i in entries),
                "tradeable": (
                    False
                    if row["id"] in {12931, COLOSSAL_BLADE} or row["id"] in SALVE_FORMS
                    else row["id"] in DRAGONBANE_TRADEABLE
                    if row["id"] in DRAGONBANE_FORMS
                    else row["id"] in HALBERD_TRADEABLE
                    if row["id"] in HALBERD_FORMS
                    else row["id"] in DEMONBANE_TRADEABLE
                    if row["id"] in DEMONBANE_FORMS
                    else row["id"] in LEAFY_TRADEABLE
                    if row["id"] in LEAFY_FORMS
                    else (row["id"] == 4170 or row["name"] == "Black mask")
                    if row["id"] in SLAYER_FORMS
                    else row["id"] in TOME_MARKET_FORMS
                    if row["id"] in TOME_FORMS
                    else True
                    if row["id"] in ELEMENTAL_AMULETS or row["id"] == 32879
                    else row["id"] in BOLT_TRADEABLE
                    if row["id"] in BOLT_REQUIREMENTS
                    else row["id"] == revenant.uncharged_id
                    if revenant is not None
                    else row["id"] in REVIEWED_POWERED_TRADEABLE
                    if powered is not None
                    else True
                    if acquisition == {"tradeable"}
                    else False
                    if acquisition == {"untradeable"}
                    else (row["id"] in {28997, 29889, 29084, 4747} if review else None)
                ),
                "content_ids": tuple(item.id for item in entries),
            }
        )
    community_path = root / "community.json"
    community_payload = community_path.read_bytes() if community_path.exists() else b""
    community = json.loads(community_payload) if community_payload else {}
    evidence = community.get("provenance", {})
    community_matches = (
        evidence.get("catalog_sha256") == sha256(payload).hexdigest()
        and bool(source_payload)
        and evidence.get("requirements_sha256") == sha256(source_payload).hexdigest()
    )
    reviewed_spells = json.dumps(
        {
            str(item_id): list(_reviewed_spells(item_id))
            for item_id in sorted(REVIEWED_STANDARD_STAVES | REVIEWED_ANCIENT_STAVES | IBAN_STAVES)
        },
        sort_keys=True,
    ).encode("utf-8")
    equivalent_reviews = json.dumps(dict(REVIEWED_EQUIVALENT_FORMS), sort_keys=True).encode()
    revision = (
        sha256(
            payload
            + source_payload
            + community_payload
            + reviewed_spells
            + equivalent_reviews
            + POWERED_REVISION
            + REVENANT_REVISION
            + OBSIDIAN_REVISION
            + TOME_REVISION
            + ELEMENTAL_AMULET_REVISION
            + BOLT_REVISION
            + HOPPER_REVISION
            + SLAYER_REVISION
            + SALVE_REVISION
            + LEAFY_REVISION
            + b"halberd-status-v1-serp12931"
            + HALBERD_REVISION
            + DEMONBANE_REVISION
            + DRAGONBANE_REVISION
            + SIZE_DAMAGE_REVISION
            + json.dumps(sorted(REVIEWED_POWERED_TRADEABLE)).encode()
            + json.dumps(dict(DOUBLE_ATTACKS), sort_keys=True).encode()
            + json.dumps(DUAL_PROFILES).encode()
        ).hexdigest()
        if source_payload or community_payload
        else sha256(
            payload
            + reviewed_spells
            + equivalent_reviews
            + POWERED_REVISION
            + REVENANT_REVISION
            + OBSIDIAN_REVISION
            + TOME_REVISION
            + ELEMENTAL_AMULET_REVISION
            + BOLT_REVISION
            + HOPPER_REVISION
            + SLAYER_REVISION
            + SALVE_REVISION
            + LEAFY_REVISION
            + b"halberd-status-v1-serp12931"
            + HALBERD_REVISION
            + DEMONBANE_REVISION
            + DRAGONBANE_REVISION
            + SIZE_DAMAGE_REVISION
            + json.dumps(sorted(REVIEWED_POWERED_TRADEABLE)).encode()
            + json.dumps(dict(DOUBLE_ATTACKS), sort_keys=True).encode()
            + json.dumps(DUAL_PROFILES).encode()
        ).hexdigest()
    )
    return EquipmentCatalog(
        result,
        revision,
        # A stale classification cannot bless changed physical/requirement data.
        community_items={int(k): v for k, v in community.get("items", {}).items()}
        if community_matches
        else {},
        community_provenance=sha256(community_payload).hexdigest() if community_matches else "",
    )


load_equipment_catalog = load_catalog
