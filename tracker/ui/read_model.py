"""Database reads and settings writes for the factual dashboard."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.db.models import ItemPrice, Player
from tracker.db.repository import (
    current_skill_snapshots,
    get_container_scans,
    get_player,
    get_player_by_username,
    get_unlocks,
)
from tracker.domain.skills import canonical_skill_name
from tracker.domain.types import AccountType, Container, GpSensitivity
from tracker.ui.staleness import humanize_age, scan_note
from tracker.ui.view_model import (
    DashboardView,
    SettingsView,
    SkillRow,
    UnlockRow,
    skill_row,
    unlock_row,
)


def first_player_id(session: Session) -> int | None:
    return session.scalar(select(Player.id).order_by(Player.id).limit(1))


def unlock_rows(session: Session, player_id: int, content: Content) -> tuple[UnlockRow, ...]:
    """Show observed unlock facts; deleted capability content is not an authority."""
    del content
    return tuple(
        unlock_row(row.key, row.state)
        for row in sorted(get_unlocks(session, player_id), key=lambda row: row.key)
    )


def skill_rows(session: Session, player_id: int, content: Content) -> tuple[SkillRow, ...]:
    rows = []
    for snapshot in current_skill_snapshots(session, player_id):
        key = canonical_skill_name(snapshot.skill)
        definition = content.skills.get(key)
        rows.append(
            skill_row(
                skill_id=key,
                name=definition.name if definition else key.replace("_", " ").title(),
                is_combat=definition.is_combat if definition else False,
                level=snapshot.level,
                xp=snapshot.xp,
            )
        )
    return tuple(sorted(rows, key=lambda row: (not row.is_ranked, -(row.level or 0), row.name)))


def dashboard_view(
    session: Session,
    player_id: int,
    now: datetime,
    *,
    quest_cape_completed: int,
    quest_cape_total: int,
    quest_cape_unknown: int,
    quest_cape_available: int,
) -> DashboardView:
    player = get_player(session, player_id)
    scans = {row.container: row.scanned_at for row in get_container_scans(session, player_id)}
    last_sync = (
        f"synced {humanize_age(player.last_sync_at, now)}"
        if player is not None and player.last_sync_at is not None
        else "never synced — start RuneLite with the companion plugin"
    )
    return DashboardView(
        display_name=player.display_name if player is not None else "unknown account",
        combat_level=player.combat_level if player is not None else None,
        quest_points=player.quest_points if player is not None else None,
        last_sync_at_label=last_sync,
        staleness_notes=tuple(
            scan_note(container, scans.get(container), now) for container in Container
        ),
        quest_cape_completed=quest_cape_completed,
        quest_cape_total=quest_cape_total,
        quest_cape_unknown=quest_cape_unknown,
        quest_cape_available=quest_cape_available,
    )


def settings_view(session: Session, player_id: int | None, settings: Settings) -> SettingsView:
    player = get_player(session, player_id) if player_id is not None else None
    prices = settings.integrations.prices
    return SettingsView(
        gp_sensitivity=player.gp_sensitivity if player is not None else GpSensitivity.NORMAL,
        tracked_username=player.username if player is not None else None,
        bind_address=settings.bind_address,
        port=settings.port,
        api_token_present=bool(settings.api_token),
        price_provider=prices.provider,
        price_base_url=prices.base_url,
        wom_base_url=settings.integrations.wise_old_man.base_url,
        account_type=(
            AccountType(player.account_type) if player is not None and player.account_type else None
        ),
        members=player.members if player is not None else None,
        price_rows=session.scalar(select(func.count()).select_from(ItemPrice)) or 0,
        price_last_fetched_at=session.scalar(select(func.max(ItemPrice.fetched_at))),
    )


def set_account_type(
    session: Session, player_id: int | None, account_type: AccountType | None
) -> None:
    player = get_player(session, player_id) if player_id is not None else None
    if player is not None:
        player.account_type = account_type.value if account_type is not None else None
        session.commit()


def set_members(session: Session, player_id: int | None, members: bool | None) -> None:
    player = get_player(session, player_id) if player_id is not None else None
    if player is not None:
        player.members = members
        session.commit()


def set_tracked_username(session: Session, player_id: int | None, username: str) -> int:
    cleaned = username.strip()
    if not cleaned:
        raise ValueError("username must not be blank")
    player = get_player(session, player_id) if player_id is not None else None
    if player is None:
        existing = get_player_by_username(session, cleaned)
        if existing is not None:
            return existing.id
        player = Player(username=cleaned, display_name=cleaned, created_at=datetime.now(UTC))
        session.add(player)
        session.flush()
        return player.id
    player.username = cleaned
    player.display_name = cleaned
    return player.id


def set_gp_sensitivity(session: Session, player_id: int, sensitivity: GpSensitivity) -> None:
    player = get_player(session, player_id)
    if player is not None:
        player.gp_sensitivity = sensitivity
        session.commit()
