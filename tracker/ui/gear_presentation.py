"""Equipment-first presentation of validated optimizer output; no scoring logic."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any

from nicegui import ui

SLOTS = (
    "head",
    "cape",
    "neck",
    "ammunition",
    "weapon",
    "body",
    "shield",
    "legs",
    "hands",
    "feet",
    "ring",
)
_ICONS = Path(__file__).parent / "assets" / "items"
GEAR_CSS = """
.gear-paperdoll {display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
 grid-template-rows:repeat(5,minmax(86px,auto));gap:7px;width:100%;max-width:390px;
 padding:16px;background:var(--panel-2);border:2px ridge var(--edge);border-radius:6px}
.gear-slot.q-btn {min-width:0;padding:5px 3px;background:var(--panel);color:var(--ink);
 border:1px solid var(--edge);text-transform:none;box-shadow:inset 0 0 10px #0002}
.gear-slot .q-btn__content {display:flex;flex-direction:column;gap:3px;flex-wrap:nowrap}
.gear-slot-name {font-size:10px;line-height:1.2;max-width:100%;overflow-wrap:anywhere}
.gear-slot-label {font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-dim)}
.gear-slot:focus-visible,.gear-slot-selected {outline:2px solid var(--gold);outline-offset:1px}
.gear-sprite {width:36px!important;height:36px!important;object-fit:contain;
 image-rendering:pixelated}
.gear-loadout {display:grid;grid-template-columns:minmax(270px,390px) minmax(0,1fr);
 gap:24px;width:100%;align-items:start}
.gear-metrics {display:flex;flex-wrap:wrap;gap:12px 28px;width:100%;padding:14px 0}
.gear-metric-value {font-family:var(--font-data);font-size:24px;color:var(--gold)}
.gear-metric-caption {font-size:12px;color:var(--ink-dim)}
.gear-role {border-top:1px solid var(--edge);padding-top:18px;width:100%}
.gear-alternative {border-top:1px solid var(--edge-soft);padding:12px 0;width:100%}
.gear-summary {padding:14px;background:var(--panel-2);border:1px solid var(--edge);width:100%}
.gear-slot-detail {min-width:0;width:100%}
@media(max-width:700px){.gear-loadout{grid-template-columns:minmax(0,1fr)}
 .gear-paperdoll{margin:auto}.gear-metric-value{font-size:20px}}
