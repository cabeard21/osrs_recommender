"""Factual presentation of GearService progression output."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from time import perf_counter
from typing import Any

from nicegui import ui

from tracker.accounts.snapshot import AccountSnapshot
from tracker.estimation.prices import PriceRecord
from tracker.gear.combat import SPELLS
from tracker.gear.service import GearService
from tracker.ui.gear_presentation import (
    GEAR_CSS,
    alternatives_for,
    render_solution,
    render_summary,
    result_definitions,
)
from tracker.ui.shell import section

_LOGGER = logging.getLogger(__name__)
_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gear-ui")
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
ContextProvider = Callable[[], tuple[AccountSnapshot, Mapping[int, PriceRecord], datetime]]


@dataclass
class OptimizationRun:
    """A page-local generation prevents a replaced request publishing stale results."""

    generation: int = 0
    snapshot_id: str = ""

    def begin(self, snapshot_id: str) -> int:
        self.generation += 1
        self.snapshot_id = snapshot_id
        return self.generation

    def cancel(self) -> None:
        self.generation += 1

    def accepts(self, generation: int, snapshot_id: str) -> bool:
        return generation == self.generation and snapshot_id == self.snapshot_id


def request_values(
    *,
    roles: list[dict[str, Any]],
    base_role: str | None = None,
    transition_mode: str = "base",
    transition_text: str = "",
    phase_text: str = "",
    loop: bool = False,
    locks: Mapping[str, Any] | None = None,
    budget_gp: float = 0,
    reserved_supply_slots: int = 12,
    max_swaps: int = 8,
    mode: str = "usable",
    **extra: Any,
) -> dict[str, Any]:
    """Translate controls without inventing extra encounter transitions."""
    if int(budget_gp) != budget_gp or budget_gp < 0:
        raise ValueError("Additional GP must be a nonnegative whole number.")
    ids = [role["id"] for role in roles]
    if not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise ValueError("Choose between one and four distinct roles.")
    base = base_role or ids[0]
    if base not in ids:
        raise ValueError("Base setup must be an enabled role.")
    transitions: list[tuple[str, str]] = []
    ordered: list[str] = []
    if transition_mode == "ordered":
        ordered = [part.strip() for part in phase_text.split(">")]
        if not phase_text.strip():
            ordered = ids
        if len(ordered) > 100 or any(value not in ids for value in ordered):
            raise ValueError(
                "Ordered phases must reference enabled roles, with at most 100 phases."
            )
    elif transition_mode == "custom":
        for line in transition_text.splitlines():
            if not line.strip():
                continue
            pair = tuple(part.strip() for part in line.split(">"))
            if len(pair) != 2 or any(value not in ids for value in pair) or pair[0] == pair[1]:
                raise ValueError("Each transition must be enabled-role > enabled-role.")
            transitions.append((pair[0], pair[1]))
        if len(ids) > 1 and not transitions:
            raise ValueError("Declare at least one transition.")
    else:
        transitions = [
            (a, b) for other in ids if other != base for a, b in ((base, other), (other, base))
        ]
    return {
        "roles": roles,
        "base_role": base,
        "transitions": transitions,
        "ordered_roles": ordered,
        "loop": loop,
        "locks": {
            key: None if value == "empty" else int(value)
            for key, value in (locks or {}).items()
            if value not in ("any", "", None)
        },
        "budget_gp": int(budget_gp),
        "reserved_supply_slots": reserved_supply_slots,
        "max_swaps": max_swaps,
        "mode": mode,
        **extra,
    }


def _assignments(text: str, *, numeric: bool = False) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise ValueError("Use one name=value assumption per line.")
        values[key.strip()] = int(value.strip()) if numeric else value.strip()
    return values


def _whole(value: Any, label: str) -> int:
    if value is None or int(value) != value:
        raise ValueError(f"{label} must be a whole number.")
    return int(value)


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


def render_optimizer(service: GearService, context: ContextProvider) -> None:
    """Interactive account-aware workbench using the shared service operation."""
    snapshot, prices, evaluated_at = context()
    from tracker.gear.encounters import encounter_presets

    presets = {preset.id: preset for preset in encounter_presets()}
    catalog = service.optimizer_catalog(snapshot, price_records=prices, now=evaluated_at)
    items = catalog.get("items", []) if isinstance(catalog, Mapping) else catalog
    definitions = {int(item.get("item_id", item.get("numeric_item_id"))): item for item in items}
    state = OptimizationRun()
    ui.add_css(GEAR_CSS)
    ui.label("Equipment optimizer").classes("text-xl font-semibold").props(
        "data-testid=gear-optimizer"
    )
    ui.label(
        "Observed ownership is dated evidence. Missing or stale scans do not prove absence. "
        "Results use a documented, limited combat model and deterministic bounded search."
    ).classes("text-sm tracker-dim")

    with section("Account and encounter"):
        preset_control = ui.select(
            {
                "custom": "Custom target and roles",
                **{key: value.name for key, value in presets.items()},
            },
            value="custom",
            label="Encounter preset",
        ).classes("w-full")
        ui.label(
            "Presets supply roles, targets, and ordered transitions. Global locks and account "
            "constraints still apply; custom role controls apply only to Custom."
        ).classes("text-sm")
        with ui.row().classes("w-full items-end"):
            mode = ui.select(
                {
                    "owned": "Observed owned only",
                    "usable": "Usable and purchasable",
                    "future": "Future / explicit what-if",
                },
                value="usable",
                label="Equipment access",
            ).props("data-testid=gear-mode")
            budget = ui.number("Additional GP", value=0, min=0, step=1000).style("min-width:165px")
            supplies = ui.number("Reserve supply slots", value=12, min=0, max=28, step=1).style(
                "min-width:165px"
            )
            maximum = ui.number("Curve maximum actions", value=8, min=0, max=12, step=1).style(
                "min-width:165px"
            )
        with ui.expansion("Target and future assumptions").classes("w-full"):
            ui.label("Default target: Defence 1, Magic 1, zero bonuses; no boosts or prayers.")
            with ui.row():
                target_name = ui.input("Target name", value="Generic target")
                defence = ui.number("Target Defence", value=1, min=0, step=1)
                magic = ui.number("Target Magic", value=1, min=0, step=1)
            with ui.row():
                target_bonuses = {
                    style: ui.number(f"Target {style} defence bonus", value=0, step=1)
                    for style in ("stab", "slash", "crush", "ranged", "magic")
                }
            skills = ui.textarea(
                "Future skill levels (one skill=level per line)", placeholder="attack=60"
            )
            quests = ui.textarea(
                "Future quest facts (quest-id=status)", placeholder="monkey_madness_i=complete"
            )
            assumed = ui.input("Assumed acquired item IDs, comma separated")
            ui.label(
                "Assumptions apply to this calculation only; synchronized facts are preserved."
            )

    def locks_control(label: str) -> dict[str, Any]:
        controls = {}
        with (
            ui.expansion(label).classes("w-full"),
            ui.element("div").classes("grid grid-cols-2 md:grid-cols-3 gap-2 w-full"),
        ):
            for slot in SLOTS:
                options = {"any": "Optimize", "empty": "Lock empty"}
                options.update(
                    {
                        str(key): str(item["name"])
                        for key, item in definitions.items()
                        if item.get("slot") == slot
                    }
                )
                controls[slot] = ui.select(
                    options, value="any", label=slot.title(), with_input=True
                ).classes("w-full")
        return controls

    status = ui.label("Choose equipment access and roles, then optimize.")
    with ui.row().classes("items-center"):
        ui.button("Optimize equipment", on_click=lambda: calculate()).props(
            "data-testid=gear-optimize"
        )
        ui.button("Cancel / clear result", on_click=lambda: invalidate()).props("flat")
    results = ui.column().classes("w-full").props("data-testid=gear-results")
    with results:
        ui.label("Your selected equipment and combat performance will appear here.").classes(
            "tracker-dim"
        )
    global_locks = locks_control("Global slot locks — all roles")
    role_controls: list[dict[str, Any]] = []
    with (
        ui.expansion("Combat roles and transitions")
        .classes("w-full")
        .props("data-testid=gear-roles")
    ):
        ui.label("Enable up to four roles. Weights are active-time shares and are normalized.")
        for name, style in (
            ("melee", "slash"),
            ("ranged", "ranged"),
            ("magic", "magic"),
            ("special", "special"),
        ):
            with ui.expansion(name.title(), value=name == "melee").classes("w-full"):
                enabled = ui.checkbox(f"Use {name}", value=name == "melee")
                with ui.row():
                    styles = ["stab", "slash", "crush"] if name == "melee" else [style]
                    attack = ui.select(styles, value=style, label="Attack type")
                    stance = ui.select(
                        ["accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"],
                        value="accurate",
                        label="Stance",
                    )
                    spell = ui.select(
                        list(SPELLS),
                        value="fire_strike",
                        label="Spell",
                    )
                    weight = ui.number("Active-time share", value=1, min=0, step=0.1)
                parent = None
                if name == "special":
                    ui.label("Utility is unscored. Lock its weapon; other slots remain optimized.")
                    parent = ui.select(
                        ["melee", "ranged", "magic"], value="melee", label="Parent combat role"
                    )
                role_controls.append(
                    {
                        "id": name,
                        "enabled": enabled,
                        "attack": attack,
                        "stance": stance,
                        "spell": spell,
                        "weight": weight,
                        "parent": parent,
                        "locks": locks_control("Role slot locks"),
                    }
                )
        with ui.row():
            base = ui.select(
                ["melee", "ranged", "magic", "special"], value="melee", label="Base equipment role"
            )
            topology = ui.select(
                {
                    "base": "Base ↔ each role",
                    "ordered": "Ordered phases",
                    "custom": "Custom directed transitions",
                },
                value="base",
                label="Required transitions",
            )
            loop = ui.checkbox("Loop last phase to first")
        edges = ui.textarea(
            "Custom transitions (one from > to per line)",
            placeholder="melee > ranged\nranged > magic\nmagic > melee",
        )
        phases = ui.input(
            "Ordered phases (optional, role > role)", placeholder="melee > magic > melee > ranged"
        ).classes("w-full")

    def invalidate() -> None:
        state.cancel()
        results.clear()
        status.set_text("Inputs changed. Optimize again for current assumptions.")

    async def calculate() -> None:
        results.clear()
        generation: int | None = None
        try:
            fresh, price_records, at = context()
            snapshot_id = fresh.fingerprint
            generation = state.begin(snapshot_id)
            roles = []
            for control in role_controls:
                if not control["enabled"].value:
                    continue
                role = {
                    "id": control["id"],
                    "style": control["attack"].value,
                    "stance": control["stance"].value,
                    "spell": control["spell"].value,
                    "weight": control["weight"].value,
                    "target": {
                        "name": target_name.value,
                        "defence_level": _whole(defence.value, "Target Defence"),
                        "magic_level": _whole(magic.value, "Target Magic"),
                        "bonuses": {
                            key: _whole(control.value, "Defence bonus")
                            for key, control in target_bonuses.items()
                        },
                    },
                    "locks": request_values(
                        roles=[{"id": "temp", "style": "slash"}],
                        locks={key: value.value for key, value in control["locks"].items()},
                    )["locks"],
                }
                if control["parent"] is not None:
                    role["parent_role"] = control["parent"].value
                roles.append(role)
            preset = presets.get(preset_control.value)
            if preset is not None:
                roles = [role.model_dump(mode="json") for role in preset.roles]
            request = request_values(
                roles=roles,
                base_role=preset.ordered_roles[0] if preset else base.value,
                transition_mode="ordered" if preset else topology.value,
                transition_text=edges.value or "",
                phase_text=" > ".join(preset.ordered_roles) if preset else (phases.value or ""),
                loop=preset.loop if preset else loop.value,
                locks={key: value.value for key, value in global_locks.items()},
                budget_gp=budget.value,
                mode=mode.value,
                reserved_supply_slots=_whole(supplies.value, "Supply reservation"),
                max_swaps=_whole(maximum.value, "Curve maximum"),
                skill_overrides=_assignments(skills.value or "", numeric=True),
                quest_overrides=_assignments(quests.value or ""),
                assumed_item_ids=[
                    int(value.strip())
                    for value in (assumed.value or "").split(",")
                    if value.strip()
                ],
                expected_snapshot_id=snapshot_id,
            )
            status.set_text("Optimizing… queued work runs outside the dashboard event loop.")
            future = _WORKER.submit(
                partial(
                    service.optimize,
                    fresh,
                    request,
                    price_records=price_records,
                    now=at,
                    cancelled=lambda: not state.accepts(generation, snapshot_id),
                )
            )
            answer = await asyncio.wrap_future(future)
            current, _, _ = context()
            if not state.accepts(generation, current.fingerprint):
                if generation == state.generation:
                    status.set_text(
                        "Account observations changed. Optimize again for current facts."
                    )
                return
            status.set_text("Best found under the supported combat model.")
            render_started = perf_counter()
            with results:
                _optimizer_results(answer, definitions, on_alternative=choose_alternative)
            render_elapsed = perf_counter() - render_started
            results.props(f"data-render-seconds={render_elapsed:.6f}")
            _LOGGER.info("Gear result NiceGUI construction: %.6fs", render_elapsed)
        except ValueError as error:
            if str(error) != "optimization_cancelled" and generation == state.generation:
                status.set_text(f"Check inputs: {error}")
        except Exception:
            _LOGGER.exception("Gear optimization failed")
            if generation is None or generation == state.generation:
                status.set_text("Optimization could not finish. Review inputs or try again.")

    async def choose_alternative(role: str, slot: str, item_id: int | None) -> None:
        control = next(control for control in role_controls if control["id"] == role)
        control["locks"][slot].set_value("empty" if item_id is None else str(item_id))
        await calculate()

    # Any edited input invalidates an in-flight result, even before the next request.
    controls = [
        mode,
        preset_control,
        budget,
        supplies,
        maximum,
        target_name,
        defence,
        magic,
        skills,
        quests,
        assumed,
        base,
        topology,
        loop,
        edges,
        phases,
        *global_locks.values(),
        *target_bonuses.values(),
    ]
    for control in role_controls:
        controls.extend(
            value
            for key, value in control.items()
            if key not in ("id", "locks") and value is not None
        )
        controls.extend(control["locks"].values())
    for control in controls:
        control.on_value_change(lambda _: invalidate())
    with (
        ui.expansion("Equipment catalog and requirements")
        .classes("w-full")
        .props("data-testid=gear-catalog")
    ):
        ui.label("Inspect future and unsupported items here; selecting a slot lock reruns search.")
        search = ui.input("Find item").classes("w-full")
        listing = ui.column().classes("w-full")

        def show_items() -> None:
            listing.clear()
            matches = [
                item
                for item in items
                if (search.value or "").lower() in str(item.get("name", "")).lower()
            ]
            with listing:
                ui.label(f"{len(matches)} matching items; showing first 40.")
                for item in matches[:40]:
                    with ui.expansion(str(item.get("name", "Unknown item"))).classes("w-full"):
                        _fact_labels(item)

        search.on_value_change(lambda _: show_items())
        # Catalog facts remain available without building forty hidden detail panels on load.
        ui.button("Browse matching items", on_click=show_items).props("outline")
    with ui.expansion("Encounter preset assumptions").classes("w-full"):
        for preset in presets.values():
            ui.label(
                f"{preset.name}: {'supported' if preset.scoring_supported else 'not yet scored'}"
            )
            for limitation in preset.limitations:
                ui.label(limitation).classes("text-sm tracker-dim")


def _fact_labels(item: Mapping[str, Any]) -> None:
    equipment = item.get("equipment", {})
    if equipment:
        ui.label(
            f"Attack profiles: {_readable(equipment.get('attack_profiles', []))}; "
            f"speed: {equipment.get('attack_speed', '?')} ticks; "
            f"two handed: {equipment.get('two_handed', False)}"
        ).classes("text-sm")
    for key, label in (
        ("wear", "Requirements"),
        ("ownership", "Observed ownership"),
        ("price", "Price"),
        ("limitations", "Limitations"),
    ):
        value = item.get(key)
        if value is not None:
            ui.label(f"{label}: {_readable(value)}").classes("text-sm tracker-dim")


def _readable(value: Any) -> str:
    if isinstance(value, Mapping):
        return "; ".join(
            f"{key.replace('_', ' ')}: {_readable(part)}"
            for key, part in value.items()
            if part is not None
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(_readable(part) for part in value)
    return str(value)


def _optimizer_results(
    answer: Mapping[str, Any],
    definitions: Mapping[int, Any],
    on_alternative: Callable[..., Any] | None = None,
) -> None:
    definitions = result_definitions(definitions, answer)
    curve = answer.get("curve", [])
    multi_style = len((answer.get("selected_solution") or {}).get("loadouts", {})) > 1
    summary = ui.column().classes("w-full order-0").props("data-testid=gear-combat-summary")
    detail = (
        ui.column()
        .classes(f"w-full order-{2 if multi_style else 1}")
        .props("data-testid=gear-selected-solution")
    )

    def select(point: Mapping[str, Any]) -> None:
        summary.clear()
        detail.clear()
        solution = point.get("solution")
        if solution:
            with summary:
                render_summary(solution)
                relative = point.get("relative_performance")
                ui.label(
                    f"Selected action limit: {point.get('swap_limit', '?')}"
                    + (f" · relative performance {relative:.1%}" if relative is not None else "")
                ).classes("text-sm tracker-dim").props("data-testid=gear-selected-action-limit")
        with detail:
            if not solution:
                ui.label(
                    "No feasible solution found under this action limit and model. "
                    "Check eligibility, ownership, budget, and legal weapon/stance profiles."
                )
                return
            _solution(
                solution,
                definitions,
                alternatives_for(answer, solution),
                on_alternative,
                show_summary=False,
            )

    if curve:
        import plotly.graph_objects as go

        with (
            ui.column()
            .classes(f"w-full order-{1 if multi_style else 2}")
            .props("data-testid=gear-swap-curve")
        ):
            ui.label("Swap efficiency").classes("text-xl font-semibold")
            ui.label(
                "Click a point to inspect its exact gear, DPS and inventory plan. "
                "Relative to the best-found unrestricted setup."
            ).classes("text-sm tracker-dim")
            figure = go.Figure(
                go.Scatter(
                    x=[point["swap_limit"] for point in curve],
                    y=[point.get("relative_performance") for point in curve],
                    mode="lines+markers",
                    connectgaps=False,
                    line={"color": "#e0a83c", "width": 3},
                    marker={"size": 9},
                    hovertemplate="%{x} actions · %{y:.1%} performance<extra></extra>",
                )
            )
            figure.update_layout(
                xaxis_title="Actions per transition",
                yaxis_title="Relative encounter performance",
                yaxis_tickformat=".0%",
                yaxis_range=[
                    0,
                    max(
                        1.05,
                        max((point.get("relative_performance") or 0) * 1.05 for point in curve),
                    ),
                ],
                height=245,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "#9d917c"},
                margin={"l": 70, "r": 10, "t": 20, "b": 45},
            )
            plot = ui.plotly(figure).classes("w-full")

            def clicked(event: Any) -> None:
                points = event.args.get("points", []) if isinstance(event.args, Mapping) else []
                if points:
                    index = points[0].get("pointIndex", points[0].get("pointNumber", 0))
                    if 0 <= index < len(curve):
                        picker.set_value(str(index))

            plot.on("plotly_click", clicked)
            columns = [
                {"name": key, "label": label, "field": key}
                for key, label in (
                    ("swap_limit", "Action limit"),
                    ("performance", "Relative performance"),
                    ("status", "Search result"),
                )
            ]
            rows = [
                {
                    "swap_limit": point["swap_limit"],
                    "status": point.get("status", ""),
                    "performance": f"{point['relative_performance']:.1%}"
                    if point.get("relative_performance") is not None
                    else "Undefined",
                }
                for point in curve
            ]
            with ui.expansion("All curve points and search status").classes("w-full"):
                ui.table(columns=columns, rows=rows, row_key="swap_limit").classes("w-full")
            options = {
                str(index): f"{point['swap_limit']} actions" for index, point in enumerate(curve)
            }
            suggestion = answer.get("suggested_swap_limit")
            selected = next(
                (index for index, point in enumerate(curve) if point["swap_limit"] == suggestion), 0
            )
            if suggestion is not None:
                ui.label(
                    f"Efficiency suggestion: {suggestion} actions reach at least 95% "
                    "of the best-found unrestricted score."
                )
            picker = (
                ui.select(options, label="Inspect curve point", value=str(selected))
                .style("min-width:200px")
                .props("data-testid=gear-curve-picker")
            )
            picker.on_value_change(lambda event: select(curve[int(event.value)]))
            select(curve[selected])
    elif answer.get("selected_solution"):
        with detail:
            _solution(
                answer["selected_solution"],
                definitions,
                alternatives_for(answer, answer["selected_solution"]),
                on_alternative,
            )
    else:
        ui.label("No feasible solution found under these assumptions.")
    with (
        ui.expansion("Search diagnostics, assumptions and model limits")
        .classes("w-full order-3")
        .props("data-testid=gear-diagnostics")
    ):
        ui.label(f"Search: {_readable(answer.get('search', {}))}").classes("text-xs")
        for limitation in answer.get("limitations", []):
            ui.label(str(limitation)).classes("text-sm tracker-dim")
        if answer.get("assumptions"):
            ui.label(f"Calculation assumptions: {_readable(answer['assumptions'])}")
    if answer.get("items"):
        with ui.expansion("Candidate and exclusion explanations").classes("w-full order-4"):
            for item in answer["items"]:
                if isinstance(item, Mapping):
                    ui.label(str(item.get("name", item.get("item_id", "Equipment"))))
                    _fact_labels(item)


def _solution(
    solution: Mapping[str, Any],
    definitions: Mapping[int, Any],
    alternatives: Mapping[str, Any] | None = None,
    on_alternative: Callable[..., Any] | None = None,
    *,
    show_summary: bool = True,
) -> None:
    render_solution(solution, definitions, alternatives, on_alternative, show_summary=show_summary)
