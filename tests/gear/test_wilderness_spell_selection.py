"""Combined spell risk can require reselecting an attack for unchanged gear."""

import pytest

from tests.gear.test_optimizer import NOW
from tests.gear.test_wilderness_spell_search import magic_case
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig
from tracker.gear.service import GearService


@pytest.mark.parametrize(
    ("profile", "native"),
    [("baseline", False), ("combined", False), ("combined", True)],
    ids=["baseline", "compact", "native"],
)
@pytest.mark.parametrize("trip", [False, True], ids=["legacy", "fixed-trip"])
@pytest.mark.parametrize("fixed_second", [False, True], ids=["two-adjustable", "one-fixed"])
def test_shared_trip_reselects_one_spell_when_individual_winners_do_not_fit(
    make_content, profile, native, fixed_second, trip
):
    if native:
        pytest.importorskip("tracker.gear.native._stages")
    snapshot, catalog, prices = magic_case()
    magic = RoleConfig(
        id="first",
        style="magic",
        spell="water_wave",
        locks={"weapon": 30070},
        combat_options=CombatOptionFilters(
            attack_types=("magic",),
            stances=("accurate",),
            spells=("water_wave", "water_strike"),
        ),
    )
    second = magic.model_copy(
        update={"id": "second", "combat_options": None if fixed_second else magic.combat_options}
    )
    request = OptimizationRequest(
        roles=(magic, second),
        max_swaps=0,
        wilderness={
            "skulled": True,
            "protect_item": True,
            "max_loss_gp": 2800,
            ("attacks_per_setup" if trip else "spell_casts"): 10,
        },
    )
    service = GearService(
        make_content(),
        optimization_profile=profile,
        fixed_reporting=True,
        factored_evaluation=True,
        compact_states=True,
        native_search=native,
    )
    service._equipment = catalog

    result = service.optimize(snapshot, request, price_records=prices, now=NOW)
    solution = result["selected_solution"]

    assert {row["combat_option"]["spell"] for row in solution["loadouts"].values()} == {
        "water_strike",
        "water_wave",
    }
    if fixed_second:
        assert solution["loadouts"]["second"]["combat_option"]["spell"] == "water_wave"
    assert solution["maximum_actions"] == 0
    assert solution["wilderness_risk"]["loss_gp"] == 2800
    if native:
        assert service.native_diagnostics["native_requests"] > 0
        assert service.native_diagnostics["fallback_requests"] == 0
