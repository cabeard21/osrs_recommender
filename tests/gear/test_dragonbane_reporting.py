"""Dragonbane reports remain optional and immutable public output metadata."""

import pytest
from pydantic import ValidationError

from tracker.gear.models import CombatPerformance, DragonbaneBonus


def test_dragonbane_report_serializes_intrinsic_and_additive_task_effect():
    report = DragonbaneBonus(
        item_id=21012, accuracy_percent=30, damage_percent=25, slayer_damage_additive=True
    )
    result = CombatPerformance(supported=True, dragonbane_bonus=report)
    assert result.model_dump(mode="json")["dragonbane_bonus"] == {
        "item_id": 21012,
        "accuracy_percent": 30,
        "damage_percent": 25,
        "slayer_damage_additive": True,
    }
    with pytest.raises(ValidationError):
        report.damage_percent = 40


def test_dragonbane_report_is_optional_and_task_addition_defaults_false():
    assert CombatPerformance(supported=True).dragonbane_bonus is None
    assert not DragonbaneBonus(
        item_id=22978, accuracy_percent=20, damage_percent=20
    ).slayer_damage_additive
