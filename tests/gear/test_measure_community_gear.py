"""Coverage measurement counts access and model support independently of search."""

from datetime import UTC, datetime
from types import SimpleNamespace

from tools.measure_community_gear import coverage_counts
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.content.requirements import SkillLeaf
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentDefinition


def test_counts_preserve_unknown_cost_and_unsupported_effects():
    now = datetime(2026, 10, 19, tzinfo=UTC)
    items = {
        i: EquipmentDefinition(
            id=i,
            name=str(i),
            slot="head",
            requirements_complete=i != 4,
            tradeable=True,
            unsupported_effects=("Known unsupported mechanic",) if i == 3 else (),
        )
        for i in (1, 2, 3, 4)
    }
    snapshot = AccountSnapshot(
        1,
        "fixture",
        observed_items={
            (1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "fixture", now),
            (3, Container.BANK): ObservedItemFact(3, Container.BANK, 1, "fixture", now),
        },
    )
    result = coverage_counts(snapshot, EquipmentCatalog(items), Content(), {}, now)
    assert result["supported_ids"] == [1, 2]
    assert result["owned_usable_ids"] == [1]
    assert result["priced_purchase_usable_ids"] == []
    assert result["missing_purchase_price_ids"] == [2]
    assert result["blocked_effect_ids"] == [3]
    assert result["unknown_gate_ids"] == [4]


def test_counts_separate_known_unmet_from_priced_available():
    now = datetime(2026, 10, 19, tzinfo=UTC)
    items = {
        1: EquipmentDefinition(
            id=1, name="Priced", slot="head", tradeable=True, requirements_complete=True
        ),
        2: EquipmentDefinition(
            id=2,
            name="Unmet",
            slot="head",
            requirements_complete=True,
            requires=SkillLeaf(skill="defence", level=70),
        ),
    }
    snapshot = AccountSnapshot(
        1, "fixture", skills={"defence": SkillState(20, None, Source.MANUAL, now)}
    )
    price = SimpleNamespace(
        item_id=1,
        high_price_gp=100,
        high_trade_at=now,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=now,
        source="live",
    )
    result = coverage_counts(snapshot, EquipmentCatalog(items), Content(), {1: price}, now)
    assert result["priced_purchase_usable_ids"] == [1]
    assert result["unmet_gate_ids"] == [2]
    assert result["unknown_gate_ids"] == []
