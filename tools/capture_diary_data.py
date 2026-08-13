"""Capture the vendored achievement-diary dump — run **by hand**, never by the app.

The companion to :mod:`tools.capture_quest_data`, and it follows the same two rules for
the same reasons: the network is touched once and the result is committed, and identity
comes from what the *plugin* transmits rather than from the wiki.

Diary keys are ``slug(Varbits.DIARY_*)`` — ``UnlockCollector`` enumerates them by
reflection over field names, so ``DIARY_ARDOUGNE_EASY`` reaches the API as
``diary_ardougne_easy``. That is a closed 12×4 space, which is why the regions are listed
here as a constant instead of being joined by name: there is nothing to guess, and a
region map that could silently mis-join is a worse trade than twelve lines of table.

Unlike quests, no registry file is needed. §6.3 keeps the ``unlock:`` key space **open**
with reserved ``diary_``/``ca_`` prefixes supplied by the plugin, and
``_check_references`` deliberately does not resolve ``unlock:`` leaves.

Run::

    python tools/capture_diary_data.py

**Requirements are per tier, taken from the tier's own task table.** Each diary page marks
its tables with ``data-diary-tier="Easy"``, and every task lists its requirements as
``{{SCP|Skill|Level}}`` templates. The tier's requirement is the maximum level each skill
is asked for across its tasks — not an estimate but a floor: you cannot complete the tier
without completing every task in it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "osrs_diaries.json"

WIKI_API = "https://oldschool.runescape.wiki/api.php"
USER_AGENT = "osrs-recommender content generator (offline vendoring)"

#: Courtesy delay between page fetches. Twelve requests is not a load, but the wiki asks.
REQUEST_DELAY_SECONDS = 0.5

#: ``diary_<region>`` key → wiki page. Hand-verified, and deliberately not derived: the
#: plugin's region tokens are abbreviations of page titles that carry ampersands and
#: qualifiers ("Kourend & Kebos", "Western Provinces"), so a normalizing join would have
#: to be loose enough to mis-match. The space is closed at twelve.
DIARY_PAGES: Mapping[str, str] = {
    "ardougne": "Ardougne Diary",
    "desert": "Desert Diary",
    "falador": "Falador Diary",
    "fremennik": "Fremennik Diary",
    "kandarin": "Kandarin Diary",
    "karamja": "Karamja Diary",
    "kourend": "Kourend & Kebos Diary",
    "lumbridge": "Lumbridge & Draynor Diary",
    "morytania": "Morytania Diary",
    "varrock": "Varrock Diary",
    "western": "Western Provinces Diary",
    "wilderness": "Wilderness Diary",
}

#: The four tiers, in the order the varbits declare them.
TIERS = ("easy", "medium", "hard", "elite")

_TIER_TABLE = re.compile(r'data-diary-tier="(?P<tier>Easy|Medium|Hard|Elite)"')


def fetch_wikitext(page: str) -> str:
    query = urllib.parse.urlencode(
        {"action": "parse", "format": "json", "page": page, "prop": "wikitext"}
    )
    request = urllib.request.Request(f"{WIKI_API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if "error" in payload:
        raise SystemExit(f"{page}: {payload['error'].get('info')}")
    return str(payload["parse"]["wikitext"]["*"])


def split_tiers(wikitext: str) -> dict[str, str]:
    """Tier name (lowercase) → the wikitext of that tier's task table.

    Split on the table's own ``data-diary-tier`` attribute rather than on the ``==Easy==``
    heading: the heading section also contains a Rewards subsection and a task-location
    map, both of which mention skills and quests that are *not* requirements.
    """
    matches = list(_TIER_TABLE.finditer(wikitext))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(wikitext)
        tier = match.group("tier").lower()
        # A tier can be marked by more than one table; concatenating keeps every task.
        blocks[tier] = blocks.get(tier, "") + wikitext[match.end() : end]
    return blocks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/capture_diary_data.py", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    diaries: list[dict[str, str]] = []
    missing: list[str] = []
    for index, (region, page) in enumerate(DIARY_PAGES.items()):
        if index:
            time.sleep(REQUEST_DELAY_SECONDS)
        blocks = split_tiers(fetch_wikitext(page))
        for tier in TIERS:
            if tier not in blocks:
                missing.append(f"{region} {tier}")
                continue
            diaries.append(
                {
                    "key": f"diary_{region}_{tier}",
                    "name": f"{page.removesuffix(' Diary')} Diary — {tier.capitalize()}",
                    "wiki_page": page,
                    "requirements": blocks[tier],
                }
            )
        print(f"  {page}: {sorted(blocks)}", file=sys.stderr)

    if missing:
        # Refusing to write, for capture_quest_data's reason: a tier silently absent from
        # the dump is a candidate silently absent from the corpus, and nothing downstream
        # can tell that from a diary that simply does not exist.
        print(f"{len(missing)} tiers had no task table: {', '.join(missing)}", file=sys.stderr)
        return 1

    document = {
        "_source": {
            "identity": "slug(net.runelite.api.gameval.Varbits.DIARY_*) — see UnlockCollector",
            "wiki_api": WIKI_API,
            "note": (
                "requirements is the raw wikitext of the tier's task table; parsing lives "
                "in tools/generate_candidates.py"
            ),
        },
        "diaries": diaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} — {len(diaries)} diary tiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
