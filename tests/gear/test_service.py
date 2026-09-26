"""Factual Account Companion gear views, independent of legacy ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tracker.accounts.service import AccountService
from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import load_content
from tracker.content.schema import Item
from tracker.db.models import Base, ContainerScan, ObservedItem, Player
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.service import GearService

SEEN = datetime(2026, 9, 20, tzinfo=UTC)


def _snapshot(*, sightings=(), scans=()) -> AccountSnapshot:
    return AccountSnapshot(
        player_id=1,
        username="gear tester",
        observed_items={(fact.item_id, fact.container): fact for fact in sightings},
        container_scans={fact.container: fact for fact in scans},
    )


def _scan(container: Container, at: datetime = SEEN) -> ContainerScanFact:
    return ContainerScanFact(container=container, scanned_at=at, source="runelite")


def _seen(item_id: int, container: Container, at: datetime = SEEN) -> ObservedItemFact:
    return ObservedItemFact(
        item_id=item_id, container=container, quantity=1, source="runelite", observed_at=at
    )


def test_progression_and_candidates_are_authored_facts(make_item, make_content) -> None:
    items = [
        make_item("rune", numeric_id=1, tier=2),
        make_item("bronze", numeric_id=2, tier=1),
        make_item("magic", numeric_id=3, style="magic", tier=1),
    ]
    service = GearService(make_content(items=items))
    snapshot = _snapshot(scans=[_scan(container) for container in Container])

    progression = service.progression(snapshot, style="melee", limit=1)
    assert [item["content_id"] for item in progression["items"]] == ["bronze"]
    assert progression["total"] == 2
    assert progression["next_offset"] == 1
    assert progression["container_scans"]["bank"]["scanned_at"] == SEEN.isoformat()
    empty_page = service.progression(snapshot, style="melee", offset=99)
    assert empty_page["items"] == []
    assert empty_page["container_scans"] == progression["container_scans"]
    assert "recommended" not in progression
    candidates = service.candidates(snapshot, style="melee", ownership="unowned")
    assert [item["content_id"] for item in candidates["items"]] == ["bronze", "rune"]


def test_ownership_is_dated_and_variant_aware(make_item, make_content) -> None:
    item = make_item("charged", numeric_id=10, variant_item_ids=(11,))
    service = GearService(make_content(items=[item]))
    scans = [_scan(Container.BANK, SEEN), _scan(Container.INVENTORY, SEEN + timedelta(days=1))]
    unknown = service.item_details(_snapshot(scans=scans), content_id="charged")
    assert unknown["items"][0]["ownership"]["status"] == "unknown"
    assert (
        unknown["items"][0]["ownership"]["container_scans"]["bank"]["scanned_at"]
        == SEEN.isoformat()
    )
    assert unknown["items"][0]["ownership"]["container_scans"]["equipment"] is None

    unowned = service.item_details(
        _snapshot(scans=[*scans, _scan(Container.EQUIPMENT, SEEN + timedelta(days=2))]),
        content_id="charged",
    )
    assert unowned["items"][0]["ownership"]["status"] == "unowned"
    assert "latest accepted scans" in unowned["items"][0]["ownership"]["meaning"]

    owned = service.item_details(
        _snapshot(sightings=[_seen(11, Container.EQUIPMENT)], scans=scans),
        content_id="charged",
    )
    assert owned["items"][0]["ownership"]["status"] == "owned"
    assert owned["items"][0]["ownership"]["observed_containers"] == ["equipment"]


def test_hypothetical_validates_catalog_facts_only(make_item, make_content) -> None:
    service = GearService(
        make_content(
            items=[
                make_item("bow", numeric_id=20, style="ranged", tier=1),
                make_item("bow_alias", numeric_id=20, style="ranged", slot="shield", tier=1),
            ]
        )
    )
    snapshot = _snapshot()
    result = service.evaluate_change(
        snapshot, style="ranged", changes=[{"slot": "weapon", "content_id": "bow"}]
    )
    assert result["joint_loadout_validity"] == "not_evaluated"
    assert result["purchase_subtotal_gp"] is None
    assert "unknown_ownership" in result["subtotal_unknown_reasons"]
    assert result["items"][0]["purchase_status"] == "unknown"
    assert "two-handed" in " ".join(result["limitations"])

    with pytest.raises(ValueError, match="duplicate physical item"):
        service.evaluate_change(
            snapshot,
            style="ranged",
            changes=[
                {"slot": "weapon", "content_id": "bow"},
                {"slot": "shield", "content_id": "bow_alias"},
            ],
        )
    with pytest.raises(ValueError, match="snapshot_changed"):
        service.evaluate_change(
            snapshot,
            style="ranged",
            changes=[{"slot": "weapon", "content_id": "bow"}],
            expected_snapshot_id="stale",
        )


def test_purchase_subtotal_requires_known_ownership_and_price(make_item, make_content) -> None:
    item = make_item("buy", numeric_id=30)
    service = GearService(make_content(items=[item]))
    snapshot = _snapshot(scans=[_scan(container) for container in Container])
    record = SimpleNamespace(
        item_id=30,
        high_price_gp=150,
        high_trade_at=SEEN,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=SEEN,
        source="live",
    )
    result = service.evaluate_change(
        snapshot,
        style="melee",
        changes=[{"slot": "weapon", "content_id": "buy"}],
        price_records={30: record},
        now=SEEN,
    )
    assert result["purchase_subtotal_gp"] == 150
    assert result["items"][0]["purchase_status"] == "necessary"
    assert result["items"][0]["price"]["selected_trade_at"] == SEEN.isoformat()
    assert result["items"][0]["price"]["fetched_at"] == SEEN.isoformat()

    owned = service.evaluate_change(
        _snapshot(sightings=[_seen(30, Container.BANK)], scans=[_scan(Container.BANK)]),
        style="melee",
        changes=[{"slot": "weapon", "content_id": "buy"}],
    )
    assert owned["purchase_subtotal_gp"] == 0
    assert owned["items"][0]["purchase_status"] == "unnecessary"


def test_numeric_identity_returns_all_memberships(make_item, make_content) -> None:
    service = GearService(
        make_content(
            items=[
                make_item("melee", numeric_id=40, style="melee"),
                make_item("magic", numeric_id=40, style="magic"),
            ]
        )
    )
    result = service.item_details(_snapshot(), numeric_item_id=40)
    assert [item["content_id"] for item in result["items"]] == ["magic", "melee"]
    assert result["ambiguous"] is True


def test_item_details_marks_content_outside_curated_gear(make_content) -> None:
    service = GearService(
        make_content(items=[Item(id="quest_token", name="Quest token", item_id=999)])
    )

    fact = service.item_details(_snapshot(), content_id="quest_token")["items"][0]
    assert fact["curated_progression_member"] is False
    assert fact["style"] is None


def test_superseded_sighting_does_not_establish_ownership(make_item, make_content) -> None:
    service = GearService(make_content(items=[make_item("old", numeric_id=50)]))
    snapshot = _snapshot(
        sightings=[_seen(50, Container.BANK, SEEN)],
        scans=[_scan(container, SEEN + timedelta(days=1)) for container in Container],
    )
    result = service.item_details(snapshot, content_id="old")
    assert result["items"][0]["ownership"]["status"] == "unowned"
    assert result["items"][0]["ownership"]["sightings"] == []


def test_unknown_gate_and_untradeable_cost(make_item, make_content) -> None:
    service = GearService(
        make_content(
            items=[
                make_item(
                    "earned",
                    numeric_id=60,
                    gate_unknown=True,
                    acquisition="untradeable",
                    acquired_from="the Fight Caves",
                )
            ]
        )
    )
    snapshot = _snapshot(scans=[_scan(container) for container in Container])
    fact = service.candidates(snapshot, style="melee", wear_status="unknown")["items"][0]
    assert fact["wear"] == {
        "status": "unknown",
        "gate_unknown": True,
        "requirements": None,
        "unmet": [],
    }
    assert fact["price"]["amount_gp"] is None
    result = service.evaluate_change(
        snapshot, style="melee", changes=[{"slot": "weapon", "content_id": "earned"}]
    )
    assert result["purchase_subtotal_gp"] is None
    assert result["subtotal_unknown_reasons"] == ["unowned_untradeable"]
    assert result["items"][0]["purchase_status"] == "not_applicable"


def test_proposal_rejects_only_authored_conflicts(make_item, make_content) -> None:
    service = GearService(
        make_content(
            items=[
                make_item("weapon", numeric_id=70, tier=1),
                make_item("shield", numeric_id=71, slot="shield", tier=1),
            ]
        )
    )
    snapshot = _snapshot()
    result = service.evaluate_change(
        snapshot,
        style="melee",
        changes=[
            {"slot": "weapon", "content_id": "weapon"},
            {"slot": "shield", "content_id": "shield"},
        ],
    )
    assert result["joint_loadout_validity"] == "not_evaluated"
    with pytest.raises(ValueError, match="duplicate slot"):
        service.evaluate_change(
            snapshot,
            style="melee",
            changes=[
                {"slot": "weapon", "content_id": "weapon"},
                {"slot": "weapon", "content_id": "weapon"},
            ],
        )
    with pytest.raises(ValueError, match="not an authored"):
        service.evaluate_change(
            snapshot,
            style="melee",
            changes=[
                {"slot": "shield", "content_id": "weapon"},
            ],
        )
    with pytest.raises(ValueError, match="changes must contain"):
        service.evaluate_change(snapshot, style="melee", changes="weapon")  # type: ignore[arg-type]


def test_wear_requirements_and_ranged_ladder(make_item, make_content) -> None:
    item = make_item(
        "ranged_bow",
        numeric_id=80,
        style="ranged",
        requires={"skill": {"ranged": 70}},
    )
    service = GearService(make_content(items=[item]))
    snapshot = AccountSnapshot(
        player_id=1,
        username="gear tester",
        skills={"ranged": SkillState(level=60, xp=None, source=Source.RUNELITE, observed_at=SEEN)},
    )
    result = service.progression(snapshot, style="ranged")
    assert result["items"][0]["wear"]["status"] == "unsatisfied"
    assert result["items"][0]["wear"]["unmet"][0]["key"] == "ranged"
    assert result["items"][0]["wear"]["requirements"]["kind"] == "skill"

    qualified = AccountSnapshot(
        player_id=1,
        username="gear tester",
        skills={"ranged": SkillState(level=80, xp=None, source=Source.RUNELITE, observed_at=SEEN)},
    )
    satisfied = service.item_details(qualified, content_id="ranged_bow")["items"][0]["wear"]
    assert satisfied["status"] == "satisfied"
    assert satisfied["unmet"] == []
    assert satisfied["requirements"]["required"] == 70


def test_avas_accumulator_uses_authored_ranged_gate_independent_of_ownership() -> None:
    service = GearService(load_content())
    scans = [_scan(container) for container in Container]

    def account(ranged_level: int) -> AccountSnapshot:
        return AccountSnapshot(
            player_id=1,
            username="Rehvun fixture",
            skills={
                "ranged": SkillState(
                    level=ranged_level, xp=None, source=Source.RUNELITE, observed_at=SEEN
                )
            },
            quests={"animal_magnetism": QuestStatus.COMPLETE},
            observed_items={(10498, Container.BANK): _seen(10498, Container.BANK)},
            container_scans={scan.container: scan for scan in scans},
        )

    below = account(38)
    fact = service.item_details(below, content_id="avas_accumulator")["items"][0]
    assert fact["ownership"]["status"] == "unowned"
    assert fact["wear"]["status"] == "unsatisfied"
    assert fact["wear"]["gate_unknown"] is False
    assert fact["wear"]["requirements"]["kind"] == "skill"
    assert fact["wear"]["requirements"]["key"] == "ranged"
    assert fact["wear"]["requirements"]["status"] == "unsatisfied"
    assert fact["wear"]["requirements"]["current"] == 38
    assert fact["wear"]["requirements"]["required"] == 50
    assert fact["wear"]["requirements"]["reason"] == "ranged: 38 / 50"
    assert fact["wear"]["unmet"][0]["key"] == "ranged"

    satisfied = service.candidates(
        below, style="ranged", ownership="unowned", wear_status="satisfied"
    )
    unsatisfied = service.candidates(
        below, style="ranged", ownership="unowned", wear_status="unsatisfied"
    )
    assert "avas_accumulator" not in {item["content_id"] for item in satisfied["items"]}
    assert "avas_accumulator" in {item["content_id"] for item in unsatisfied["items"]}

    proposal = service.evaluate_change(
        below, style="ranged", changes=[{"slot": "cape", "content_id": "avas_accumulator"}]
    )["items"][0]
    assert proposal["wear"]["status"] == "unsatisfied"
    assert proposal["wear"]["unmet"][0]["required"] == 50

    qualified = service.item_details(account(50), content_id="avas_accumulator")["items"][0]
    assert qualified["wear"]["status"] == "satisfied"
    assert qualified["wear"]["unmet"] == []
    assert qualified["ownership"]["status"] == "unowned"


@pytest.mark.parametrize(
    ("content_id", "skill", "required"),
    [("avas_attractor", "ranged", 30), ("saradomin_cape", "magic", 60)],
)
def test_other_authored_capes_have_use_gates(content_id: str, skill: str, required: int) -> None:
    service = GearService(load_content())

    def wear_at(level: int) -> dict:
        snapshot = AccountSnapshot(
            player_id=1,
            username="gear tester",
            skills={
                skill: SkillState(level=level, xp=None, source=Source.RUNELITE, observed_at=SEEN)
            },
        )
        return service.item_details(snapshot, content_id=content_id)["items"][0]["wear"]

    below = wear_at(required - 1)
    assert below["status"] == "unsatisfied"
    assert below["unmet"][0]["key"] == skill
    assert below["unmet"][0]["required"] == required
    assert wear_at(required)["status"] == "satisfied"


def test_imbued_suffering_ring_retains_base_hitpoints_requirement() -> None:
    service = GearService(load_content())
    snapshot = AccountSnapshot(
        player_id=1,
        username="gear tester",
        skills={
            "hitpoints": SkillState(level=74, xp=None, source=Source.RUNELITE, observed_at=SEEN)
        },
    )
    wear = service.item_details(snapshot, content_id="ring_of_suffering_i")["items"][0]["wear"]
    assert wear["status"] == "unsatisfied"
    assert wear["unmet"][0]["required"] == 75


@pytest.mark.parametrize("content_id", ["book_of_law", "book_of_darkness"])
def test_filled_god_books_require_horror_from_the_deep(content_id: str) -> None:
    service = GearService(load_content())
    incomplete = AccountSnapshot(
        player_id=1,
        username="gear tester",
        quests={"horror_from_the_deep": QuestStatus.NOT_STARTED},
    )
    complete = AccountSnapshot(
        player_id=1,
        username="gear tester",
        quests={"horror_from_the_deep": QuestStatus.COMPLETE},
    )
    wear = service.item_details(incomplete, content_id=content_id)["items"][0]["wear"]
    assert wear["status"] == "unsatisfied"
    assert wear["unmet"][0]["key"] == "horror_from_the_deep"
    assert (
        service.item_details(complete, content_id=content_id)["items"][0]["wear"]["status"]
        == "satisfied"
    )


def test_gear_proposal_does_not_persist_changes(make_item, make_content) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    with sessions.begin() as db:
        db.add(Player(id=1, username="fixture", display_name="Fixture", created_at=SEEN))
        db.flush()
        db.add(
            ContainerScan(
                player_id=1,
                container=Container.BANK,
                source=Source.RUNELITE,
                scanned_at=SEEN,
            )
        )
    accounts = AccountService(sessions)
    before = accounts.get_snapshot(1)
    service = GearService(make_content(items=[make_item("proposal", numeric_id=123)]))

    result = service.evaluate_change(
        before,
        style="melee",
        changes=[{"slot": "weapon", "content_id": "proposal"}],
        expected_snapshot_id=before.fingerprint,
    )

    after = accounts.get_snapshot(1)
    assert result["snapshot_id"] == before.fingerprint
    assert after.fingerprint == before.fingerprint
    assert after.observed_items == before.observed_items == {}
    assert after.container_scans == before.container_scans
    with sessions() as db:
        assert db.query(ObservedItem).count() == 0
        assert db.query(ContainerScan).count() == 1
    engine.dispose()
