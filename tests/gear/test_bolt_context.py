from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import UnlockState
from tracker.gear.evaluation import resolve_bolt_context
from tracker.gear.npcs import npc_catalog, resolve_target
from tracker.gear.optimizer import RoleConfig


@pytest.mark.parametrize("state", [None, *UnlockState])
def test_diary_context_only_uses_confirmed_unlock(state):
    snapshot = AccountSnapshot(
        player_id=1,
        username="test",
        unlocks={} if state is None else {"diary_kandarin_hard": state},
        last_sync_at=datetime(2026, 11, 12, tzinfo=UTC),
    )
    role = RoleConfig(id="ranged", style="ranged")
    resolved = resolve_bolt_context(role, snapshot)
    assert resolved.bolt_diary_boost is (state is UnlockState.UNLOCKED)
    assert role.bolt_diary_boost is False
    assert "bolt_diary_boost" not in resolved.model_dump()


def test_client_cannot_claim_diary_boost():
    with pytest.raises(ValueError, match="resolved internally"):
        RoleConfig(id="ranged", style="ranged", bolt_diary_boost=True)


def test_saved_npc_target_inherits_hp_and_preserves_current_override():
    catalog = npc_catalog()
    entry = catalog.detail(catalog.search("Dagannoth Rex")["items"][0]["key"])
    target = {
        k: v for k, v in entry["target"].items() if k not in {"hitpoints", "current_hitpoints"}
    }
    selection = {"key": entry["key"], "catalog_revision": catalog.revision}
    role = RoleConfig(id="ranged", style="ranged", target=target, target_selection=selection)
    resolved = resolve_target(role)
    assert resolved.target.hitpoints == entry["source_record"]["skills"]["hp"]
    override = role.model_copy(
        update={"target": role.target.model_copy(update={"current_hitpoints": 10})}
    )
    assert resolve_target(override).target.current_hitpoints == 10


def test_selected_npc_rejects_hp_above_canonical_base():
    catalog = npc_catalog()
    entry = catalog.detail(catalog.search("Dagannoth Rex")["items"][0]["key"])
    target = {**entry["target"], "current_hitpoints": entry["source_record"]["skills"]["hp"] + 1}
    with pytest.raises(ValueError, match="hitpoints"):
        resolve_target(
            RoleConfig(
                id="ranged",
                style="ranged",
                target=target,
                target_selection={"key": entry["key"], "catalog_revision": catalog.revision},
            )
        )


def test_search_retains_proc_forms_after_ordinary_ammo_truncation(monkeypatch):
    from tracker.gear.models import EquipmentDefinition
    from tracker.gear.optimizer import OptimizationRequest, _Search

    monkeypatch.setattr(_Search, "cost", lambda *args: 0)
    monkeypatch.setattr(_Search, "untradeable_acquisitions", lambda *args: 0)
    monkeypatch.setattr(_Search, "performance", lambda *args: {"supported": True, "dps": 1})
    items = {
        i: EquipmentDefinition(
            id=i, name=str(i), slot="ammunition", bolt_effect="opal" if i == 40 else None
        )
        for i in range(1, 41)
    }
    snapshot = AccountSnapshot(1, "test", unlocks={"diary_kandarin_hard": UnlockState.UNLOCKED})
    request = OptimizationRequest(roles=(RoleConfig(id="ranged", style="ranged"),))
    search = _Search(snapshot, request, items, {}, None, prepared_eligible=items)
    assert 40 in search.pools["ammunition"]
    assert set(range(1, 24)) <= set(search.pools["ammunition"])
    assert search.request.roles[0].bolt_diary_boost


def low_tier_context():
    """Real reviewed forms, restricted to an owned level-46 progression case."""
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import load_content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.catalog import EquipmentCatalog, load_catalog
    from tracker.gear.models import CombatTarget
    from tracker.gear.optimizer import OptimizationRequest

    now = datetime(2026, 11, 12, tzinfo=UTC)
    content = load_content()
    full = load_catalog(content)
    ids = (9177, 9183, 9236, 9242)
    catalog = EquipmentCatalog({i: full.items[i] for i in ids}, revision=full.revision)
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(level, None, Source.MANUAL, now)
            for key, level in (
                ("attack", 46),
                ("strength", 46),
                ("defence", 46),
                ("ranged", 46),
                ("magic", 46),
                ("hitpoints", 46),
            )
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "test", now) for i in ids
        },
        unlocks={"diary_kandarin_hard": UnlockState.UNLOCKED},
    )
    request = OptimizationRequest(
        mode="owned",
        max_swaps=0,
        roles=(
            RoleConfig(
                id="ranged",
                style="ranged",
                stance="rapid",
                target=CombatTarget(hitpoints=1000, current_hitpoints=500),
            ),
        ),
    )
    return snapshot, request, catalog, content, {}, now


def test_owned_adamant_crossbow_and_ruby_win_without_rune_crossbow():
    from tracker.gear.optimizer import optimize

    result = optimize(*low_tier_context())
    loadout = result["selected_solution"]["loadouts"]["ranged"]
    assert loadout["equipment"]["weapon"] == 9183
    assert loadout["equipment"]["ammunition"] == 9242
    assert result["selected_solution"]["purchase_cost_gp"] == 0
    assert loadout["performance"]["bolt_effect"]["diary_boosted"] is True
    assert loadout["performance"]["bolt_effect"]["target_hitpoints"] == 500


def test_spawned_worker_retains_target_hp_and_diary_and_matches_serial():
    from tracker.gear.optimizer import optimize
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.potions import PotionPolicy

    snapshot, request, catalog, content, prices, now = low_tier_context()
    branch = request.model_copy(update={"potions": PotionPolicy(mode="fixed")})
    expected = optimize(snapshot, branch, catalog, content, prices, now, _complete_frontiers=True)
    pool = AutoProcessPool(1)
    try:
        pool.start(content, catalog)
        actual = pool.run_potions(
            snapshot, request, catalog, content, prices, now, branches=[branch]
        )
    finally:
        pool.close()
    assert actual[0]["selected_solution"] == expected["selected_solution"]
    assert actual[0]["assumptions"] == expected["assumptions"]
