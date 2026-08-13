"""Resolve item names to numeric ``item_id``s — run **by hand**, never by the app.

``content/items/items.yaml`` needs the numeric id the OSRS Wiki price API is keyed by
(§10.5), and `_check_live_prices` rejects a ``price_mode: live`` item without one. Guessing
that number is the failure this script exists to prevent: "Toxic blowpipe" and "Toxic
blowpipe (empty)" are different items with different ids and near-identical names, and a
plausible-looking wrong id produces a *silently wrong GP estimate* rather than an error.

**This does not belong in** :mod:`tracker.integrations.prices`. The same host serves
``/mapping``, the full item catalog, and §8.3 is explicit that the full item economy is
never pulled at runtime — the one-request-per-scoped-id design in that client's docstring
exists to keep that promise. An authoring-time lookup is a different activity from a
runtime fetch, and ``tools/`` is where the other authoring-time fetches already live
(:mod:`tools.capture_quest_data`, :mod:`tools.capture_diary_data`).

Nothing is written. The output is meant to be read and pasted, so a wrong id has to survive
a human looking at it.

Run::

    python tools/lookup_item_ids.py "Dragon hunter crossbow" "Bandos chestplate"
    python tools/lookup_item_ids.py            # the names this corpus currently wants
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Sequence
from typing import Any

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
USER_AGENT = "osrs-recommender content authoring (offline item id lookup)"

#: The names the PvM ladder added. Kept here so re-running the lookup after a wiki rename
#: is one command rather than an act of recall.
#: No Toxic blowpipe: only ``Toxic blowpipe (empty)`` has a catalog row, because the charged
#: form is untradeable. An ``item:`` leaf naming the empty id would miss every player who
#: owns a charged one, which is the opposite of what the gate means — so the ladder gates on
#: the Rune crossbow instead. This script found that; the guess would not have.
DEFAULT_NAMES: tuple[str, ...] = (
    "Rune crossbow",
    "Bandos chestplate",
    "Armadyl chestplate",
    "Dragon hunter crossbow",
)


def fetch_mapping() -> list[dict[str, Any]]:
    request = urllib.request.Request(MAPPING_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):  # pragma: no cover — run by hand
        raise SystemExit(f"unexpected /mapping payload: {type(payload).__name__}")
    return payload


def resolve(mapping: Sequence[dict[str, Any]], name: str) -> dict[str, Any]:
    """Exact, case-insensitive match. **Zero or several matches is an error, not a pick.**

    Choosing the first of several is how "(empty)", "(uncharged)" and "(c)" variants get
    committed as the base item. There is no heuristic here on purpose: the ambiguity is
    real and belongs in front of the person authoring the file.
    """
    wanted = name.strip().casefold()
    matches = [row for row in mapping if str(row.get("name", "")).casefold() == wanted]
    if not matches:
        near = sorted(
            str(row["name"]) for row in mapping if wanted in str(row.get("name", "")).casefold()
        )
        hint = f" Did you mean: {', '.join(near[:8])}" if near else ""
        raise SystemExit(f"no item named {name!r}.{hint}")
    if len(matches) > 1:
        ids = ", ".join(f"{row['id']} ({row['name']})" for row in matches)
        raise SystemExit(f"{name!r} matches {len(matches)} items: {ids}")
    return matches[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="item names; defaults to this corpus's list")
    arguments = parser.parse_args(argv)
    names = tuple(arguments.names) or DEFAULT_NAMES

    mapping = fetch_mapping()
    print(f"# {len(mapping)} items in the catalog\n")
    for name in names:
        row = resolve(mapping, name)
        print(f"{row['id']:>7}  {row['name']}  (members={row.get('members')})")
    return 0


if __name__ == "__main__":  # pragma: no cover — run by hand
    sys.exit(main())
