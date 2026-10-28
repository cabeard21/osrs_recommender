"""Build a small ordinary-equipment policy sidecar from pinned local sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from tools.import_equipment import normalize
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.community import POLICY_VERSION, classify_ordinary


def build(source, physical_rows, captured_rows, catalog, requirements):
    """Preserve all source data and record exclusions, including authored gates."""
    captures = defaultdict(list)
    for row in captured_rows:
        normalized = json.loads(json.dumps(normalize(row, bulk_reviews={})))
        captures[row["id"]].append({**row, "normalized": normalized})
    items, exceptions = {}, {}
    for row in physical_rows:
        key = str(row["id"])
        if catalog.items[row["id"]].content_ids:
            exceptions[key] = "authored_metadata_preserved"
            continue
        if key not in requirements:
            exceptions[key] = "missing_valid_requirement_map"
            continue
        variants = captures.get(row["id"], [])
        if len(variants) != 1:
            exceptions[key] = "missing_or_ambiguous_physical_capture"
            continue
        item, reason = classify_ordinary(row, source.get(key), variants[0])
        if item:
            items[key] = item
        else:
            exceptions[key] = reason
    return items, exceptions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--content", type=Path, default=Path("content"))
    parser.add_argument("--output", type=Path, default=Path("content/equipment/community.json"))
    args = parser.parse_args(argv)
    root = args.content / "equipment"
    if args.output.resolve() != (root / "community.json").resolve():
        parser.error("Output must be the content equipment/community.json sidecar")
    if args.output.resolve() in {args.source.resolve(), args.capture.resolve()}:
        parser.error("Output must not overwrite a source")
    source_raw, capture_raw = args.source.read_bytes(), args.capture.read_bytes()
    physical_raw = (root / "catalog.json").read_bytes()
    requirements_raw = (root / "requirements.json").read_bytes()
    requirements_data = json.loads(requirements_raw)
    if hashlib.sha256(source_raw).hexdigest() != requirements_data["source"]["sha256"]:
        parser.error("Requirements and community source hashes must agree")
    manifest = json.loads((root / "manifest.json").read_bytes())
    if hashlib.sha256(capture_raw).hexdigest() != manifest["capture_sha256"]:
        parser.error("Physical capture must match the catalog manifest")
    catalog = load_catalog(load_content(args.content), root)
    physical_rows = json.loads(physical_raw)
    items, exceptions = build(
        json.loads(source_raw),
        physical_rows,
        json.loads(capture_raw),
        catalog,
        requirements_data["items"],
    )
    plain = [key for key, item in items.items() if not item["cosmetic_variant"]]
    rows_by_id = {str(row["id"]): row for row in physical_rows}
    signatures = {
        json.dumps(
            {
                k: v
                for k, v in rows_by_id[key].items()
                if k not in {"id", "name", "unsupported_effects"}
            },
            sort_keys=True,
        )
        for key in items
    }
    summary = {
        "newly_qualifiable_ids": len(items),
        "noncosmetic_ids": len(plain),
        "cosmetic_variant_ids": len(items) - len(plain),
        "distinct_physical_profiles": len(signatures),
        "by_slot": dict(Counter(rows_by_id[key]["slot"] for key in items)),
        "exclusions": dict(Counter(exceptions.values())),
    }
    payload = {
        "provenance": {
            "policy_version": POLICY_VERSION,
            "source": requirements_data["source"],
            "source_sha256": hashlib.sha256(source_raw).hexdigest(),
            "catalog_sha256": hashlib.sha256(physical_raw).hexdigest(),
            "requirements_sha256": hashlib.sha256(requirements_raw).hexdigest(),
            "physical_capture_sha256": hashlib.sha256(capture_raw).hexdigest(),
        },
        "items": items,
        "summary": summary,
        "exceptions": exceptions,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
