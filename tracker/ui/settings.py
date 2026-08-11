"""§9.6, §11.2, §7.5, §15's settings page.

**§9.6 is explicit about vocabulary**: *"The UI never says 'κ' or even 'GP sensitivity'."*
It asks one question, in three words the player already understands:

> How strongly should expensive upgrades be deprioritized?

with the answer as Strongly / Normally / Barely — never as the internal ``high | normal |
low`` names and never as a κ value. :data:`~tracker.ui.view_model.GP_SENSITIVITY_LABELS` is
the one place that mapping exists; this module reads it rather than repeating it, and a test
greps this page's rendered source for the forbidden tokens directly.

**Bind address and token presence, never the token value** (§15, §11.2). The token is a
bearer credential shared with the RuneLite plugin; a settings page that echoed it back would
turn a screenshot into a credential leak. Only whether one is configured is shown.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from tracker.domain.types import GpSensitivity
from tracker.ui.shell import section
from tracker.ui.view_model import GP_SENSITIVITY_LABELS, SENSITIVITY_QUESTION, SettingsView

SensitivityHandler = Callable[[GpSensitivity], None]

#: Display order for the three-way question — strongest deprioritization first, since that
#: is the more common PvP-progression choice (§9.6's own table orders it this way too).
_SENSITIVITY_ORDER: tuple[GpSensitivity, ...] = (
    GpSensitivity.HIGH,
    GpSensitivity.NORMAL,
    GpSensitivity.LOW,
)


def render(view: SettingsView, *, on_set_sensitivity: SensitivityHandler) -> None:
    """The whole page: the sensitivity question, roadmap-adjacent config, and attribution."""
    with section("Upgrade cost", testid="settings-sensitivity"):
        ui.html(SENSITIVITY_QUESTION).classes("text-sm block mb-1")
        group = ui.radio(
            {level.value: GP_SENSITIVITY_LABELS[level] for level in _SENSITIVITY_ORDER},
            value=view.gp_sensitivity.value,
            on_change=lambda event: on_set_sensitivity(GpSensitivity(event.value)),
        )
        group.props("data-testid=gp-sensitivity-radio")

    with section("Connection", testid="settings-connection"):
        with ui.element("div").classes("layer-row"):
            ui.html("Bind address").classes("layer-label")
            element = ui.html(view.bind_address)
            element.props("data-testid=bind-address")
        with ui.element("div").classes("layer-row"):
            ui.html("Port").classes("layer-label")
            ui.html(str(view.port))
        with ui.element("div").classes("layer-row"):
            ui.html("Sync token").classes("layer-label")
            token = ui.html("configured" if view.api_token_present else "not configured")
            token.props(
                f"data-testid=token-presence data-present={str(view.api_token_present).lower()}"
            )

    footer = ui.element("p").classes("text-xs opacity-60 mt-2")
    footer.props("data-testid=price-attribution")
    with footer:
        ui.html(f"Prices from {view.price_provider} ({view.price_base_url}).")
