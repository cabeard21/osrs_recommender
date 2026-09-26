"""Factual presentation of GearService progression output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from nicegui import ui

from tracker.accounts.snapshot import AccountSnapshot
from tracker.estimation.prices import PriceRecord
from tracker.gear.service import GearService
from tracker.ui.shell import section


def progression_views(
    service: GearService,
    snapshot: AccountSnapshot,
    prices: Mapping[int, PriceRecord],
    now: datetime,
) -> tuple[dict[str, Any], ...]:
    """Call the same service operation and inputs as MCP; add no UI interpretation."""
    views = []
    for style in ("melee", "ranged", "magic"):
        page = service.progression(snapshot, style=style, limit=100, price_records=prices, now=now)
        items = list(page["items"])
        while page.get("next_offset") is not None:
            page = service.progression(
                snapshot,
                style=style,
                limit=100,
                offset=page["next_offset"],
                price_records=prices,
                now=now,
            )
            items.extend(page["items"])
        views.append({"style": style, "items": items})
    return tuple(views)


def _price_label(price: Mapping[str, Any]) -> str:
    amount = price.get("amount_gp")
    if amount is None:
        return "Price unknown"
    return f"{amount:,} gp · {price.get('layer', 'unknown')}"


def render(views: Sequence[Mapping[str, Any]]) -> None:
    """Render service facts as delivered, without choosing a setup or ranking candidates."""
    ui.html(
        "Authored progression order. Ownership means an item was observed; "
        "unowned means it was not seen in the latest accepted container scans. "
        "Scan times may differ. No loadout recommendation or joint compatibility is evaluated."
    ).classes("text-sm tracker-dim")
    for view in views:
        style = str(view["style"])
        with (
            section(style.title(), testid=f"gear-style-{style}"),
            ui.element("div").classes("flex flex-col gap-3"),
        ):
            for item in view["items"]:
                _render_item(item)


def _render_item(item: Mapping[str, Any]) -> None:
    slot = str(item["slot"])
    with ui.element("div").classes("tracker-card") as card:
        card.props(f"data-testid=gear-item data-slot={slot} data-content-id={item['content_id']}")
        with ui.element("div").classes("flex flex-wrap gap-2 items-baseline"):
            ui.label(str(item["name"])).classes("font-semibold")
            ui.html(f"{slot} · tier {item['tier']}").classes("text-xs tracker-faint")
        ownership = item["ownership"]
        wear = item["wear"]
        ui.label(
            f"Ownership: {ownership['status']} — {ownership['meaning']}; "
            f"wear requirements: {wear['status']}"
        ).classes("text-sm tracker-dim")
        sightings = ownership.get("sightings", ())
        if sightings:
            ui.label(
                "Observed: "
                + ", ".join(f"{fact['container']} at {fact['observed_at']}" for fact in sightings)
            ).classes("text-xs tracker-faint")
        price = item["price"]
        ui.label(_price_label(price)).classes("text-sm tracker-data")
        ui.label(
            f"{price['selection_reason']} · provider {price['provider'] or 'unknown'} · "
            f"fetched {price['fetched_at'] or 'unknown'}"
        ).classes("text-xs tracker-faint")
