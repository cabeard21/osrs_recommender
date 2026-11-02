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
from tracker.content.requirements import AllOf
from tracker.gear.combat import SPELLS
from tracker.gear.models import EquipmentDefinition
from tracker.gear.requirements_source import requirement_from_levels

# Reviewed ordinary forms only, not general ownership aliases. The pinned Wiki
# equipment_aliases.json maps these Soul Wars/Emir's Arena rings to 11773.
# Their physical rows must still match before sharing requirements/effects review.
REVIEWED_EQUIVALENT_FORMS: Mapping[int, int] = MappingProxyType({25264: 11773, 26770: 11773})

# Exact physical elemental staves with reviewed Standard spellbook autocast.
# https://oldschool.runescape.wiki/w/Autocast
# https://oldschool.runescape.wiki/w/Mystic_air_staff
REVIEWED_STANDARD_STAVES = frozenset({1381, 1387, 1401, 1403, 1405, 1407})


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
        acquisition = {item.acquisition for item in entries}
        result[row["id"]] = EquipmentDefinition.model_validate(
            {
                **row,
                "spell_compatibility": (
                    tuple(SPELLS)
                    if row["id"] in REVIEWED_STANDARD_STAVES
                    else row.get("spell_compatibility", ())
                ),
                "requires": requirement,
                "requirements_complete": bool(entries) and not any(i.gate_unknown for i in entries),
                "tradeable": (
                    True
                    if acquisition == {"tradeable"}
                    else False
                    if acquisition == {"untradeable"}
                    else None
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
        {str(item_id): list(SPELLS) for item_id in sorted(REVIEWED_STANDARD_STAVES)},
        sort_keys=True,
    ).encode("utf-8")
    revision = (
        sha256(payload + source_payload + community_payload + reviewed_spells).hexdigest()
        if source_payload or community_payload
        else sha256(payload + reviewed_spells).hexdigest()
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
