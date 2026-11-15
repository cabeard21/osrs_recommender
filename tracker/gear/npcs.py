"""Pinned, inspectable NPC records and conservative ordinary-attack capability review."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from tracker.gear.leafy import NPC_SLAYER
from tracker.gear.leafy import REVISION as LEAFY_REVISION
from tracker.gear.models import CombatTarget

if TYPE_CHECKING:
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig

ROOT = Path("content/npcs")
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parents[2] / "content" / "npcs"

# These describe NPC families or equipment affinities. Equipment-specific effects
# remain gated by the equipment evaluator, rather than disabling ordinary hits.
ORDINARY_ATTRIBUTES = frozenset(
    {"undead", "demon", "dragon", "fiery", "golem", "kalphite", "rat", "shade", "spectral", "leafy"}
)
MECHANICAL_ATTRIBUTES = {
    "vampyre1": "Vampyre targets have weapon-specific damage adjustments.",
    "vampyre2": "Vampyre targets restrict weapons and damage.",
    "vampyre3": "Vampyre targets require vampyrebane weapon restrictions.",
    "penance": "Penance targets require Barbarian Assault role and damage rules.",
    "xerician": "Xerician targets require raid scaling and encounter rules.",
    "flying": "Flying targets require attack-style reach and immunity rules.",
}


class NpcCatalog:
    def __init__(self, root: Path = ROOT):
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        payload = (root / "monsters.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest["catalog_sha256"]:
            raise ValueError("NPC catalog checksum mismatch")
        status_path = root / "status_immunities.json"
        status_payload = status_path.read_bytes() if status_path.exists() else b""
        self.status_facts = json.loads(status_payload).get("items", {}) if status_payload else {}
        self.revision = hashlib.sha256(
            payload
            + status_payload
            + json.dumps(manifest.get("reviewed_profiles", {}), sort_keys=True).encode()
            + json.dumps(manifest.get("mechanic_exceptions", {}), sort_keys=True).encode()
            + b"ordinary-npc-traits-v7-halberd-status"
            + LEAFY_REVISION
        ).hexdigest()
        self.entries: dict[str, dict[str, Any]] = {}
        rows = json.loads(payload)
        identities: dict[tuple[Any, Any, Any], set[str]] = {}
        for row in rows:
            identity_tuple = (row["id"], row["name"], row.get("version", ""))
            identities.setdefault(identity_tuple, set()).add(json.dumps(row, sort_keys=True))
        for row in rows:
            source_identity = (row["id"], row["name"], row.get("version", ""))
            identity = json.dumps(source_identity, ensure_ascii=True)
            if len(identities[source_identity]) > 1:
                # Ambiguous upstream identity: preserve both records without conflating them.
                identity += hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            key = hashlib.sha256(identity.encode()).hexdigest()[:24]
            if key in self.entries:
                continue  # Identical source duplicates carry no distinct identity.
            self.entries[key] = self._entry(key, row, manifest)

    def _entry(self, key: str, row: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        skills, defence = row.get("skills", {}), row.get("defensive", {})
        required = [skills.get("def"), skills.get("magic")] + [
            defence.get(k)
            for k in ("stab", "slash", "crush", "magic", "light", "standard", "heavy")
        ]
        reasons = []
        review = manifest.get("reviewed_profiles", {}).get(str(row["id"]))
        if review and (
            review["name"] != row["name"] or review["variant"] != row.get("version", "")
        ):
            review = None
        status = "supported"
        if (row["id"], row["name"]) in {
            (13675, "Acidic Araxyte"),
            (13671, "Mirrorback Araxyte"),
            (13673, "Ruptura Araxyte"),
        }:
            status = "unsupported"
            reasons.append(
                "Araxxor spawn attacks require an encounter review, including "
                "the noxious halberd guaranteed-maximum-hit rule."
            )
        for attribute in row.get("attributes", []):
            if attribute in MECHANICAL_ATTRIBUTES:
                status = "unsupported"
                reasons.append(MECHANICAL_ATTRIBUTES[attribute])
            elif attribute not in ORDINARY_ATTRIBUTES:
                if status == "supported":
                    status = "not_reviewed"
                reasons.append(f"Unknown NPC mechanic attribute: {attribute}.")
        if "leafy" in row.get("attributes", []) and row["id"] not in NPC_SLAYER:
            status = "unsupported"
            reasons.append("Leafy target profile has not been reviewed.")
        exception = manifest.get("mechanic_exceptions", {}).get(str(row["id"]))
        if exception and not (
            row["id"] == 13012
            and row.get("version") == "Regular"
            and exception["reasons"] == ["Target has phase-specific damage rules."]
        ):
            status = "unsupported"
            reasons.extend(exception["reasons"])
        if row["id"] == 13012 and row.get("version") == "Clone":
            status = "unsupported"
            reasons.append(
                "Eclipse Moon Clone accuracy, timing and hitsplat rules are not supported."
            )
        if not all(type(value) is int for value in required):
            status = "unsupported"
            reasons.append("Required combat statistics are missing.")
        variant = row.get("version", "")
        target = None
        if all(type(value) is int for value in required):
            weakness = row.get("weakness") or {}
            try:
                target = CombatTarget(
                    hitpoints=skills.get("hp"),
                    **self.status_facts.get(
                        json.dumps(
                            [row["id"], row["name"], row.get("version", "")], ensure_ascii=True
                        ),
                        {},
                    ),
                    traits=tuple(sorted(set(row.get("attributes", ())) & ORDINARY_ATTRIBUTES)),
                    name=row["name"] + (f" ({variant})" if variant else ""),
                    defence_level=skills["def"],
                    magic_level=skills["magic"],
                    bonuses={k: defence[k] for k in ("stab", "slash", "crush", "magic")}
                    | {"ranged": defence["standard"]},
                    ranged_light=defence["light"],
                    ranged_standard=defence["standard"],
                    ranged_heavy=defence["heavy"],
                    weakness_element=weakness.get("element"),
                    weakness_percent=weakness.get("severity", 0),
                    flat_armour=defence.get("flat_armour", 0),
                    damage_cap=50 if row["name"] == "Zulrah" else None,
                    unsupported_mechanics=tuple(reasons) if status != "supported" else (),
                ).model_dump(mode="json")
            except ValueError:
                status, reasons = "unsupported", ["Combat statistics exceed supported bounds."]
        return {
            "key": key,
            "npc_id": row["id"],
            "name": row["name"],
            "variant": variant,
            "combat_level": row.get("level"),
            "support_status": status,
            "reasons": reasons,
            "catalog_revision": self.revision,
            "source_url": manifest["source_url"],
            "wiki_url": "https://oldschool.runescape.wiki/w/"
            + quote(row["name"].replace(" ", "_")),
            "limitations": [
                "Ordinary attacks only; Moon curses, healing, survival and encounter "
                "downtime are not simulated."
            ]
            if row["id"] in {13011, 13012, 13013}
            else review.get("limitations", [])
            if review
            else [
                "Ordinary direct attacks using catalog base stats only; encounter phases, "
                "survival and movement are not simulated. Status damage uses reviewed "
                "susceptibility and duration. "
                "Slayer bonuses require explicit task context.",
                "Family attributes do not enable unsupported equipment effects.",
            ],
            "target": target,
            "source_record": row,
        }

    def detail(self, key: str) -> dict[str, Any]:
        if key not in self.entries:
            raise ValueError("NPC target not found; reselect a target.")
        return self.entries[key]

    def search(self, query: str = "", offset: int = 0, limit: int = 20) -> dict[str, Any]:
        query = query.strip().casefold()
        rows = [
            e
            for e in self.entries.values()
            if not query
            or query in (e["name"] + " " + e["variant"]).casefold()
            or query == str(e["npc_id"])
        ]
        rows.sort(
            key=lambda e: (
                0
                if query in (e["name"].casefold(), str(e["npc_id"]))
                else 1
                if e["name"].casefold().startswith(query)
                else 2,
                e["name"].casefold(),
                e["variant"],
                e["key"],
            )
        )
        return {
            "catalog_revision": self.revision,
            "items": [
                {k: v for k, v in e.items() if k not in ("target", "source_record")}
                for e in rows[offset : offset + limit]
            ],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
        }


@lru_cache(maxsize=1)
def npc_catalog() -> NpcCatalog:
    return NpcCatalog()


def resolve_target(role: RoleConfig) -> RoleConfig:
    selection = role.target_selection
    if selection is None:
        return role
    catalog = npc_catalog()
    if selection.catalog_revision != catalog.revision:
        raise ValueError("NPC catalog revision changed; refresh and reselect the target.")
    entry = catalog.detail(selection.key)
    if (
        role.allowed_disciplines is None
        and entry["npc_id"] in {2042, 2043, 2044}
        and role.style in {"stab", "slash", "crush"}
    ):
        raise ValueError("Zulrah is immune to melee damage; choose a ranged or magic role.")
    if entry["support_status"] != "supported":
        raise ValueError(
            "NPC mechanics unsupported or not reviewed: " + "; ".join(entry["reasons"])
        )
    canonical = CombatTarget.model_validate(entry["target"])
    effective = role.target or canonical
    # Older saved targets have no HP metadata; the selected NPC owns base HP.
    effective = CombatTarget.model_validate(
        {
            **effective.model_dump(),
            "hitpoints": canonical.hitpoints,
        }
    )
    for field in (
        "damage_cap",
        "flat_armour",
        "unsupported_mechanics",
        "traits",
        "poison_susceptibility",
        "venom_susceptibility",
    ):
        if getattr(effective, field) != getattr(canonical, field):
            raise ValueError("NPC mechanic restrictions cannot be overridden.")
    return role.model_copy(update={"target": effective})


def discipline_problem(role: RoleConfig) -> str | None:
    """Concrete target immunity; Auto placeholders are resolved before search."""
    if role.target_selection is None or role.style not in {"stab", "slash", "crush"}:
        return None
    entry = npc_catalog().detail(role.target_selection.key)
    if entry["npc_id"] in {2042, 2043, 2044}:
        return "Zulrah is immune to melee damage; choose a ranged or magic role."
    return None


def resolve_request(request: OptimizationRequest | Mapping[str, Any]) -> OptimizationRequest:
    from tracker.gear.optimizer import OptimizationRequest

    normalized = (
        request
        if isinstance(request, OptimizationRequest)
        else OptimizationRequest.model_validate(request)
    )
    return normalized.model_copy(
        update={"roles": tuple(resolve_target(role) for role in normalized.roles)}
    )
