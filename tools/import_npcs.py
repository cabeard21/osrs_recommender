"""Import a downloaded, revision-pinned Wiki NPC snapshot (never runs at app startup).

python tools/import_npcs.py --source /path/to/monsters.json --revision <40-char-sha>
A refresh clears optional profile notes but preserves the existing mechanic exception
registry. The output directory must contain a manifest with that registry; copy the
bundled manifest first when preparing a new output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path


def mechanic_exceptions(output: Path, parser: argparse.ArgumentParser) -> dict:
    try:
        previous = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot preserve mechanic exceptions from existing output manifest: {exc}")
    exceptions = previous.get("mechanic_exceptions") if isinstance(previous, dict) else None
    if not isinstance(exceptions, dict) or not exceptions:
        parser.error(
            "Existing output manifest must contain a nonempty mechanic_exceptions registry"
        )
    for npc_id, rule in exceptions.items():
        if (
            not npc_id.isdigit()
            or not isinstance(rule, dict)
            or not isinstance(rule.get("source_url"), str)
            or not rule["source_url"]
            or not isinstance(rule.get("reasons"), list)
            or not rule["reasons"]
            or not all(isinstance(reason, str) and reason for reason in rule["reasons"])
        ):
            parser.error(f"Malformed mechanic exception for NPC {npc_id}")
    return exceptions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, default=Path("content/npcs"))
    args = parser.parse_args()
    if not re.fullmatch("[a-f0-9]{40}", args.revision):
        parser.error("--revision must be an exact Git commit SHA")
    exceptions = mechanic_exceptions(args.output, parser)
    payload = args.source.read_bytes()
    rows = json.loads(payload)
    if (
        not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(r, dict) or not {"id", "name", "skills", "defensive"} <= r.keys()
            for r in rows
        )
    ):
        parser.error("source must be a nonempty Wiki monster catalog")
    # Normalize LF before computing the checksum so checkout platform is irrelevant.
    payload = payload.replace(b"\r\n", b"\n")
    manifest = {
        "source_revision": args.revision,
        "source_url": f"https://github.com/weirdgloop/osrs-dps-calc/blob/{args.revision}/cdn/json/monsters.json",
        "catalog_sha256": hashlib.sha256(payload).hexdigest(),
        "imported_at": datetime.now(UTC).isoformat(),
        "attribution": (
            "OSRS Wiki contributors / Weird Gloop. "
            "Source project GPL-3.0; Wiki data CC BY-NC-SA 3.0."
        ),
        "reviewed_profiles": {},
        "mechanic_exceptions": exceptions,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "monsters.json").write_bytes(payload)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
