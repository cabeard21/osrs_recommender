"""Armour-aware scoring survives optimizer and detached worker boundaries."""

from dataclasses import replace

from tests.gear.test_optimizer import run, weapon
from tests.gear.test_parallel_payload import inputs
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import RoleConfig
from tracker.gear.parallel_payload import context_payload, decode_context, decode_job, job_payload


def test_armour_changes_optimizer_weapon_ranking():
    items = [weapon(1, "slash", 10), weapon(2, "slash", attack_pattern="independent_double")]
    winners = []
    for armour in (0, -5):
        result = run(
            items,
            (RoleConfig(id="melee", style="slash", target=CombatTarget(flat_armour=armour)),),
            max_swaps=0,
        )
        winners.append(result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"])
    assert winners == [1, 2]


def test_flat_armour_and_attack_pattern_worker_round_trip():
    snapshot, request, catalog, content, prices, now = inputs()
    items = {
        key: value.model_copy(update={"attack_pattern": "conditional_double"})
        for key, value in catalog.items.items()
    }
    catalog = replace(catalog, items=items)
    request = request.model_copy(
        update={
            "roles": tuple(
                role.model_copy(update={"target": CombatTarget(flat_armour=-5)})
                for role in request.roles
            )
        }
    )
    payload, identity = context_payload(content, catalog)
    _, restored = decode_context(payload, identity)
    assert restored == catalog
    _, configured, _, _ = decode_job(
        job_payload(snapshot, request, prices, now, identity), identity
    )
    assert configured == request
