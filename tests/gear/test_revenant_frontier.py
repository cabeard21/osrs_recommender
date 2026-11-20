"""Compare the complete Python and desktop-native frontiers for an owned empty mace."""

from dataclasses import replace

from tests.gear.test_optimizer import NOW
from tests.gear.test_wilderness_optimization import scenario
from tools.benchmark_gear_desktop import result_digest
from tracker.content.loader import load_content
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.objective_store import close_result_archives
from tracker.gear.optimizer import OptimizationRequest
from tracker.gear.service import GearService


def test_owned_mace_auto_retains_both_physical_forms_at_their_real_cost():
    content = load_content()
    catalog = load_catalog(content)
    base, charged = 22542, 22545
    snapshot, _, prices = scenario(owned=(base,))
    snapshot = replace(snapshot, skills={**snapshot.skills, "ranged": snapshot.skills["attack"]})
    prices = {
        i: replace(prices[4587], item_id=i, high_price_gp=gp)
        for i, gp in ((base, 3_000_000), (21820, 10))
    }
    request = OptimizationRequest.model_validate(
        {
            "roles": [
                {
                    "id": "wild",
                    "style": "crush",
                    "allowed_disciplines": ["melee", "ranged"],
                    "combat_options": {
                        "attack_types": ["crush", "standard"],
                        "stances": ["accurate", "rapid"],
                        "spells": [],
                    },
                }
            ],
            "mode": "owned",
            "max_swaps": 0,
            "max_dps_loss_pct": 100,
            "objectives": [{"kind": "gp_per_damage"}, {"kind": "wilderness_loss_gp"}],
            "wilderness": {"attacks_per_setup": 25},
        }
    )
    digests = []
    for native in (False, True):
        service = GearService(
            content,
            optimization_profile="combined",
            fixed_reporting=True,
            factored_evaluation=True,
            compact_states=True,
            native_search=native,
        )
        service._equipment = EquipmentCatalog(
            {i: catalog.items[i] for i in (base, charged)}, revision=catalog.revision
        )
        result = service.optimize(snapshot, request, price_records=prices, now=NOW)
        try:
            groups = [{**g, "points": list(g["points"])} for g in result["objective_frontiers"]]
            group = next(g for g in groups if g["swap_limit"] is None)
            solutions = [p["solution"] for p in group["points"]]
            by_weapon = {s["loadouts"]["wild"]["equipment"].get("weapon"): s for s in solutions}
            assert {base, charged} <= by_weapon.keys()
            assert by_weapon[base]["score"] < by_weapon[charged]["score"]
            assert by_weapon[base]["objective_values"]["gp_per_damage"] == 0
            assert by_weapon[charged]["objective_values"]["gp_per_damage"] > 0
            assert by_weapon[charged]["objective_values"]["wilderness_loss_gp"] == 10_250
            assert by_weapon[charged]["purchase_cost_gp"] == 0
            digests.append(result_digest({**result, "objective_frontiers": groups}))
        finally:
            close_result_archives(result)
        if native:
            assert service.native_diagnostics["native_requests"] > 0
            assert service.native_diagnostics["fallback_requests"] == 0, service.native_diagnostics
    assert digests[0] == digests[1]
