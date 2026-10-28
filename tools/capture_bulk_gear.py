"""Explicit maintenance-time source capture for bulk_review_gear families.

This writes evidence only. It never writes family approvals or runtime content.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import httpx

from tools.bulk_review_gear import encoded, read


def capture(root: Path, family: dict) -> dict:
    provenance = read(root / "content/equipment/manifest.json")
    revision = provenance["revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Capture needs the existing pinned equipment revision")
    rows = read(root / "content/equipment/catalog.json")
    matches = {
        r["id"]: r
        for r in rows
        if re.search(family["name_pattern"], r["name"], re.I) and r["slot"] in family["slots"]
    }
    pages = {}
    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "osrs-account-companion bulk equipment review"},
    ) as client:
        response = client.get(
            f"https://raw.githubusercontent.com/weirdgloop/osrs-dps-calc/"
            f"{revision}/cdn/json/equipment.json"
        )
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != provenance["capture_sha256"]:
            raise ValueError("Pinned upstream capture checksum mismatch")
        exports = [r for r in response.json() if r["id"] in matches]
        names = sorted({r["name"] for r in matches.values()})
        for offset in range(0, len(names), 50):
            response = client.get(
                "https://oldschool.runescape.wiki/api.php",
                params={
                    "action": "query",
                    "prop": "revisions",
                    "format": "json",
                    "formatversion": 2,
                    "titles": "|".join(names[offset : offset + 50]),
                    "rvprop": "ids|timestamp|content",
                    "rvslots": "main",
                },
            )
            response.raise_for_status()
            for page in response.json()["query"]["pages"]:
                if "revisions" not in page:
                    continue
                rev = page["revisions"][0]
                text = rev["slots"]["main"]["content"]
                ids = re.findall(r"^\|\s*id\s*=\s*(\d+)\s*$", text, re.M)
                if len(ids) != 1:
                    continue  # Ambiguous/multi-form infoboxes require separate evidence.
                item_id = int(ids[0])
                if item_id not in matches or page["title"] != matches[item_id]["name"]:
                    continue
                pages[str(item_id)] = {
                    "title": page["title"],
                    "revision": rev["revid"],
                    "timestamp": rev["timestamp"],
                    "url": f"https://oldschool.runescape.wiki/w/Special:PermanentLink/{rev['revid']}",
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "wikitext": text,
                }
    return {
        "schema_version": 1,
        "equipment_source": {k: provenance[k] for k in ("source", "revision", "capture_sha256")},
        "equipment_rows": exports,
        "pages": pages,
        **{k: provenance[k] for k in ("attribution", "source_license", "license_urls")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--family", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.root, read(args.family))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded(result))
    print(f"Captured {len(result['pages'])} exact-ID Wiki pages; no approvals changed")


if __name__ == "__main__":
    main()
