"""Properties of the contract file itself (§12.1, §12.2, D12, G8)."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tracker.api.contract import (
    CONTRACT_PATH,
    load_sync_payload_schema,
    validate_sync_payload,
)

pytestmark = pytest.mark.contract


def test_the_contract_is_a_valid_2020_12_schema() -> None:
    Draft202012Validator.check_schema(load_sync_payload_schema())


def test_the_contract_lives_where_both_languages_look_for_it() -> None:
    """§12.1 names the path. The Java plugin references the same file, so moving it is a
    cross-language change, not a refactor.
    """
    assert CONTRACT_PATH.is_file()
    assert CONTRACT_PATH.parts[-2:] == ("contracts", "sync_payload.schema.json")


def test_the_contract_is_still_marked_provisional() -> None:
    """D12 / §12.1 — provisional until a real RuneLite snapshot has validated against it.

    This test is meant to *fail* at Step 8.5, which is when the marker is removed and the
    schema freezes. Failing then is the point: it makes the freeze a deliberate edit
    rather than something that happens when nobody is looking.
    """
    assert load_sync_payload_schema()["x-status"] == "provisional"


def _objects(node: Any, path: str = "<root>") -> list[tuple[str, dict[str, Any]]]:
    """Every subschema that declares ``properties``, with its location."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if "properties" in node:
            found.append((path, node))
        for key, value in node.items():
            found.extend(_objects(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_objects(value, f"{path}/{index}"))
    return found


def test_every_object_in_the_contract_forbids_additional_properties() -> None:
    """**G8**, structurally rather than per-field.

    The parametrized rejection tests in ``test_sync.py`` prove the boundary holds for the
    things §7.6 names today. This one proves it holds for the thing nobody has thought of
    yet: any object added to this schema without ``additionalProperties: false`` fails
    here, at authoring time.
    """
    offenders = [
        path
        for path, schema in _objects(load_sync_payload_schema())
        if schema.get("additionalProperties") is not False
    ]

    assert offenders == []


def test_validation_reports_the_offending_path() -> None:
    """A plugin author reads this string out of a 422 body. ``jsonschema``'s own multi-line
    report quotes the entire failing instance — thousands of lines for a bank scan.
    """
    message = validate_sync_payload(
        {
            "payload_version": 1,
            "observed_at": "2026-08-04T15:18:41+00:00",
            "player": {"username": "zezima"},
            "skills": [{"skill": "magic", "level": 200}],
        }
    )

    assert message is not None
    assert message.startswith("skills/0/level: ")
    assert "\n" not in message


def test_validation_is_deterministic_across_several_failures() -> None:
    """One broken plugin build must report the same error on every sync, or its author
    chases a different symptom each time.
    """
    payload = {
        "payload_version": 1,
        "observed_at": "not-a-timestamp",
        "player": {"username": ""},
        "quests": [{"quest_id": "Desert Treasure I", "status": "finished"}],
    }

    messages = {validate_sync_payload(payload) for _ in range(5)}

    assert len(messages) == 1
