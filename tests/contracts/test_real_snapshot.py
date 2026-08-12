"""The frozen contract, guarded by a real RuneLite snapshot (plan step 8.5).

`real_snapshot.json` is an actual capture from RuneLite 1.12.35 — every skill, all 211 quests,
the diary and combat-achievement varbits, and three container scans — with the username
redacted. It is the evidence that froze `contracts/sync_payload.schema.json`; §12.2 now requires
a `payload_version` bump for any change that would break it.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "sync_payload.schema.json"
FIXTURE = Path(__file__).parent / "fixtures" / "real_snapshot.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_schema_is_itself_a_valid_2020_12_schema(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def test_a_real_runelite_snapshot_validates(schema: dict, snapshot: dict) -> None:
    jsonschema.Draft202012Validator(schema).validate(snapshot)


def test_the_contract_is_frozen(schema: dict) -> None:
    """§12.2. The provisional marker is gone; changes now cost a version bump."""
    assert "x-status" not in schema
    assert schema["properties"]["payload_version"]["minimum"] == 1


def test_the_snapshot_is_redacted() -> None:
    """A committed fixture must never carry a real account name."""
    assert json.loads(FIXTURE.read_text(encoding="utf-8"))["player"]["username"] == "redacted"


def test_an_observed_but_empty_container_still_emits_a_scan(snapshot: dict) -> None:
    """§6.5's whole point, and the capture that proved it is representable.

    The inventory was emptied (an item was withdrawn and then equipped), so it was *observed*
    holding nothing. It therefore carries a `container_scans` row and contributes no
    `observed_items` — which is what makes "you do not own it" distinguishable from "we have
    never looked".
    """
    scanned = {scan["container"] for scan in snapshot["container_scans"]}
    assert scanned == {"inventory", "equipment", "bank"}

    containers_with_items = {item["container"] for item in snapshot["observed_items"]}
    assert "inventory" in scanned
    assert "inventory" not in containers_with_items


def test_every_scan_timestamp_is_offset_aware(snapshot: dict) -> None:
    """§4.5. A naive timestamp is how an age becomes silently wrong."""
    for scan in snapshot["container_scans"]:
        assert scan["scanned_at"].endswith("Z") or "+" in scan["scanned_at"][-6:]


def test_quest_identity_matches_the_ids_content_authors(snapshot: dict) -> None:
    """The reconciliation's central ruling: `quest_id` is a slug of RuneLite's `Quest` constant.

    `content/` independently authors `desert_treasure_i` and `lunar_diplomacy`; the plugin
    derives exactly those strings from the enum. The agreement is what makes the slug rule
    defensible rather than convenient — see docs/CONTRACT_RECONCILIATION.md.
    """
    quest_ids = {quest["quest_id"] for quest in snapshot["quests"]}
    assert {"desert_treasure_i", "lunar_diplomacy"} <= quest_ids


def test_unranked_xp_is_never_negative(snapshot: dict) -> None:
    """G5. The client reports 0 for an untrained skill; -1 never reaches this contract."""
    assert all(skill["xp"] is None or skill["xp"] >= 0 for skill in snapshot["skills"])


def test_the_payload_carries_no_practice_events(snapshot: dict) -> None:
    """The spike collected none by design (G8) — practice detection is Step 12c's job."""
    assert "practice_events" not in snapshot
