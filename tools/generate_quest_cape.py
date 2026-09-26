"""Generate the standalone factual catalog, offline; --check detects drift.

Unrecognized hard conditions remain explicit unknowns. Combat execution and supplies
are intentionally outside the model. Source and generator are independent of rankings.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/data/quest_cape_source.json"
OUTPUT = ROOT / "content/quest_cape/catalog.json"
SKILL = re.compile(r"\{\{SCP\|([^|}]+)\|(\d+)(?:\||\}\})", re.I)
LINK = re.compile(r"\[\[([^|\]#]+)")


def generate(source: dict) -> dict:
    lookup = {q["wiki_page"].replace("_", " "): q["id"] for q in source["quests"]}
    result = []
    for row in source["quests"]:
        raw = row["requirements"]
        skills: dict[str, int] = {}
        others: dict[str, int] = {}
        prerequisites: set[str] = set()
        unknowns: list[str] = []
        notes: list[str] = []
        for line in (raw or "").splitlines():
            line = re.sub(r"<!--.*?-->", "", line).strip()
            if not line or line.lower() == "none":
                continue
            depth = len(line) - len(line.lstrip("*"))
            # Nested requirements belong to their owning prerequisite, not this quest.
            if depth > 2:
                continue
            lower = line.lower()
            if re.search(
                r"(?:ability|able) to (?:defeat|kill|survive|defend|evade|withstand|run|get past)"
                r"|capable of killing",
                lower,
            ):
                notes.append(line)
                continue
            if "the following quest" in lower or lower.startswith("**the above quests"):
                continue
            if re.search(r"\b(started|partial|starting|start of)\b", lower):
                unknowns.append(line)
                continue
            if lower.lstrip("* ").startswith(("it is beneficial", "you do not need", "none -")):
                notes.append(line)
                continue
            if re.search(r"\bor\b|not necessary", lower):
                # Do not flatten alternatives or optional equipment thresholds into AND.
                unknowns.append(line)
                continue
            matched = SKILL.findall(line)
            if matched:
                for label, value in matched:
                    label = label.lower()
                    if label in {"quest", "quest points", "combat", "combat level"}:
                        key = "quest_points" if label.startswith("quest") else "combat_level"
                        others[key] = max(others.get(key, 0), int(value))
                    else:
                        skills[label] = max(skills.get(label, 0), int(value))
                continue
            links = [
                lookup[t.replace("_", " ")]
                for t in LINK.findall(line)
                if t.replace("_", " ") in lookup
            ]
            if links:
                prerequisites.update(links)
                continue
            # Headers and execution advice are notes; every other clause needs review.
            if depth == 0 and (
                line.startswith("'''") or line in {"<onlyinclude>", "</onlyinclude>"}
            ):
                continue
            unknowns.append(line)
        clauses: list[dict[str, Any]] = [
            {"skill": {key: value}} for key, value in sorted(skills.items())
        ]
        clauses.extend({key: value} for key, value in sorted(others.items()))
        clauses.extend({"quest": key} for key in sorted(prerequisites - {row["id"]}))
        # The parent is a progress aggregate. Its final chapter is the concrete action.
        # Subquests retain their own RuneLite identities and prerequisite observations.
        if row["id"] == "recipe_for_disaster":
            clauses = [{"quest": "recipe_for_disaster_culinaromancer"}]
            unknowns = []
        definition = {
            "id": row["id"],
            "name": row["name"],
            "counts_for_cape": not row["miniquest"] and not row["subquest"],
            "requires": (clauses[0] if len(clauses) == 1 else {"all_of": clauses})
            if clauses
            else None,
            "quest_points": 0 if row["miniquest"] else row["quest_points"],
            "requirements_verified": raw is not None,
            "unmodeled": sorted(set(unknowns)),
            "notes": sorted(set(notes)),
            "wiki_url": "https://oldschool.runescape.wiki/w/"
            + quote(row["wiki_page"].replace(" ", "_")),
            "revision": row["revision"],
            "completes_parent": "recipe_for_disaster"
            if row["id"] == "recipe_for_disaster_culinaromancer"
            else None,
            "staged_rewards": row["id"] == "recipe_for_disaster",
        }
        result.append(definition)
    return {
        "version": source["captured_at"],
        "source": (
            f"OSRS Wiki page revisions (CC BY-NC-SA 3.0); RuneLite {source['runelite_api_version']}"
        ),
        "quests": sorted(result, key=lambda q: q["id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate(json.loads(SOURCE.read_text(encoding="utf-8")))
    # Validate identities, graph, and the existing requirement grammar before writing.
    sys.path.insert(0, str(ROOT))
    from tracker.quest_cape.catalog import QuestCatalog

    QuestCatalog.model_validate(generated)
    text = json.dumps(generated, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print("Quest Cape catalog drift: run python tools/generate_quest_cape.py")
            return 1
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(text, encoding="utf-8")
    print(f"Quest Cape catalog OK: {len(generated['quests'])} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
