import pytest

from tests.gear.test_running_costs import NOW
from tracker.gear.catalog import load_catalog
from tracker.gear.models import EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost


@pytest.mark.parametrize(
    "item_id,pattern",
    [
        (28997, "conditional_double"),
        (29889, "independent_double"),
        (29084, "independent_double"),
        (4747, "independent_double"),
        (4958, "independent_double"),
        (4961, "independent_double"),
    ],
)
def test_reviewed_double_hit_forms(make_content, item_id, pattern):
    item = load_catalog(make_content()).items[item_id]
    assert item.attack_pattern == pattern
    assert not item.unsupported_effects
    assert item.requires is not None
    assert item.requirements_complete
    assert item.attack_styles


def test_dual_profiles_and_broken_torag_excluded(make_content):
    items = load_catalog(make_content()).items
    assert items[28997].attack_profiles == (
        ("crush", "accurate"),
        ("crush", "aggressive"),
        ("stab", "controlled"),
        ("crush", "defensive"),
    )
    assert items[4962].unsupported_effects
    assert items[4962].attack_pattern == "single"


@pytest.mark.parametrize("item_id", [4747, 4958, 4959, 4960, 4961])
def test_torag_degradation_is_unavailable(item_id):
    item = EquipmentDefinition(id=item_id, name="Torag's hammers", slot="weapon")
    result = evaluate_running_cost(
        {"weapon": item}, {"attack_type": "crush"}, {"attack_interval": 3, "dps": 5}, {}, NOW
    )
    assert result["status"] == "unavailable"
    assert result["gp_per_hour"] is None
    assert "degradation" in result["reasons"][0]
