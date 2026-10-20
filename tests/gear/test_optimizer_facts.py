from datetime import UTC, datetime, timedelta

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.domain.types import Container
from tracker.gear.facts import observed_ownership

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def test_absence_is_unknown_without_all_scans():
    assert observed_ownership(AccountSnapshot(1, "test"), 1)["status"] == "unknown"


def test_superseded_sightings_and_quantities_not_summed():
    facts = {(1, c): ObservedItemFact(1, c, 2, "test", NOW) for c in Container}
    snapshot = AccountSnapshot(1, "test", observed_items=facts)
    assert observed_ownership(snapshot, 1)["quantity"] == 2
    scans = {c: ContainerScanFact(c, NOW + timedelta(seconds=1), "test") for c in Container}
    result = observed_ownership(
        AccountSnapshot(1, "test", observed_items=facts, container_scans=scans), 1
    )
    assert result["status"] == "unowned"
    assert "not observed" in result["meaning"]


def test_dragon_scimitar_quest_and_level_gates_and_whatif_copy(make_content):
    from tracker.content.requirements import AllOf, QuestLeaf, SkillLeaf
    from tracker.domain.types import QuestStatus, SkillState, Source
    from tracker.gear.facts import equipment_fact, hypothetical_snapshot
    from tracker.gear.models import EquipmentDefinition

    item = EquipmentDefinition(
        id=4587,
        name="Dragon scimitar",
        slot="weapon",
        requirements_complete=True,
        requires=AllOf(
            children=(SkillLeaf(skill="attack", level=60), QuestLeaf(quest_id="monkey_madness_i"))
        ),
    )
    content = make_content(quests={"monkey_madness_i": "Monkey Madness I"})
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"attack": SkillState(59, None, Source.MANUAL, NOW)},
        quests={"monkey_madness_i": QuestStatus.COMPLETE},
    )
    assert equipment_fact(snapshot, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"
    projected = hypothetical_snapshot(snapshot, {"attack": 60}, {}, NOW)
    assert equipment_fact(projected, item, content, {}, NOW)["wear"]["status"] == "satisfied"
    assert snapshot.skills["attack"].level == 59
    missing_quest = hypothetical_snapshot(projected, {}, {"monkey_madness_i": "not_started"}, NOW)
    assert equipment_fact(missing_quest, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"


def test_missing_requirements_metadata_never_means_unrestricted(make_content):
    from tracker.gear.facts import equipment_fact
    from tracker.gear.models import EquipmentDefinition

    item = EquipmentDefinition(id=1, name="Unknown gates", slot="head")
    fact = equipment_fact(AccountSnapshot(1, "test"), item, make_content(), {}, NOW)
    assert fact["wear"]["status"] == "unknown"
