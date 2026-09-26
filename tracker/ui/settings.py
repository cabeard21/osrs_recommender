"""Account settings, connection observability, and a retained GP preference.

The GP preference remains editable but is currently not applied by factual Gear, price,
budget, or MCP operations. The bearer token is represented only by its presence.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from tracker.domain.types import AccountType, GpSensitivity
from tracker.ui.shell import section
from tracker.ui.view_model import (
    ACCOUNT_TYPE_LABELS,
    ACCOUNT_TYPE_NOTE,
    ACCOUNT_TYPE_QUESTION,
    ACCOUNT_TYPE_UNSET,
    GP_SENSITIVITY_LABELS,
    MEMBERS_QUESTION,
    MEMBERS_UNSET,
    SENSITIVITY_QUESTION,
    SettingsView,
)

SensitivityHandler = Callable[[GpSensitivity], None]
UsernameHandler = Callable[[str], None]
AccountTypeHandler = Callable[[AccountType | None], None]
MembersHandler = Callable[[bool | None], None]

#: The radio value standing for "nobody has said". A sentinel string rather than ``None``
#: because NiceGUI's radio keys its options by value, and ``None`` as a key is
#: indistinguishable from "no option selected" — which would make the *unset* state
#: unselectable rather than merely unselected.
UNSET = "__unset__"

#: Display order for the three-way question — strongest deprioritization first, since that
#: is the more common PvP-progression choice (§9.6's own table orders it this way too).
_SENSITIVITY_ORDER: tuple[GpSensitivity, ...] = (
    GpSensitivity.HIGH,
    GpSensitivity.NORMAL,
    GpSensitivity.LOW,
)


def render(
    view: SettingsView,
    *,
    on_set_sensitivity: SensitivityHandler,
    on_set_username: UsernameHandler,
    on_set_account_type: AccountTypeHandler,
    on_set_members: MembersHandler,
) -> None:
    """The whole page: the tracked character, the sensitivity question, config, attribution."""
    with section("Character", testid="settings-character"):
        ui.html(
            "The account Wise Old Man follows. Set this to keep skills current while "
            "RuneLite is closed — it is also filled in automatically by your first sync."
        ).classes("text-sm block mb-1")
        field = ui.input(
            label="RuneScape username",
            value=view.tracked_username or "",
        )

        # Committed on blur or Enter, never per keystroke. Naming a character reloads the
        # page — a different account changes what every other page is about — and an
        # ``on_change`` handler fires once per letter, so typing "Rehvun" reloaded the page
        # six times and wrote five partial usernames on the way. The equality guard keeps
        # merely tabbing through the field from counting as a change.
        def commit() -> None:
            candidate = str(field.value or "").strip()
            if not candidate or candidate == (view.tracked_username or ""):
                return
            on_set_username(candidate)

        field.on("blur", commit)
        field.on("keydown.enter", commit)
        field.props(
            "data-testid=tracked-username "
            f"data-configured={str(view.tracked_username is not None).lower()}"
        )
        if view.tracked_username is None:
            note = ui.html("No character set — Wise Old Man cannot look anything up yet.")
            note.classes("text-xs tracker-faint")
            note.props("data-testid=no-username-note")

    with section("Upgrade cost", testid="settings-sensitivity"):
        ui.html(SENSITIVITY_QUESTION).classes("text-sm block mb-1")
        ui.html(
            "Saved for your account. This preference currently has no effect on "
            "Gear, prices, budget facts, or ChatGPT tools."
        ).classes("text-xs tracker-faint block mb-2")
        group = ui.radio(
            {level.value: GP_SENSITIVITY_LABELS[level] for level in _SENSITIVITY_ORDER},
            value=view.gp_sensitivity.value,
            on_change=lambda event: on_set_sensitivity(GpSensitivity(event.value)),
        )
        group.props("data-testid=gp-sensitivity-radio")

    with section("Account", testid="settings-account"):
        # An explicit "not set" option, and it is selected by default. §4.5 makes "nobody
        # has said" a real state, and a radio group without it would force the user to
        # assert something the moment the page renders — which is exactly how a wrong
        # default gets into the data looking like an answer.
        ui.html(ACCOUNT_TYPE_QUESTION).classes("text-sm block mb-1")
        options = {UNSET: ACCOUNT_TYPE_UNSET} | {
            account_type.value: ACCOUNT_TYPE_LABELS[account_type] for account_type in AccountType
        }
        account_group = ui.radio(
            options,
            value=view.account_type.value if view.account_type is not None else UNSET,
            on_change=lambda event: on_set_account_type(
                None if event.value == UNSET else AccountType(event.value)
            ),
        )
        account_group.props(
            "data-testid=account-type-radio "
            f"data-configured={str(view.account_type is not None).lower()}"
        )
        ui.html(ACCOUNT_TYPE_NOTE).classes("text-xs tracker-faint block")

        ui.html(MEMBERS_QUESTION).classes("text-sm block mb-1 mt-3")
        members_group = ui.radio(
            {UNSET: MEMBERS_UNSET, "true": "Members", "false": "Free-to-play"},
            value=UNSET if view.members is None else str(view.members).lower(),
            on_change=lambda event: on_set_members(
                None if event.value == UNSET else event.value == "true"
            ),
        )
        members_group.props(
            f"data-testid=members-radio data-configured={str(view.members is not None).lower()}"
        )

    with section("Connection", testid="settings-connection"):
        with ui.element("div").classes("layer-row"):
            ui.html("Bind address").classes("layer-label")
            element = ui.html(view.bind_address)
            element.props("data-testid=bind-address")
        with ui.element("div").classes("layer-row"):
            ui.html("Port").classes("layer-label")
            ui.html(str(view.port))
        with ui.element("div").classes("layer-row"):
            ui.html("Price cache").classes("layer-label")
            cache = ui.html(view.price_cache_label)
            cache.props(
                "data-testid=price-cache "
                f"data-rows={view.price_rows} "
                f"data-fetched={str(view.price_last_fetched_at is not None).lower()}"
            )
        with ui.element("div").classes("layer-row"):
            ui.html("Sync token").classes("layer-label")
            token = ui.html("configured" if view.api_token_present else "not configured")
            token.props(
                f"data-testid=token-presence data-present={str(view.api_token_present).lower()}"
            )

    footer = ui.element("p").classes("text-xs tracker-faint mt-2")
    footer.props("data-testid=price-attribution")
    with footer:
        ui.html(
            f"Prices from {view.price_provider} ({view.price_base_url}). "
            f"Skill data from Wise Old Man ({view.wom_base_url})."
        )
