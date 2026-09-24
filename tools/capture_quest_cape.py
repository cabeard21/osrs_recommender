"""Capture quest facts from Wiki page revisions, separately from legacy generation.

Run manually: python tools/capture_quest_cape.py. No application code imports this tool.
The identity spine is the vendored RuneLite enum dump. Wiki text is CC BY-NC-SA 3.0.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://oldschool.runescape.wiki/api.php"


def fetch(titles: list[str]) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "revisions",
        "rvprop": "content|ids|timestamp",
        "rvslots": "main",
        "titles": "|".join(titles),
    }
    request = urllib.request.Request(
        API + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "osrs-recommender/0.1 (personal offline quest catalog capture)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    if "error" in data:
        raise ValueError(data["error"])
    return list(data["query"]["pages"].values())


def main() -> None:
    identity = json.loads((ROOT / "tools/data/osrs_quests.json").read_text())
    rows = identity["quests"]
    pages = {}
    for start in range(0, len(rows), 20):
        for page in fetch([q["wiki_page"] for q in rows[start : start + 20]]):
            pages[page["title"]] = page
    captured = []
    for row in rows:
        page = pages[row["wiki_page"]]
        revision = page["revisions"][0]
        text = revision["slots"]["main"]["*"]
        requirements = re.search(
            r"\|\s*requirements[ \t]*=[ \t]*(.*?)(?=\n\|\s*\w+\s*=|\n\}\})", text, re.S
        )
        points = re.search(r"\|\s*qp\s*=\s*(\d+)\s*(?:\||\n|\})", text)
        captured.append(
            {
                "id": row["id"],
                "name": row["name"],
                "wiki_page": row["wiki_page"],
                "revision": revision["revid"],
                "timestamp": revision["timestamp"],
                "miniquest": bool(re.search(r"\{\{Infobox Miniquest\b", text, re.I)),
                "subquest": row["wiki_page"].startswith("Recipe for Disaster/"),
                "requirements": requirements[1].strip()
                if requirements
                else ("" if "{{Quest details" in text else None),
                "quest_points": int(points[1]) if points else None,
            }
        )
    result = {
        "captured_at": datetime.now(UTC).isoformat(),
        "runelite_api_version": identity["_source"]["runelite_api_version"],
        "source": API,
        "license": "CC BY-NC-SA 3.0",
        "quests": captured,
    }
    (ROOT / "tools/data/quest_cape_source.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Captured {len(captured)} quest pages")


if __name__ == "__main__":
    main()
