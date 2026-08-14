"""Resolve every gear-ladder name to its numeric item id — run **by hand**, never by the app.

Two sources, because one is not enough. The price API's ``/mapping`` catalog is the
authority for anything tradeable and is what :mod:`tools.lookup_item_ids` already uses. It
carries **only** tradeables, though, and a gear ladder is full of things that are not: fire
capes, void, the defenders, Barrows gloves, and every charged form whose uncharged sibling is
the one that trades. Those ids come from the wiki's own ``Infobox Item``, read out of raw
wikitext — the wiki has neither Cargo nor SMW enabled, so there is no structured query to ask.

**This does not belong in** :mod:`tracker.integrations.prices`, for the reason
:mod:`tools.lookup_item_ids` gives at length: the same host serves ``/mapping``, the full
item catalog, and §8.3 is explicit that the full item economy is never pulled at runtime. An
authoring-time capture is a different activity from a runtime fetch, and this is where the
other authoring-time captures already live.

The refuse-to-guess rule is inherited whole. A name matching several catalog rows is an error
rather than a pick — *"Toxic blowpipe"* and *"Toxic blowpipe (empty)"* are different items
with different ids, and a plausible-looking wrong id produces a silently wrong GP estimate
rather than a failure. Every variant the wiki lists is captured with its version label
attached, so the decision about which one is the *priced* one stays with a human reading
:mod:`tools.generate_gear_items`.

Output is a JSON file under ``tools/data/``, matching the capture-then-generate shape
:mod:`tools.capture_quest_data` and :mod:`tools.generate_candidates` already use. Nothing
under ``content/`` is touched here.

Run::

    python tools/capture_gear_ids.py
    python tools/capture_gear_ids.py --out tools/data/osrs_gear_ids.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gear_ladders import unique_names

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "tools" / "data" / "osrs_gear_ids.json"

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
WIKI_API = "https://oldschool.runescape.wiki/api.php"
USER_AGENT = "osrs-recommender content authoring (offline item id lookup)"

#: ``|id3 = 24223`` and ``|version3 = Locked``. The numeric suffix pairs the two.
ID_LINE = re.compile(r"^\|\s*id(\d*)\s*=\s*([0-9,\s]+)$", re.MULTILINE)
VERSION_LINE = re.compile(r"^\|\s*version(\d*)\s*=\s*(.+)$", re.MULTILINE)

#: MediaWiki caps a ``titles=`` query; well under any limit and few enough requests to be
#: polite to a volunteer-run wiki.
WIKI_BATCH = 40


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_catalog() -> dict[str, list[dict[str, Any]]]:
    """The price API's tradeable catalog, indexed by case-folded name."""
    payload = _get(MAPPING_URL)
    if not isinstance(payload, list):  # pragma: no cover — run by hand
        raise SystemExit(f"unexpected /mapping payload: {type(payload).__name__}")
    rows: dict[str, list[dict[str, Any]]] = {}
    for row in payload:
        rows.setdefault(str(row.get("name", "")).casefold(), []).append(row)
    return rows


def resolve_catalog(catalog: dict[str, list[dict[str, Any]]], name: str) -> int | None:
    """The one catalog id for ``name``, or ``None`` when it has no row.

    **Several matches is an error, not a pick** — the rule :mod:`tools.lookup_item_ids`
    exists to enforce. Zero matches is *not* an error here: an untradeable simply has no row,
    and the wiki lookup is what covers it.
    """
    matches = catalog.get(name.casefold(), [])
    if not matches:
        return None
    if len(matches) > 1:  # pragma: no cover — run by hand
        ids = ", ".join(f"{row['id']} ({row['name']})" for row in matches)
        raise SystemExit(f"{name!r} matches {len(matches)} catalog items: {ids}")
    return int(matches[0]["id"])


def fetch_wikitext(titles: Sequence[str]) -> dict[str, str]:
    """Raw wikitext per title, following redirects and keyed by the name we asked for."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": "|".join(titles),
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    }
    query = _get(f"{WIKI_API}?{urllib.parse.urlencode(params)}").get("query", {})
    # A redirect or a normalisation means the page's title is not the name we asked for;
    # key the result by what was asked, so the caller need not follow the trail.
    aliases: dict[str, str] = {}
    for kind in ("redirects", "normalized"):
        for entry in query.get(kind, []):
            aliases[entry["to"]] = entry["from"]

    out: dict[str, str] = {}
    for page in query.get("pages", []):
        if "revisions" not in page:
            continue
        title = page["title"]
        content = page["revisions"][0]["slots"]["main"]["content"]
        for key in {title, aliases.get(title, title)}:
            out[key] = content
    return out


def variants(wikitext: str) -> list[tuple[str, int]]:
    """``[(version label, id)]`` for every variant the infobox declares, in file order."""
    labels = {suffix: value.strip() for suffix, value in VERSION_LINE.findall(wikitext)}
    found: list[tuple[str, int]] = []
    for suffix, value in ID_LINE.findall(wikitext):
        for part in value.split(","):
            part = part.strip()
            if part.isdigit():
                found.append((labels.get(suffix, ""), int(part)))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    arguments = parser.parse_args(argv)

    names = unique_names()
    catalog = fetch_catalog()
    print(f"# {sum(len(rows) for rows in catalog.values())} rows in the price catalog")

    priced: dict[str, int] = {}
    unpriced: list[str] = []
    for name in names:
        item_id = resolve_catalog(catalog, name)
        if item_id is None:
            unpriced.append(name)
        else:
            priced[name] = item_id
    print(f"# {len(priced)} tradeable, {len(unpriced)} to look up on the wiki")

    pages: dict[str, str] = {}
    # Every name, not only the unpriced ones: a tradeable item can still have charged or
    # broken variants that matter for *ownership*, and those are only listed on the wiki.
    for start in range(0, len(names), WIKI_BATCH):
        pages.update(fetch_wikitext(names[start : start + WIKI_BATCH]))
    wiki = {name: variants(text) for name in names if (text := pages.get(name)) is not None}

    unresolved = [name for name in unpriced if not wiki.get(name)]
    if unresolved:  # pragma: no cover — run by hand
        raise SystemExit(
            "no id from either source for: "
            + ", ".join(repr(name) for name in unresolved)
            + "\nCheck the spelling against the wiki page title in tools/gear_ladders.py."
        )

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "catalog": priced,
        "wiki": {name: [list(row) for row in rows] for name, rows in wiki.items()},
    }
    with arguments.out.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(f"# wrote {arguments.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover — run by hand
    sys.exit(main())
