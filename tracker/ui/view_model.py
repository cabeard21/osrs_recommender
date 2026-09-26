"""Immutable rows for factual dashboard pages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from tracker.domain.types import AccountType, GpSensitivity, UnlockState
from tracker.ui.states import UiState, ui_state_for_unlock


@dataclass(frozen=True, slots=True)
class UnlockRow:
    key: str
    name: str
    state: UiState
    unlock_state: UnlockState


def unlock_row(key: str, state: UnlockState) -> UnlockRow:
    return UnlockRow(key, key.replace("_", " ").title(), ui_state_for_unlock(state), state)


@dataclass(frozen=True, slots=True)
class SkillRow:
    skill_id: str
    name: str
    is_combat: bool
    is_ranked: bool
    level: int | None
    xp: int | None

    @property
    def level_label(self) -> str:
        return str(self.level) if self.is_ranked and self.level is not None else "unranked"

    @property
    def progress(self) -> float:
        if not self.is_ranked or self.level is None:
            return 0.0
        return min(1.0, max(0.0, self.level / 99.0))


def skill_row(
    *, skill_id: str, name: str, is_combat: bool, level: int | None, xp: int | None
) -> SkillRow:
    ranked = xp is not None and level is not None
    return SkillRow(
        skill_id, name, is_combat, ranked, level if ranked else None, xp if ranked else None
    )


@dataclass(frozen=True, slots=True)
class DashboardView:
    display_name: str
    combat_level: int | None
    quest_points: int | None
    last_sync_at_label: str
    staleness_notes: tuple[str, ...]
    quest_cape_completed: int
    quest_cape_total: int
    quest_cape_unknown: int
    quest_cape_available: int


GP_SENSITIVITY_LABELS: Mapping[GpSensitivity, str] = {
    GpSensitivity.HIGH: "Strongly",
    GpSensitivity.NORMAL: "Normally",
    GpSensitivity.LOW: "Barely",
}
SENSITIVITY_QUESTION = "How strongly should expensive upgrades be deprioritized?"
ACCOUNT_TYPE_QUESTION = "What kind of account is this?"
ACCOUNT_TYPE_UNSET = "Not set — nothing is assumed"
ACCOUNT_TYPE_LABELS: Mapping[AccountType, str] = {
    AccountType.MAIN: "Main",
    AccountType.IRONMAN: "Ironman",
    AccountType.HARDCORE: "Hardcore ironman",
    AccountType.ULTIMATE: "Ultimate ironman",
    AccountType.GROUP: "Group ironman",
}
ACCOUNT_TYPE_NOTE = "Recorded account type. Current factual Gear tools do not choose purchases."
MEMBERS_QUESTION = "Is this a members account?"
MEMBERS_UNSET = "Not set"


@dataclass(frozen=True, slots=True)
class SettingsView:
    gp_sensitivity: GpSensitivity
    tracked_username: str | None
    bind_address: str
    port: int
    api_token_present: bool
    price_provider: str
    price_base_url: str
    wom_base_url: str
    account_type: AccountType | None = None
    members: bool | None = None
    price_rows: int = 0
    price_last_fetched_at: datetime | None = None

    @property
    def price_cache_label(self) -> str:
        if self.price_last_fetched_at is None:
            return "never fetched"
        noun = "item" if self.price_rows == 1 else "items"
        return f"{self.price_rows} {noun} priced"

    @property
    def sensitivity_label(self) -> str:
        return GP_SENSITIVITY_LABELS[self.gp_sensitivity]
