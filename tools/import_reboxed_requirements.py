"""Import exact-ID partial level gates from a locally downloaded complete JSON.

No network at runtime, physical-statistics writes, approval or effects changes.
Run ``python -m tools.import_reboxed_requirements --help`` for usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from tracker.content.loader import load_content
from tracker.content.requirements import AllOf, CombatLevelLeaf, SkillLeaf
from tracker.gear.catalog import load_catalog
from tracker.gear.requirements_source import requirement_from_levels, requirement_state

REPOSITORY = "https://github.com/DayV-git/osrsreboxed-db"


def build_import(source, rows, skills):
    """Keep only validated maps for exact physical IDs, without modifying inputs."""
    if not isinstance(source, dict):
        raise ValueError("Complete items JSON must be an object keyed by item ID")
    items, exceptions = {}, {}
    for row in rows:
        key = str(row["id"])
        external = source.get(key)
        if external is not None and not isinstance(external, dict):
            exceptions[key] = "invalid_record"
            continue
        state = requirement_state(external)
        if external is not None and (
            type(external.get("id")) is not int or external["id"] != row["id"]
        ):
            state = "identity_mismatch"
        if state == "populated":
            levels = external["equipment"]["requirements"]
            try:
                requirement_from_levels(levels, skills)
            except ValueError:
                state = "invalid_requirements"
            else:
                if external.get("incomplete") is True:
                    state = "source_incomplete"
                else:
                    items[key] = dict(sorted(levels.items()))
                    continue
        exceptions[key] = state
    return items, exceptions


def reviewed_levels(requirement):
    """Compare conjunctive skill minima only; quest/unlock gates are separate."""
    if isinstance(requirement, SkillLeaf):
        return {requirement.skill: requirement.level}
    if isinstance(requirement, CombatLevelLeaf):
        return {"combat": requirement.level}
    if isinstance(requirement, AllOf):
        result = {}
        for child in requirement.children:
            levels = reviewed_levels(child)
            if levels is None:
                return None
            for skill, level in levels.items():
                result[skill] = max(level, result.get(skill, 0))
        return result
    if requirement is not None and requirement.type in {"any_of", "not", "at_least"}:
        return None
    return {}


def coverage_report(source, catalog, items, exceptions):
    counts = Counter(requirement_state(source.get(str(i))) for i in catalog.items)
    comparisons, disagreements = Counter(), []
    for key, item in catalog.items.items():
        if not item.requirements_complete:
            continue
        levels = reviewed_levels(item.requires)
        external = items.get(str(key))
        if external is None or levels is None:
            comparisons["not_comparable"] += 1
        elif levels == external:
            comparisons["agree"] += 1
        else:
            comparisons["disagree"] += 1
            disagreements.append(
                {"id": key, "name": item.name, "reviewed_skills": levels, "source_skills": external}
            )
    applied = [i for i, item in catalog.items.items() if not item.content_ids and str(i) in items]
    complete = sum(i.requirements_complete for i in catalog.items.values())
    known = sum(i.requires is not None for i in catalog.items.values())
    effects = sum(bool(i.unsupported_effects) for i in catalog.items.values())
    unresolved = [i for i, item in catalog.items.items() if not item.requirements_complete]
    return {
        "catalog_ids": len(catalog.items),
        "physical_catalog_sha256": catalog.revision,
        "source_items": len(source),
        "matched_ids": len(catalog.items) - counts["unmatched"],
        "source_states": dict(counts),
        "usable_level_maps": len(items),
        "reviewed_comparison": dict(comparisons),
        "disagreements": disagreements,
        "new_partial_requirement_ids": applied,
        "import_exceptions": exceptions,
        "quest_or_other_gate_review_ids": unresolved,
        "special_effect_review_ids": [i for i, x in catalog.items.items() if x.unsupported_effects],
        "remaining_gate_or_effect_review": sum(
            not i.requirements_complete or bool(i.unsupported_effects)
            for i in catalog.items.values()
        ),
        "before": {
            "with_requirement_tree": known,
            "complete_gates": complete,
            "effect_blockers": effects,
        },
        "after": {
            "with_requirement_tree": known + len(applied),
            "complete_gates": complete,
            "effect_blockers": effects,
        },
        "newly_rankable": 0,
    }


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="Pinned upstream 40-character commit")
    parser.add_argument("--content", type=Path, default=Path("content"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must be a lowercase 40-character Git SHA")
    root = args.content / "equipment"
    protected = {
        args.source.resolve(),
        (root / "catalog.json").resolve(),
        (root / "manifest.json").resolve(),
    }
    if args.output.resolve() in protected or args.report.resolve() in protected:
        parser.error("Outputs must not overwrite the source or physical catalog")
    if args.output.resolve() == args.report.resolve():
        parser.error("Output and report paths must differ")
    allowed_content_outputs = {
        (root / name).resolve() for name in ("requirements.json", "requirements-report.json")
    }
    for path in (args.output, args.report):
        if path.resolve().is_relative_to(args.content.resolve()) and (
            path.resolve() not in allowed_content_outputs
        ):
            parser.error("Content outputs must be requirements.json or requirements-report.json")
    raw = args.source.read_bytes()
    source = json.loads(raw)
    content = load_content(args.content)
    catalog = load_catalog(content, root, use_requirements_source=False)
    rows = [{"id": key} for key in catalog.items]
    items, exceptions = build_import(source, rows, content.skills)
    provenance = {
        "repository": REPOSITORY,
        "commit": args.commit,
        "url": f"https://raw.githubusercontent.com/DayV-git/osrsreboxed-db/{args.commit}"
        "/docs/items-complete.json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "license": "GPL-3.0",
    }
    report = {"source": provenance, **coverage_report(source, catalog, items, exceptions)}
    write_json(args.output, {"source": provenance, "items": items})
    write_json(args.report, report)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if not isinstance(v, list) and k != "import_exceptions"
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
