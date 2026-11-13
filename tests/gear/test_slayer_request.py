"""Slayer task context is explicit, strict and local to each configuration."""

import pytest
from pydantic import ValidationError

from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def test_task_context_defaults_off_and_round_trips_per_role():
    off = RoleConfig(id="off", style="slash")
    on = RoleConfig(id="on", style="magic", on_slayer_task=True)
    request = OptimizationRequest(roles=(off, on))
    decoded = OptimizationRequest.model_validate_json(request.model_dump_json())
    assert not decoded.roles[0].on_slayer_task
    assert decoded.roles[1].on_slayer_task
    assert decoded.prepared_weapon_locks().roles[1].on_slayer_task
    assert on.model_dump()["on_slayer_task"] is True


@pytest.mark.parametrize("value", [1, 0, "true", "false", None])
def test_task_context_requires_boolean(value):
    with pytest.raises(ValidationError):
        RoleConfig(id="role", style="slash", on_slayer_task=value)


def test_task_effect_candidates_survive_small_slot_cap(monkeypatch):
    from dataclasses import replace

    from tests.gear.test_scoring_options import context
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container
    from tracker.gear import optimizer
    from tracker.gear.facts import equipment_fact
    from tracker.gear.models import EquipmentBonuses, EquipmentDefinition

    role = RoleConfig(id="melee", style="slash", on_slayer_task=True)
    snapshot, items, _, request = context(role)
    # A small cap forces the deliberately weak raw-stat mask below ordinary heads.
    mask = EquipmentDefinition(
        id=100,
        name="Task mask fixture",
        slot="head",
        slayer_bonus="melee",
        requirements_complete=True,
    )
    heads = {
        i: EquipmentDefinition(
            id=i,
            name=f"Head {i}",
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(slash=i),
        )
        for i in range(101, 110)
    }
    items = {**items, mask.id: mask, **heads}
    snapshot = replace(
        snapshot,
        observed_items={
            (i, Container.BANK): ObservedItemFact(
                i, Container.BANK, 1, "fixture", next(iter(snapshot.skills.values())).observed_at
            )
            for i in items
        },
    )
    from tests.gear.test_optimizer import NOW

    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    pools = optimizer._Search(snapshot, request, items, facts, None).candidate_pools()
    assert mask.id in pools["head"]
