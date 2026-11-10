"""Deterministic concrete discipline assignments over immutable role requests."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import product
from typing import Any

DISCIPLINES = ("melee", "ranged", "magic")


def has_auto(request: Any) -> bool:
    return any(role.allowed_disciplines is not None for role in request.roles)


def has_magic(request: Any) -> bool:
    return any(
        "magic" in role.allowed_disciplines
        if role.allowed_disciplines is not None
        else role.style == "magic"
        for role in request.roles
    )


def branch_requests(request: Any) -> Iterator[tuple[str, Any]]:
    choices = [
        tuple(
            role.model_copy(
                update={
                    "allowed_disciplines": None,
                    "style": "slash" if discipline == "melee" else discipline,
                    "stance": "rapid" if discipline == "ranged" else "accurate",
                }
            )
            for discipline in DISCIPLINES
            if discipline in role.allowed_disciplines
        )
        if role.allowed_disciplines is not None
        else (role,)
        for role in request.roles
    ]
    for roles in product(*choices):
        mapping = {
            role.id: "melee" if role.style in {"stab", "slash", "crush"} else role.style
            for role in roles
            if role.style != "special"
        }
        key = (
            next(iter(mapping.values()))
            if len(roles) == 1
            else "/".join(f"{role_id}={discipline}" for role_id, discipline in mapping.items())
        )
        yield key, request.model_copy(update={"roles": roles})


def merge_assignment_results(
    request: Any, branches: list[tuple[str, dict[str, Any]]], *, complete_frontiers: bool = False
) -> dict[str, Any]:
    """Merge full joint archives without publishing a response per assignment."""
    import json
    from hashlib import sha256

    from tracker.gear.potion_search import merge_results

    result = merge_results(
        request, [row for _, row in branches], complete_frontiers=complete_frontiers
    )
    assumptions = {
        **result["assumptions"],
        "discipline_assignment_policy": {
            "policy": "full-per-discipline-assignment-v1",
            "allowed_disciplines": {
                role.id: list(role.allowed_disciplines)
                for role in request.roles
                if role.allowed_disciplines is not None
            },
        },
    }
    return {
        **result,
        "discipline_results": [],
        "discipline_comparison": [],
        "assumptions": assumptions,
        "assumptions_fingerprint": sha256(
            json.dumps(assumptions, sort_keys=True).encode()
        ).hexdigest(),
        "search": {
            **{key: value for key, value in result["search"].items() if key != "potion_selection"},
            "discipline_assignment_selection": {
                "policy": "full-per-discipline-assignment-v1",
                "branch_count": len(branches),
                "branches": {
                    key: {
                        **row["search"],
                        "status": "best_found"
                        if row["selected_solution"]
                        else "no_feasible_solution_found",
                        "reasons": [] if row["selected_solution"] else row["limitations"],
                    }
                    for key, row in branches
                },
            },
        },
    }
