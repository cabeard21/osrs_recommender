"""Account resolution is an adapter seam, never a model-selected tool argument."""

from dataclasses import dataclass
from typing import Protocol

from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot


class SnapshotProvider(Protocol):
    def get_snapshot(self) -> AccountSnapshot: ...


@dataclass(frozen=True)
class ConfiguredAccount:
    accounts: AccountService
    player_id: int

    def get_snapshot(self) -> AccountSnapshot:
        return self.accounts.get_snapshot(self.player_id)
