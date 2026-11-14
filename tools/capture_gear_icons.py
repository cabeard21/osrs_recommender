"""Capture missing numeric-ID sprites offline; never called by the application.

Run ``python -m tools.capture_gear_icons --help`` from the repository root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from tracker.content.loader import load_content
from tracker.gear.bolts_catalog import BOLTS, CROSSBOWS
from tracker.gear.catalog import load_catalog
from tracker.gear.leafy import FORMS as LEAFY_FORMS
from tracker.gear.tomes import FORMS as TOME_FORMS

ROOT = Path(__file__).resolve().parent.parent
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIRROR = (
    "https://raw.githubusercontent.com/runelite/static.runelite.net/"
    "gh-pages/cache/item/icon/{item_id}.png"
)


def download(client: httpx.Client, url: str) -> bytes:
    for attempt in range(3):
        try:
            response = client.get(url)
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(PNG_SIGNATURE) or payload[12:16] != b"IHDR":
                raise ValueError("Response is not a PNG image")
            return payload
        except httpx.TransportError:
            if attempt == 2:
                raise
    raise AssertionError("Unreachable")


def capture(root: Path, ids: list[int], *, dry_run: bool = False) -> int:
    folder = root / "tracker/ui/assets/items"
    source_path = folder / "source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    catalog = load_catalog(load_content(root / "content"), root / "content/equipment")
    unknown = set(ids) - catalog.items.keys()
    if unknown:
        raise ValueError(f"IDs absent from physical equipment catalog: {sorted(unknown)}")
    selected = sorted(
        set(ids)
        if ids
        else {i.id for i in catalog.items.values() if i.content_ids}
        | catalog.community_items.keys()
        | BOLTS.keys()
        | CROSSBOWS.keys()
        | TOME_FORMS.keys()
        | LEAFY_FORMS.keys()
    )
    missing = [item_id for item_id in selected if not (folder / f"{item_id}.png").exists()]
    print(f"{len(selected)} selected; {len(missing)} missing sprites")
    if dry_run:
        for item_id in missing:
            print(f"{item_id}: {catalog.items[item_id].name}")
        return 0
    failures = 0
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for item_id in missing:
            for template in (source["source_template"], MIRROR):
                url = template.format(item_id=item_id)
                try:
                    payload = download(client, url)
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"Failed {item_id} from {url}: {exc}")
                    continue
                break
            else:
                failures += 1
                continue
            (folder / f"{item_id}.png").write_bytes(payload)
            source.setdefault("additional_captures", {})[str(item_id)] = {
                "source": url,
                "retrieved_on": datetime.now(UTC).date().isoformat(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            # Save provenance per successful file so interrupted captures can resume.
            source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
            print(f"Added {item_id}: {catalog.items[item_id].name}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "item_ids",
        nargs="*",
        type=int,
        help=(
            "Default: all authored physical forms, community-supported equipment, "
            "and reviewed enchanted bolts/crossbows and tome forms"
        ),
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--dry-run", action="store_true", help="List missing sprites without fetching"
    )
    args = parser.parse_args()
    return capture(args.root, args.item_ids, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
