from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import UnlockState
from tracker.gear.combat import evaluate_loadout
from tracker.gear.defensive_rolls import player_defence_rolls
from tracker.gear.models import EquipmentBonuses
from tracker.gear.prayers import PrayerPolicy, catalog, effects, setups


def test_policy_rejects_conflicts_and_unknown_ids():
    for ids in [("piety", "steel_skin"), ("eagle_eye", "mystic_might"), ("missing",)]:
        with pytest.raises(ValueError):
            PrayerPolicy(mode="fixed", selected_ids=ids)
    with pytest.raises(ValueError):
        PrayerPolicy(mode="disabled", selected_ids=("piety",))


def test_unlocks_unknown_and_locked_are_excluded():
    policy = PrayerPolicy(mode="optimize", allowed_ids=("rigour", "eagle_eye"))
    levels = {"prayer": 99, "defence": 99}
    account = AccountSnapshot(1, "fixture")
    assert setups(policy, account, levels) == ((), ("eagle_eye",))
    with pytest.raises(ValueError, match="rigour"):
        setups(PrayerPolicy(mode="fixed", selected_ids=("rigour",)), account, levels)
    unlocked = AccountSnapshot(1, "fixture", unlocks={"rigour": UnlockState.UNLOCKED})
    assert ("rigour",) in setups(policy, unlocked, levels)


def test_legal_combinations_and_additive_defence():
    policy = PrayerPolicy(mode="fixed", selected_ids=("deadeye", "steel_skin"))
    account = AccountSnapshot(1, "fixture", unlocks={"deadeye": UnlockState.UNLOCKED})
    assert setups(policy, account, {"prayer": 99}) == (("deadeye", "steel_skin"),)
    assert effects(policy.selected_ids).defence == 120


def test_prayer_rounding_and_magic_damage():
    role = SimpleNamespace(
        style="magic", stance="accurate", spell="fire_bolt", active_prayer_ids=("augury",)
    )
    result = evaluate_loadout([], role, {"magic": 59, "defence": 51})
    assert result.attack_roll == (59 * 125 // 100 + 11) * 64
    assert result.max_hit == 12  # floor(12 * 1.04)
    assert result.player_defence_rolls.stab == (51 * 125 // 100 + 8) * 64


def test_magic_defence_floors_each_stage():
    result = player_defence_rolls(
        {"magic": 59, "defence": 51}, EquipmentBonuses(), "controlled", effects(("augury",))
    )
    assert result.magic == ((59 * 125 // 100) * 7 // 10 + (51 * 125 // 100) * 3 // 10 + 9) * 64


def test_catalog_contains_reviewed_stat_prayers():
    rows = catalog()
    assert len(rows) == 22
    assert {r["id"] for r in rows} >= {"zeal", "deadeye", "mystic_vigour"}


def test_zeal_requires_knight_waves_and_defence_and_replaces_piety():
    policy = PrayerPolicy(mode="fixed", selected_ids=("zeal",))
    levels = {"prayer": 84, "attack": 75, "strength": 75, "defence": 70}
    account = AccountSnapshot(1, "fixture", unlocks={"zeal": UnlockState.UNLOCKED})
    with pytest.raises(ValueError, match="knight_waves"):
        setups(policy, account, levels)
    account = AccountSnapshot(
        1, "fixture", unlocks={"zeal": UnlockState.UNLOCKED, "knight_waves": UnlockState.UNLOCKED}
    )
    assert setups(policy, account, levels) == (("zeal",),)
    with pytest.raises(ValueError, match="Defence"):
        setups(policy, account, {**levels, "defence": 69})
    with pytest.raises(ValueError, match="Replaced"):
        setups(PrayerPolicy(mode="fixed", selected_ids=("piety",)), account, levels)


def test_prayer_policy_and_missing_level_edges():
    with pytest.raises(ValueError):
        PrayerPolicy(mode="fixed", allowed_ids=("piety",))
    with pytest.raises(ValueError):
        effects(("unknown",))
    assert setups(PrayerPolicy(), AccountSnapshot(1, "fixture"), {}) == ((),)
    rows = catalog(AccountSnapshot(1, "fixture"), {"prayer": 1})
    assert next(row for row in rows if row["id"] == "rigour")["availability"] == "unsatisfied"
    assert "steel_skin" in next(row for row in rows if row["id"] == "rigour")["conflicts"]


def test_melee_prayer_rounds_before_stance():
    role = SimpleNamespace(style="crush", stance="aggressive", active_prayer_ids=("piety",))
    result = evaluate_loadout([], role, {"attack": 59, "strength": 51})
    assert result.attack_roll == (59 * 120 // 100 + 8) * 64
    assert result.max_hit == int(0.5 + (51 * 123 // 100 + 11) * 64 / 640)
