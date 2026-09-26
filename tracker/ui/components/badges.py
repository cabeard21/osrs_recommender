"""Shared factual status and freshness labels."""

from __future__ import annotations

from nicegui import ui

from tracker.ui.states import STATE_CLASSES, STATE_LABELS, UiState, state_props


def state_badge(state: UiState, *, label: str | None = None) -> ui.element:
    element = ui.element("span").classes(f"state-badge {STATE_CLASSES[state]}")
    element.props(state_props(state))
    with element:
        ui.label(label if label is not None else STATE_LABELS[state])
    return element


def staleness_note(message: str) -> ui.element:
    element = ui.element("p").classes("text-xs tracker-dim m-0")
    element.props("data-testid=staleness-note")
    with element:
        ui.label(message)
    return element
