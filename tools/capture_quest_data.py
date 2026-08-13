"""Capture the vendored quest dump — run **by hand**, never by the app.

This is the only part of the quest pipeline that touches the network, and it is
deliberately a separate tool from :mod:`tools.generate_candidates`. §16.1 keeps the
network out of :mod:`tracker.content`, and the corpus is the fixture every engine test
ranks against: a runtime fetch would make ranking non-reproducible between two runs on
the same account. So the wiki is read once, the result is committed, and generation is
offline and deterministic from then on.

**Identity comes from RuneLite, not from the wiki.** A candidate's ``completion`` predicate
is only true if its quest id equals what the plugin transmits, and that is
``slug(Quest.name())`` — the ruling recorded in ``docs/CONTRACT_RECONCILIATION.md`` and
implemented in ``QuestCollector.questId``. Wiki page names are a *display* space with
punctuation and disambiguation suffixes; deriving ids from them would produce candidates
that silently never complete. So the enum is the spine and the wiki is joined onto it.

Producing the enum dump (needs the RuneLite api jar Gradle already downloaded for the
plugin, and a JDK)::

    cat > DumpQuests.java <<'EOF'
    import net.runelite.api.Quest;
    public class DumpQuests {
      public static void main(String[] a) {
        for (Quest q : Quest.values()) System.out.println(q.name() + "\\t" + q.getName());
      }
    }
    EOF
    JAR=~/.gradle/caches/modules-2/files-2.1/net.runelite/runelite-api/*/*/runelite-api-*.jar
    javac -cp $JAR DumpQuests.java && java -cp "$JAR:." DumpQuests > quests_enum.tsv

Then::

    python tools/capture_quest_data.py --enum quests_enum.tsv --api-version 1.12.35

The wiki side is the ``quest`` Bucket's ``requirements`` field, stored **raw**. Parsing
lives in :mod:`tools.generate_candidates` where tests can exercise it, rather than being
baked into a captured artefact nobody can re-derive.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

#: Where the vendored dump lands. Committed; read by the generator; never read by the app.
DEFAULT_OUT = Path(__file__).resolve().parent / "data" / "osrs_quests.json"

WIKI_API = "https://oldschool.runescape.wiki/api.php"

#: The wiki asks for a descriptive agent naming a contact. One request is made per run.
USER_AGENT = "osrs-recommender content generator (https://github.com/, offline vendoring)"

BUCKET_QUERY = 'bucket("quest").select("page_name","requirements").limit(1000).run()'

#: RuneLite enum constants whose display name does not normalize onto a wiki page title.
#: Every entry is hand-verified against the wiki, and the generator fails loudly if any
#: other quest goes unmatched — an alias table that silently absorbs new mismatches would
#: hide exactly the drift this pipeline exists to catch.
#:
#: The Recipe for Disaster sub-quests are the whole list bar one: RuneLite names them
#: ``RECIPE_FOR_DISASTER__EVIL_DAVE`` while the wiki files them as subpages phrased from
#: the player's side ("Freeing Evil Dave"). Vale Totems carries a ``(miniquest)``
#: disambiguator the enum has no room for.
PAGE_ALIASES: Mapping[str, str] = {
    "RECIPE_FOR_DISASTER__MOUNTAIN_DWARF": "Recipe for Disaster/Freeing the Mountain Dwarf",
    "RECIPE_FOR_DISASTER__WARTFACE__BENTNOZE": "Recipe for Disaster/Freeing the Goblin generals",
    "RECIPE_FOR_DISASTER__PIRATE_PETE": "Recipe for Disaster/Freeing Pirate Pete",
    "RECIPE_FOR_DISASTER__LUMBRIDGE_GUIDE": "Recipe for Disaster/Freeing the Lumbridge Guide",
    "RECIPE_FOR_DISASTER__EVIL_DAVE": "Recipe for Disaster/Freeing Evil Dave",
    "RECIPE_FOR_DISASTER__SKRACH_UGLOGWEE": "Recipe for Disaster/Freeing Skrach Uglogwee",
    "RECIPE_FOR_DISASTER__SIR_AMIK_VARZE": "Recipe for Disaster/Freeing Sir Amik Varze",
    "RECIPE_FOR_DISASTER__KING_AWOWOGEI": "Recipe for Disaster/Freeing King Awowogei",
    "RECIPE_FOR_DISASTER__CULINAROMANCER": "Recipe for Disaster/Defeating the Culinaromancer",
    "VALE_TOTEMS": "Vale Totems (miniquest)",
}


def slug(constant_name: str) -> str:
    """``QuestCollector.slug``, restated in Python.

    Deliberately duplicated rather than imported from anywhere: the Java side is the
    authority, this is a transcription of it, and the pair is checked by a test that
    compares against ids observed in a real payload. A shared helper would only hide the
    fact that two languages must agree.
    """
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", constant_name.lower()))


def normalize_title(title: str) -> str:
    """Fold a display name to a joining key: case, punctuation and accents all dropped."""
    folded = unicodedata.normalize("NFKD", title)
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def read_enum(path: Path) -> list[tuple[str, str]]:
    """The ``CONSTANT\\tDisplay Name`` dump, in enum order."""
    rows: list[tuple[str, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise SystemExit(f"{path}:{number}: expected 'CONSTANT<TAB>Name', found {line!r}")
        rows.append((parts[0], parts[1]))
    return rows


def fetch_wiki_requirements() -> dict[str, str]:
    """Page title → raw ``requirements`` wikitext, for every quest the wiki knows."""
    query = urllib.parse.urlencode({"action": "bucket", "format": "json", "query": BUCKET_QUERY})
    request = urllib.request.Request(f"{WIKI_API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if "bucket" not in payload:
        raise SystemExit(f"wiki returned no rows: {payload.get('error', payload)}")
    return {row["page_name"]: row.get("requirements") or "" for row in payload["bucket"]}


def join(
    enum_rows: Sequence[tuple[str, str]], wiki: Mapping[str, str]
) -> tuple[list[dict[str, str]], list[str]]:
    """Join the enum onto the wiki. Returns the quests and the unmatched enum constants."""
    by_key = {normalize_title(title): title for title in wiki}
    quests: list[dict[str, str]] = []
    unmatched: list[str] = []
    for constant, display in enum_rows:
        page = PAGE_ALIASES.get(constant) or by_key.get(normalize_title(display))
        if page is None or page not in wiki:
            unmatched.append(constant)
            continue
        quests.append(
            {
                "id": slug(constant),
                "name": display,
                "wiki_page": page,
                "requirements": wiki[page],
            }
        )
    return quests, unmatched


def _iter_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python tools/capture_quest_data.py", description=__doc__)
    parser.add_argument("--enum", type=Path, required=True, help="CONSTANT<TAB>Name dump")
    parser.add_argument("--api-version", required=True, help="runelite-api version, for provenance")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _iter_args(argv)
    enum_rows = read_enum(args.enum)
    wiki = fetch_wiki_requirements()
    quests, unmatched = join(enum_rows, wiki)

    if unmatched:
        # Refusing to write is the point. A partial dump would silently drop quests from
        # the corpus, and a missing candidate is invisible in a way a wrong one is not.
        print(f"{len(unmatched)} quests did not match a wiki page:", file=sys.stderr)
        for constant in unmatched:
            print(f"  {constant}", file=sys.stderr)
        print("add each to PAGE_ALIASES after checking the page by hand", file=sys.stderr)
        return 1

    document = {
        "_source": {
            "identity": "slug(net.runelite.api.Quest.name()) — see QuestCollector",
            "runelite_api_version": args.api_version,
            "wiki_api": WIKI_API,
            "wiki_query": BUCKET_QUERY,
            "note": "requirements is raw wikitext; parsing lives in tools/generate_candidates.py",
        },
        "quests": quests,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} — {len(quests)} quests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
