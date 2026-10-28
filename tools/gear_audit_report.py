"""Deterministic Markdown rendering of equipment coverage facts, without inference."""

from __future__ import annotations

import html
import json
from typing import Any


def cell(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return (
        html.escape(str(value), quote=False)
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(cell(c) for c in row) + " |" for row in rows],
        "",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Gear Equipment Coverage Audit",
        "",
        "Generated from frozen inputs. Eligibility is measured before search; "
        "absence from an optimized loadout is never used as evidence.",
        "",
        f"Evaluation time: `{report.get('evaluated_at')}`. "
        f"Snapshot fingerprint: `{report.get('snapshot_id')}`.",
        "",
        f"Physical catalog revision: `{report.get('catalog_revision')}`.",
        "",
        "## Provenance and limits",
        "",
        "This is a local frozen-state diagnostic using the current catalog and authored "
        "metadata, not a reconstruction of historical catalog versions or current live "
        "gameplay. Scan timestamps and item sighting timestamps are distinct. Ownership "
        "quantities across asynchronous containers are not added.",
        "",
    ]
    lines += table(
        ["Field", "Value"], [[k, v] for k, v in sorted(report.get("provenance", {}).items())]
    )
    lines += [
        "## Coverage denominators",
        "",
        "Counts of independent limitations overlap. Primary blocking categories are "
        "exclusive. Unclassified bank/inventory IDs are neither assumed equipment "
        "nor assumed non-equipment. An equipment-container sighting confirms equipment "
        "but cannot establish its exact slot or name.",
        "",
    ]
    for title, key in (
        ("Catalog-wide", "catalog_summary"),
        ("Current-account observations", "current_account_summary"),
    ):
        lines += [f"### {title}", ""]
        lines += table(
            ["Measure", "Count / detail"], [[k, v] for k, v in sorted(report.get(key, {}).items())]
        )
    lines += [
        "## Scenario and price policy",
        "",
        "Default sweeps use independent owned-only accurate stab, slash, crush, ranged "
        "and magic (fire_strike) roles, generic targets and zero acquisition budget. "
        "Exact request input replaces these defaults. Current stored account facts are "
        "not time-filtered into an invented historical snapshot.",
        "",
        "Prices fetched after the evaluation time are unavailable in the as-of view; "
        "future trade legs are excluded. Raw-cache diagnostics retain and flag these "
        "inputs separately. Authored static hints are current hints, not historical trades. "
        "No purchase price is required for an observed owned item.",
        "",
        f"Price policy: {cell(report.get('price_policy'))}",
        "",
    ]
    for scenario in report.get("scenarios", []):
        lines += [f"### {cell(scenario.get('scenario_id', scenario.get('id')))}", ""]
        lines += table(["Field", "Value"], [[k, v] for k, v in sorted(scenario.items())])
    lines += [
        "## Item-level blocking reasons",
        "",
        "Each physical ID appears once with all available container sightings. "
        "Access eligibility is separate from combat-model support and scenario "
        "compatibility. Pool retention is measured directly; later beam survival is "
        "`not_measured`. A retained item is not guaranteed to occur in a legal full "
        "loadout. Missing supported scaffolds are contextual limitations.",
        "",
    ]
    equipment = [r for r in report.get("items", []) if r.get("classification") == "equipment"]
    lines += table(
        ["ID", "Canonical name", "Slot", "Catalog", "Primary blocker", "Secondary limitations"],
        [
            [
                r["item_id"],
                r["name"],
                r.get("slot"),
                r.get("catalog_present"),
                r.get("primary_blocker"),
                r.get("secondary_limitations"),
            ]
            for r in equipment
        ],
    )
    for row in equipment:
        fact = row.get("fact") or {}
        lines += [f"### {row['item_id']} — {cell(row['name'])}", ""]
        lines += table(
            ["Dimension", "Evidence"],
            [
                ["Observations (container, time, source, scan state)", row.get("observations")],
                [
                    "Canonical name source / authored slot (not physical slot)",
                    {
                        "source": row.get("canonical_name_source"),
                        "authored_slot": row.get("authored_slot"),
                        "ambiguous": row.get("authored_identity_ambiguous"),
                    },
                ],
                [
                    "Physical catalog / exact slot",
                    {"present": row.get("catalog_present"), "slot": row.get("slot")},
                ],
                [
                    "Requirements completeness / wear / unmet and unknown requirements",
                    fact.get("wear"),
                ],
                ["Combat effects / model limitations", fact.get("limitations")],
                [
                    "Physical style / stance / hands / ammunition metadata",
                    row.get("compatibility_metadata"),
                ],
                ["Concrete ownership", row.get("ownership", fact.get("ownership"))],
                ["Acquisition", fact.get("acquisition")],
                ["As-of price", fact.get("price")],
                ["Raw-cache price diagnostic", row.get("pricing")],
                ["Physical variant review", row.get("variant_review")],
                ["Primary blocker", row.get("primary_blocker")],
                ["Secondary limitations", row.get("secondary_limitations")],
            ],
        )
        lines += table(
            [
                "Scenario / role",
                "Access",
                "Role support",
                "Initial eligible",
                "Retention",
                "Evidence",
            ],
            [
                [
                    f"{r.get('scenario_id')}/{r.get('role_id')}",
                    r.get("access_eligible"),
                    r.get("role_support"),
                    r.get("initial_eligible"),
                    r.get("candidate_retention"),
                    {
                        k: v
                        for k, v in r.items()
                        if k
                        not in {
                            "scenario_id",
                            "role_id",
                            "access_eligible",
                            "role_support",
                            "initial_eligible",
                            "candidate_retention",
                        }
                    },
                ]
                for r in row.get("scenario_results", [])
            ],
        )
    lines += [
        "## Unclassified observed IDs",
        "",
        "Canonical name, equipment status and slot remain unknown when exact existing "
        "mappings do not establish them. These IDs are preserved for follow-up "
        "classification and excluded from confirmed equipment denominators.",
        "",
    ]
    lines += table(
        ["ID", "Name", "Classification", "Observations", "Reason"],
        [
            [
                r["item_id"],
                r["name"],
                r["classification"],
                r.get("observations"),
                r.get("primary_blocker"),
            ]
            for r in report.get("items", [])
            if r.get("classification") != "equipment"
        ],
    )
    lines += [
        "## Persistence and acceptance limits",
        "",
        "Persisted scans reflect accepted merge state. Sync-event totals do not link "
        "every sighting to a retained raw payload. Overwritten/deleted history and "
        "rejected payload contents cannot be reconstructed. Raw persisted observation "
        "evidence, including superseded and zero-quantity rows, is retained in audit.json.",
        "",
    ]
    return "\n".join(lines)