"""
_POSITIONS = {
    "head": (1, 2),
    "cape": (2, 1),
    "neck": (2, 2),
    "ammunition": (2, 3),
    "weapon": (3, 1),
    "body": (3, 2),
    "shield": (3, 3),
    "legs": (4, 2),
    "hands": (5, 1),
    "feet": (5, 2),
    "ring": (5, 3),
}


def icon_path(item_id: int | None) -> Path | None:
    path = _ICONS / f"{item_id}.png"
    return path if item_id is not None and path.is_file() else None


def item_name(item_id: int | None, definitions: Mapping[int, Any]) -> str:
    if item_id is None:
        return "Empty"
    return str(definitions.get(int(item_id), {}).get("name", f"Item {item_id}"))


def result_definitions(catalog: Mapping[int, Any], answer: Mapping[str, Any]) -> dict[int, Any]:
    """Use current request facts, including explicit hypothetical eligibility."""
    return {
        **catalog,
        **{
            int(item["item_id"]): {**catalog.get(int(item["item_id"]), {}), **item}
            for item in answer.get("items", [])
            if isinstance(item, Mapping)
        },
    }


def eligibility_text(item: Mapping[str, Any]) -> str:
    wear = item.get("wear", {}).get("status", "unknown")
    ownership = item.get("ownership", {}).get("status", "unknown")
    held = {
        "owned": "Observed owned",
        "unowned": "Not observed in complete scans",
        "unknown": "Ownership unknown (incomplete scans)",
    }.get(ownership, ownership)
    return f"Requirements: {wear}. {held}. Acquisition: {item.get('acquisition', 'unknown')}."


def action_text(action: Mapping[str, Any], definitions: Mapping[int, Any]) -> str:
    text = (
        f"{str(action.get('operation', 'equip')).capitalize()} "
        f"{item_name(action.get('item_id'), definitions)} ({action.get('slot', '?')})"
    )
    removed = action.get("automatically_removed", [])
    if removed:
        text += "; automatically removes " + ", ".join(item_name(i, definitions) for i in removed)
    return text + f" · {action.get('gear_inventory_slots', '?')} gear inventory slots after action"


def alternatives_for(answer: Mapping[str, Any], solution: Mapping[str, Any]) -> Mapping[str, Any]:
    """Service deltas describe its single-role selected surrounding equipment only."""
    selected = answer.get("selected_solution") or {}
    if len(solution.get("loadouts", {})) != 1:
        return {}
    if solution.get("loadouts") != selected.get("loadouts"):
        return {}
    return answer.get("alternatives", {})


def _sprite(item_id: int | None, name: str) -> None:
    path = icon_path(item_id)
    if path:
        ui.image(path).classes("gear-sprite").props(f'fit=contain alt="{name}"')
    else:
        ui.icon("checkroom" if item_id is None else "inventory_2", size="28px").classes(
            "tracker-faint"
        )


def _metric(label: str, value: str) -> None:
    with ui.column().classes("gap-0"):
        ui.label(value).classes("gear-metric-value")
        ui.label(label).classes("gear-metric-caption")


def _slot_detail(
    role: str,
    slot: str,
    item_id: int | None,
    definitions: Mapping[int, Any],
    alternatives: Mapping[str, Any],
    on_alternative: Callable[..., Any] | None,
) -> None:
    name = item_name(item_id, definitions)
    with ui.row().classes("items-center"):
        _sprite(item_id, name)
        ui.label(f"{slot.title()} · {name}").classes("text-lg font-semibold")
    item = definitions.get(item_id, {}) if item_id is not None else {}
    ui.label(
        eligibility_text(item) if item_id is not None else "Empty slot; no equipment requirements."
    ).classes("text-sm tracker-dim")
    if item:
        with ui.expansion("Eligibility and ownership evidence").classes("w-full"):
            for field in ("wear", "ownership", "price", "limitations"):
                if item.get(field):
                    ui.label(f"{field.title()}: {item[field]}").classes("text-sm tracker-dim")
    ui.label("Select a slot to inspect its item and compatible alternatives.").classes(
        "text-sm tracker-dim"
    )
    rows = alternatives.get(slot, [])
    if rows:
        with ui.expansion("Compatible alternatives").classes("w-full"):
            ui.label(
                "DPS differences use this exact surrounding setup; selection locks this role "
                "and reruns all validation."
            ).classes("text-xs tracker-dim")
            for alternative in rows:
                alternative_id = alternative["item_id"]
                alternative_name = item_name(alternative_id, definitions)
                with ui.column().classes("gear-alternative gap-1"):
                    with ui.row().classes("items-center"):
                        _sprite(alternative_id, alternative_name)
                        ui.label(alternative_name).classes("font-semibold")
                    ui.label(
                        f"{alternative['score_delta']:+.4f} DPS; "
                        f"setup purchases {alternative['purchase_cost_gp']:,} gp"
                    )
                    ui.label(
                        "Validated for this setup: eligibility, equipment compatibility, "
                        "ownership mode, budget and inventory constraints."
                    ).classes("text-xs")
                    ui.label(
                        eligibility_text(definitions.get(alternative_id, {}))
                        if alternative_id is not None
                        else "Empty slot; no equipment requirements."
                    ).classes("text-xs tracker-dim")
                    if on_alternative:
                        ui.button(
                            f"Use {alternative_name}",
                            on_click=partial(on_alternative, role, slot, alternative_id),
                        ).props(
                            f"outline data-testid=gear-alternative-{slot}-"
                            f"{alternative_id or 'empty'}"
                        )
    elif not alternatives:
        ui.label(
            "Slot DPS alternatives are available for the selected single-role result. "
            "Use role slot locks to compare another setup."
        ).classes("text-sm tracker-dim")
    else:
        ui.label("No other validated candidate for this slot in the current search pool.").classes(
            "text-sm tracker-dim"
        )


def render_summary(solution: Mapping[str, Any]) -> None:
    with ui.row().classes("gear-metrics"):
        score = solution.get("score")
        _metric("Encounter score · weighted DPS", f"{score:.3f}" if score is not None else "—")
        _metric("Additional purchases", f"{solution.get('purchase_cost_gp', 0):,} gp")
        _metric("Maximum gear inventory", str(solution.get("max_gear_inventory_slots", "?")))
        _metric("Free after reserved supplies", str(solution.get("remaining_inventory_slots", "?")))
    # Retain the explicit score label for existing automation and accessibility.
    ui.label(f"Encounter score: {score if score is not None else 'unavailable'}").classes(
        "text-sm tracker-dim"
    )
    for role, loadout in solution.get("loadouts", {}).items():
        performance = loadout.get("performance") or {}
        with ui.row().classes("gear-metrics"):
            ui.label(role.title()).classes("font-semibold")
            dps = performance.get("dps")
            accuracy = performance.get("accuracy")
            interval = performance.get("attack_interval")
            _metric("DPS", f"{dps:.3f}" if dps is not None else "Unscored utility")
            _metric("Max hit", str(performance.get("max_hit", "—")))
            _metric("Accuracy", f"{accuracy:.1%}" if accuracy is not None else "—")
            _metric("Attack interval", f"{interval:g}s" if interval is not None else "—")
        bonuses = performance.get("bonuses", {})
        with ui.row().classes("gap-5"):
            for field, label in (
                ("melee_strength", "Melee strength bonus"),
                ("ranged_strength", "Ranged strength bonus"),
            ):
                if field in bonuses:
                    ui.label(f"{label}: {bonuses[field]:+}").props(
                        f"data-testid=gear-{role}-{field}"
                    ).classes("text-sm")


def render_solution(
    solution: Mapping[str, Any],
    definitions: Mapping[int, Any],
    alternatives: Mapping[str, Any] | None = None,
    on_alternative: Callable[..., Any] | None = None,
    *,
    show_summary: bool = True,
) -> None:
    if show_summary:
        render_summary(solution)
    for role, loadout in solution.get("loadouts", {}).items():
        with ui.column().classes("gear-role"):
            ui.label(f"{role.title()} equipment").classes("text-xl font-semibold")
            performance = loadout.get("performance") or {}
            equipment = loadout.get("equipment", {})
            with ui.element("div").classes("gear-loadout"):
                buttons = {}
                with (
                    ui.element("div")
                    .classes("gear-paperdoll")
                    .props(f"data-testid=gear-{role}-paperdoll")
                ):
                    for slot in SLOTS:
                        item_id = equipment.get(slot)
                        name = item_name(item_id, definitions)
                        row, column = _POSITIONS[slot]
                        with (
                            ui.button(color=None)
                            .classes("gear-slot")
                            .style(f"grid-row:{row};grid-column:{column}")
                            .props(
                                f'aria-label="Inspect {slot}: {name}" '
                                f"data-testid=gear-{role}-slot-{slot}"
                            ) as button
                        ):
                            ui.label(slot.title()).classes("gear-slot-label")
                            _sprite(item_id, name)
                            ui.label(name).classes("gear-slot-name")
                        buttons[slot] = button
                detail = (
                    ui.column()
                    .classes("gear-slot-detail")
                    .props(f"data-testid=gear-{role}-slot-detail")
                )

                def select_slot(
                    slot: str, *, role=role, equipment=equipment, detail=detail, buttons=buttons
                ) -> None:
                    detail.clear()
                    for key, button in buttons.items():
                        button.classes(
                            add="gear-slot-selected" if key == slot else "",
                            remove="gear-slot-selected" if key != slot else "",
                        )
                    with detail:
                        _slot_detail(
                            role,
                            slot,
                            equipment.get(slot),
                            definitions,
                            alternatives or {},
                            on_alternative,
                        )

                for slot, button in buttons.items():
                    button.on_click(partial(select_slot, slot))
                select_slot("weapon")
            with ui.expansion("Equipment bonuses and combat calculation").classes("w-full"):
                for key, value in performance.items():
                    ui.label(f"{key.replace('_', ' ').title()}: {value}").classes("text-sm")
    _inventory(solution, definitions)


def _inventory(solution: Mapping[str, Any], definitions: Mapping[int, Any]) -> None:
    with ui.column().classes("gear-summary gap-2").props("data-testid=gear-inventory-plan"):
        ui.label("Inventory and exact equipment changes").classes("text-lg font-semibold")
        ui.label(
            f"Gear inventory at base: {solution.get('gear_inventory_slots', '?')} · "
            f"Maximum gear inventory: {solution.get('max_gear_inventory_slots', '?')} · "
            f"Reserved supplies: {solution.get('reserved_supply_slots', '?')} · "
            f"Free after reserved supplies: {solution.get('remaining_inventory_slots', '?')}"
        )
        carried = solution.get("carried_item_ids", [])
        ui.label(
            "Required equipment (one usable instance or stack of each): "
            + (", ".join(item_name(i, definitions) for i in carried) or "None")
        )
        for transition in solution.get("transitions", []):
            ui.label(
                f"{transition.get('from_role')} → {transition.get('to_role')}: "
                f"{transition.get('action_count', '?')} actions · "
                f"peak {transition.get('max_gear_inventory_slots', '?')} gear slots"
            ).classes("font-semibold")
            for index, action in enumerate(transition.get("actions", []), 1):
                ui.label(f"{index}. {action_text(action, definitions)}").classes("text-sm")
        purchases = solution.get("purchases", [])
        if purchases:
            with ui.expansion("Purchase list and ownership uncertainty").classes("w-full"):
                for purchase in purchases:
                    ui.label(
                        f"{item_name(purchase['item_id'], definitions)} · "
                        f"{purchase['cost_gp']:,} gp"
                        + (
                            " · conditional: ownership unknown"
                            if purchase.get("conditional")
                            else ""
                        )
                    )
