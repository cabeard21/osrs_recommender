"""Exact physical Aquanite hopper review; passive assumptions live in hopper.py."""

from typing import Any


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    if row["id"] != 32879:
        return row
    if (row["name"], row["slot"]) != ("Aquanite hopper", "shield"):
        raise ValueError("Reviewed hopper physical form changed: 32879")
    return {
        **row,
        "unsupported_effects": [
            effect
            for effect in row["unsupported_effects"]
            if effect != "Offensive effects have not been validated."
        ],
    }
