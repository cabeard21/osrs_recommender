from datetime import UTC, datetime
from types import SimpleNamespace

from tracker.accounts.snapshot import AccountSnapshot
from tracker.api.gear_ui import combat_option_capabilities
from tracker.domain.types import SkillState, Source
from tracker.gear.models import EquipmentDefinition


def test_missing_account_does_not_offer_unconfirmed_combat_options():
    gear = SimpleNamespace(equipment_catalog=lambda: SimpleNamespace(items={}))
    result = combat_option_capabilities(None, gear)
    assert not any(row["available"] for row in result["attack_types"])
    assert not any(row["available"] for row in result["spells"])
    assert {row["id"] for row in result["attack_types"]} == {
        "stab",
        "slash",
        "crush",
        "light",
        "standard",
        "heavy",
        "magic",
    }


def test_powered_filter_is_exposed_only_with_complete_metadata():
    gear = SimpleNamespace(
        equipment_catalog=lambda: SimpleNamespace(
            items={
                1: EquipmentDefinition(
                    id=1, name="Unknown staff", slot="weapon", powered_attack="unknown"
                ),
                2: EquipmentDefinition(
                    id=2,
                    name="Reviewed staff",
                    slot="weapon",
                    powered_attack="reviewed",
                    powered_attack_base_max_hit=10,
                    powered_attack_stances=("accurate", "longrange"),
                ),
            }
        )
    )
    result = combat_option_capabilities(None, gear)
    ids = {row["id"] for row in result["spells"]}
    assert "powered:2" in ids
    assert "powered:1" not in ids


def test_synced_magic_level_offers_standard_spells_without_unlock_row():
    account = AccountSnapshot(
        1,
        "mage",
        skills={"magic": SkillState(13, None, Source.RUNELITE, datetime(2026, 10, 28, tzinfo=UTC))},
    )
    gear = SimpleNamespace(equipment_catalog=lambda: SimpleNamespace(items={}))
    result = combat_option_capabilities(account, gear)
    available = {row["id"] for row in result["spells"] if row["available"]}
    assert {"wind_strike", "fire_strike"} <= available
