"""Offline exact-ID equipment proposals, validation and approved application.

Run with ``python -m tools.bulk_review_gear --help`` from the repository root.
Family patterns discover items; only independently sourced exact-ID claims can
produce overlays. Neither discovery nor proposal generation clears effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path

from tracker.content.loader import load_content
from tracker.content.schema import Item
from tracker.content.validate import validate_content
from tracker.gear.catalog import load_catalog

GENERIC = ["Offensive effects have not been validated."]


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def physical(row) -> dict:
    return {k: v for k, v in row.items() if k != "unsupported_effects"}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wear_requirements(family: dict, evidence: list[str]):
    """Conservative, family-supplied grammar for explicit wear statements only."""
    plain = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", " ".join(evidence))
    skills: dict[str, set[int]] = {}
    for rule in family.get("wear_patterns", []):
        values = {int(m["level"]) for m in re.finditer(rule["pattern"], plain, re.I)}
        if values:
            skills[rule["skill"]] = skills.get(rule["skill"], set()) | values
    if any(len(values) != 1 for values in skills.values()):
        raise ValueError("Ambiguous wear requirements")
    parts = [{"skill": {k: next(iter(v)) for k, v in skills.items()}}] if skills else []
    parts += [
        {"quest": rule["quest"]}
        for rule in family.get("quest_patterns", [])
        if re.search(rule["pattern"], plain, re.I)
    ]
    if not parts:
        pattern = family.get("ungated_pattern")
        if not pattern or not re.search(pattern, plain, re.I):
            raise ValueError("Missing or ambiguous wear requirements")
        return None
    return parts[0] if len(parts) == 1 else {"all_of": parts}


def local(root: Path, path: str) -> Path:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Source path must stay inside repository")
    return resolved


def context(root: Path, family_path: Path):
    family = read(family_path)
    if family["schema_version"] != 1 or not re.fullmatch(r"[a-z][a-z0-9_]*", family["id"]):
        raise ValueError("Invalid family identity/schema")
    source_path = local(root, family["source_file"])
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != family["source_sha256"]:
        raise ValueError("Source capture checksum mismatch")
    sources = read(source_path)
    rows = read(root / "content/equipment/catalog.json")
    provenance = read(root / "content/equipment/manifest.json")
    if (
        hashlib.sha256((root / "content/equipment/catalog.json").read_bytes()).hexdigest()
        != provenance["catalog_sha256"]
    ):
        raise ValueError("Catalog checksum mismatch")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate physical IDs")
    if sources["equipment_source"] != {
        k: provenance[k] for k in ("source", "revision", "capture_sha256")
    }:
        raise ValueError("Pinned equipment source mismatch")
    overlay = f"content/items/bulk_{family['id']}.yaml"
    authored = {
        p.relative_to(root).as_posix(): hashlib.sha256(
            p.read_text(encoding="utf-8").encode()
        ).hexdigest()
        for folder in ("items", "skills", "quests")
        for p in sorted((root / "content" / folder).rglob("*"))
        if p.suffix in (".yaml", ".yml") and p != root / overlay
    }
    inputs = {
        "family_sha256": digest(family),
        "source_sha256": family["source_sha256"],
        "physical_catalog_sha256": digest([physical(r) for r in rows]),
        "authored_sha256": digest(authored),
        "equipment_source": sources["equipment_source"],
    }
    return family, sources, rows, inputs, overlay


def source_entry(row: dict, family: dict, sources: dict) -> dict:
    """Bind a structured transcription to pinned page bytes and physical export."""
    claim = family["items"].get(str(row["id"]))
    base = {
        "item_id": row["id"],
        "physical": physical(row),
        "overlay": None,
        "classification": "manual_review_exception",
        "sources": [sources["equipment_source"]],
        "reasons": [
            family.get("exceptions", {}).get(
                str(row["id"]), "No exact-ID source-backed wear/effects review."
            )
        ],
        "decision": "pending",
        "review_reason": "",
    }
    if claim is None:
        return base
    page = sources["pages"][str(row["id"])]
    text = page["wikitext"]
    if hashlib.sha256(text.encode()).hexdigest() != page["sha256"]:
        raise ValueError("Wiki page checksum mismatch")

    def fields(key):
        return re.findall(r"^\|\s*" + key + r"\s*=\s*([^\n]+)", text, re.M)

    if fields("id") != [str(row["id"])] or fields("name") != [row["name"]]:
        raise ValueError("Wiki physical identity mismatch")
    if page["title"] != row["name"] or not isinstance(page["revision"], int):
        raise ValueError("Wiki title/revision mismatch")
    if (
        page["url"]
        != f"https://oldschool.runescape.wiki/w/Special:PermanentLink/{page['revision']}"
    ):
        raise ValueError("Wiki permanent reference mismatch")
    from tools.import_equipment import normalize

    exports = [r for r in sources["equipment_rows"] if r["id"] == row["id"]]
    if len(exports) != 1 or digest(physical(normalize(exports[0], bulk_reviews={}))) != digest(
        physical(row)
    ):
        raise ValueError("Pinned physical statistics differ")
    # New families can omit transcriptions where their conservative grammar
    # recognises explicit wear prose. Exact-ID mechanics review remains required.
    automatic_evidence = [
        p
        for p in text.split("==Combat stats==")[0].split("\n\n")
        if re.search(r"\b(?:wear|worn|equip)\b", p, re.I) and "{{Infobox" not in p
    ]
    evidence = claim.get("wear_evidence", automatic_evidence)
    try:
        extracted = wear_requirements(family, evidence)
    except ValueError:
        if "wear_evidence" in claim:
            raise
        return {**base, "reasons": ["No unambiguous wear statement recognised by family grammar."]}
    claim = {
        "requires": extracted,
        "acquisition": ("tradeable" if fields("tradeable") == ["Yes"] else "untradeable"),
        "wear_evidence": evidence,
        **claim,
    }
    acquisition = claim["acquisition"]
    if acquisition not in ("tradeable", "untradeable") or fields("tradeable") != [
        "Yes" if acquisition == "tradeable" else "No"
    ]:
        raise ValueError("Acquisition source mismatch")
    if not claim["wear_evidence"] or any(q not in text for q in claim["wear_evidence"]):
        raise ValueError("Wear evidence missing from source")
    if claim["requires"] != wear_requirements(family, claim["wear_evidence"]):
        raise ValueError("Structured wear requirements differ from source evidence")
    if not claim["review_reason"].strip():
        raise ValueError("Missing source review reason")
    classification = claim["classification"]
    mechanics = claim["mechanics"]
    reasons = [claim["review_reason"]]
    # Detection is deliberately advisory. Absence of a keyword is never approval.
    flags = sorted(
        set(
            re.findall(
                r"\b(?:special attack|set effect|passive effect|charged|degrades|"
                r"poison|conditional)\b",
                text.split("==Changes==")[0],
                re.I,
            )
        )
    )
    if mechanics != "ordinary" or flags or row["unsupported_effects"] not in (GENERIC, []):
        classification = "manual_review_exception"
        reasons += [f"Mechanics require manual review: {mechanics}; detected={flags}"]
    if classification not in ("ordinary", "verified_variant", "manual_review_exception"):
        raise ValueError("Unknown classification")
    if classification == "verified_variant":
        primary = claim.get("variant_of")
        originals = [r for r in sources["equipment_rows"] if r["id"] == primary]

        def comparable(r):
            return {k: v for k, v in r.items() if k not in ("id", "name")}

        if len(originals) != 1 or comparable(exports[0]) != comparable(originals[0]):
            raise ValueError("Variant differs from reviewed physical reference")
        reasons += [f"Independent exact-ID gates; physical comparison with {primary}."]
    overlay = {
        "id": f"bulk_{family['id']}_{row['id']}",
        "name": row["name"],
        "item_id": row["id"],
        "slot": row["slot"],
        "requires": claim["requires"],
        "acquisition": acquisition,
        "price_mode": "live",
        "price_staleness_days": 30,
    }
    Item.model_validate(overlay)
    return {
        **base,
        "classification": classification,
        "reasons": reasons,
        "sources": [
            {k: page[k] for k in ("url", "revision", "sha256")},
            sources["equipment_source"],
        ],
        "overlay": overlay if classification != "manual_review_exception" else None,
    }


def propose(root: Path, family_path: Path, include_reviewed: bool = False) -> dict:
    family, sources, rows, inputs, _ = context(root, family_path)
    catalog = load_catalog(load_content(root / "content"), root / "content/equipment")
    matches = [
        r
        for r in rows
        if re.search(family["name_pattern"], r["name"], re.I) and r["slot"] in family["slots"]
    ]
    entries = [
        source_entry(r, family, sources)
        for r in sorted(matches, key=lambda r: r["id"])
        if include_reviewed
        or not (
            catalog.items[r["id"]].requirements_complete
            and not catalog.items[r["id"]].unsupported_effects
        )
    ]
    return {
        "schema_version": 1,
        "family": family["id"],
        "inputs": inputs,
        "entries": entries,
        "proposed_effect_clearance": [
            e["item_id"] for e in entries if e["classification"] != "manual_review_exception"
        ],
        "approved_effect_clearance": [],
    }


def coverage(root: Path) -> dict:
    catalog = load_catalog(load_content(root / "content"), root / "content/equipment")
    return {
        "physical_ids": len(catalog.items),
        "requirements_complete": sum(i.requirements_complete for i in catalog.items.values()),
        "effects_cleared": sum(not i.unsupported_effects for i in catalog.items.values()),
        "metadata_supported": sum(
            i.requirements_complete and not i.unsupported_effects for i in catalog.items.values()
        ),
    }


def validate(root: Path, family_path: Path, manifest: dict) -> dict[str, bytes]:
    family, sources, rows, inputs, overlay_path = context(root, family_path)
    if set(manifest) != {
        "schema_version",
        "family",
        "inputs",
        "entries",
        "proposed_effect_clearance",
        "approved_effect_clearance",
    }:
        raise ValueError("Unexpected manifest fields")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("family") != family["id"]
        or manifest.get("inputs") != inputs
    ):
        raise ValueError("Manifest schema, identity or input/source consistency mismatch")
    entries = manifest["entries"]
    ids = [e["item_id"] for e in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate manifest IDs")
    by_id = {r["id"]: r for r in rows}
    for entry in entries:
        row = by_id[entry["item_id"]]
        if (
            not re.search(family["name_pattern"], row["name"], re.I)
            or row["slot"] not in family["slots"]
        ):
            raise ValueError("Item outside family")
        expected = source_entry(row, family, sources)
        if {**entry, "decision": "pending", "review_reason": ""} != expected:
            raise ValueError("Proposal differs from exact-ID source/physical evidence")
        if entry["decision"] not in ("pending", "approved", "rejected"):
            raise ValueError("Invalid review decision")
    proposed = [e["item_id"] for e in entries if e["classification"] != "manual_review_exception"]
    if manifest["proposed_effect_clearance"] != proposed:
        raise ValueError("Proposed effects list mismatch")
    approved = [e for e in entries if e["decision"] == "approved"]
    approved_ids = [e["item_id"] for e in approved]
    effects = manifest["approved_effect_clearance"]
    if len(set(effects)) != len(effects) or set(effects) != set(approved_ids):
        raise ValueError("Separate exact-ID effect approval required")
    if any(e["overlay"] is None or not e["review_reason"].strip() for e in approved):
        raise ValueError("Unsupported mechanics or absent explicit review reason")
    content = load_content(root / "content")
    generated_ids = {e["overlay"]["id"] for e in approved}
    generated = root / overlay_path
    if generated.exists():
        previous = read(generated)
        if previous != [e["overlay"] for e in approved]:
            raise ValueError("Existing applied family differs; use a new batch family ID")
    for item_id in generated_ids & content.items.keys():
        if content.location_of("item", item_id).file.resolve() != generated.resolve():
            raise ValueError("Generated authored ID collides with existing content")
    retained = {k: v for k, v in content.items.items() if k not in generated_ids}
    for existing in retained.values():
        if set(existing.owned_item_ids) & set(approved_ids):
            raise ValueError("Conflicting existing exact-ID/variant overlay")
    new_items = {e["overlay"]["id"]: Item.model_validate(e["overlay"]) for e in approved}
    errors = validate_content(replace(content, items={**retained, **new_items}))
    if errors:
        raise ValueError(f"Invalid authored content: {errors}")
    registry_path = f"content/equipment/reviews/applied/{family['id']}.json"
    if (root / registry_path).exists() and read(root / registry_path) != manifest:
        raise ValueError("Existing review registry differs")
    if not approved:
        return {}
    updated_rows = [
        {**r, "unsupported_effects": []} if r["id"] in approved_ids else r for r in rows
    ]
    payload = (json.dumps(updated_rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    provenance = read(root / "content/equipment/manifest.json")
    return {
        overlay_path: encoded([e["overlay"] for e in approved]),
        registry_path: encoded(manifest),
        "content/equipment/catalog.json": payload,
        "content/equipment/manifest.json": encoded(
            {**provenance, "catalog_sha256": hashlib.sha256(payload).hexdigest()}
        ),
    }


def apply(root: Path, family_path: Path, manifest: dict) -> None:
    """Validate first; stage all bytes, restoring originals on replacement failure.

    A process kill/power loss during multi-file replacement still needs restoring
    the catalog/manifest pair from version control before retrying.
    """
    outputs = validate(root, family_path, manifest)
    originals = {
        relative: (root / relative).read_bytes() if (root / relative).exists() else None
        for relative in outputs
    }
    with tempfile.TemporaryDirectory(prefix="gear-review-", dir=root) as staging:
        staged = {relative: Path(staging) / str(i) for i, relative in enumerate(outputs)}
        for relative, payload in outputs.items():
            staged[relative].write_bytes(payload)
        changed = []
        try:
            for relative, payload in outputs.items():
                if originals[relative] == payload:
                    continue
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                staged[relative].replace(target)
                changed.append(relative)
        except OSError:
            for relative in reversed(changed):
                target = root / relative
                if originals[relative] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(originals[relative])
            raise
    from tools.import_equipment import bulk_reviewed_rows

    bulk_reviewed_rows.cache_clear()


def report(manifest: dict) -> str:
    lines = [
        f"# {manifest['family']} equipment review",
        "",
        "Discovery is not approval. Exact physical IDs only.",
        "",
        "| ID | Item | Classification | Decision | Wear/acquisition | Source | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {e['item_id']} | {e['physical']['name']} | {e['classification']} | "
        f"{e['decision']} | {json.dumps(e['overlay']['requires']) if e['overlay'] else 'unknown'}"
        f" / {e['overlay']['acquisition'] if e['overlay'] else 'unknown'} | "
        f"[pinned source]({e['sources'][0].get('url', e['sources'][0].get('source'))}) | "
        f"{'; '.join(e['reasons'])} |"
        for e in manifest["entries"]
    ]
    lines += [
        "",
        f"Proposed effect clearances: {manifest['proposed_effect_clearance']}",
        f"Approved effect clearances: {manifest['approved_effect_clearance']}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("propose", "validate", "apply", "coverage"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--family", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--include-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "coverage":
            print(json.dumps(coverage(args.root), indent=2))
            return
        if args.family is None or args.manifest is None:
            parser.error("--family and --manifest required")
        if args.command == "propose":
            result = propose(args.root, args.family, args.include_reviewed)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_bytes(encoded(result))
        else:
            result = read(args.manifest)
            if args.command == "apply":
                apply(args.root, args.family, result)
            else:
                validate(args.root, args.family, result)
        if args.report:
            args.report.write_text(report(result), encoding="utf-8")
        print(
            f"{args.command}: {len(result['entries'])} entries; "
            f"{len(result['approved_effect_clearance'])} approved"
        )
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Bulk review rejected: {exc}\n")


if __name__ == "__main__":
    main()
