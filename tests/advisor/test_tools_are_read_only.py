"""D15's behavioural half: dispatch every tool, and prove nothing moved.

``test_import_boundary`` establishes that the advisor *cannot* reach a session. This establishes
the same conclusion from the other side, and the redundancy is deliberate: the import test would
pass if somebody handed a session in through an argument, and this test would pass if a write
happened through a path the fixture does not cover. Together they are hard to defeat by accident.

The signature check is the cheapest and most durable of the three. If nothing can pass a session
in, nothing inside can use one.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.advisor.conftest import make_capability_view, make_price, make_snapshot, make_task
from tracker.advisor.dispatch import execute_tool
from tracker.advisor.snapshot import AdvisorSnapshot
from tracker.advisor.tools import TOOLS
from tracker.integrations.llm.types import ToolCall

#: One plausible call per tool, chosen to reach a real result rather than an early error —
#: a tool that returns "no such id" has exercised almost none of its body.
_CALLS: dict[str, dict[str, Any]] = {
    "search_candidates": {"query": "magic"},
    "get_candidate_detail": {"candidate_id": "train_magic_87_94"},
    "get_capability_detail": {"capability_id": "ice_barrage_nh"},
    "list_training_methods": {"skill_id": "magic"},
    "get_quest_status": {"name_query": "desert"},
    "get_skill_detail": {"skill_id": "magic"},
    "get_item_price": {"item_ids": [995]},
}


def _snapshot() -> AdvisorSnapshot:
    return make_snapshot(
        capabilities=(make_capability_view(),),
        ranked=(make_task(),),
        prices={995: make_price()},
    )


def _dispatch_everything() -> None:
    snapshot = _snapshot()
    for spec in TOOLS:
        execute_tool(snapshot, ToolCall(call_id="c", name=spec.name, arguments=_CALLS[spec.name]))


def test_every_tool_has_a_representative_call() -> None:
    """Guards the fixture: a tool absent from ``_CALLS`` would go silently unexercised."""
    assert {spec.name for spec in TOOLS} == set(_CALLS)


def test_dispatching_every_tool_writes_nothing_to_a_database(tmp_path: Path) -> None:
    """A real SQLite file, hashed before and after. Any write at all changes the digest."""
    database = tmp_path / "tracker.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE player (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO player (id, name) VALUES (1, 'someone')")
    connection.commit()
    connection.close()

    before = hashlib.sha256(database.read_bytes()).hexdigest()
    _dispatch_everything()
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_execute_tool_accepts_no_session() -> None:
    """The durable version of the same guarantee: nothing can pass a session in."""
    parameters = inspect.signature(execute_tool).parameters
    assert list(parameters) == ["snapshot", "call"]
    annotation = str(parameters["snapshot"].annotation)
    assert "Session" not in annotation
    assert "AdvisorSnapshot" in annotation


def test_dispatch_is_deterministic_across_repeated_calls() -> None:
    """A tool that mutated the snapshot would answer differently the second time."""
    snapshot = _snapshot()
    for spec in TOOLS:
        call = ToolCall(call_id="c", name=spec.name, arguments=_CALLS[spec.name])
        assert execute_tool(snapshot, call) == execute_tool(snapshot, call), spec.name


def test_the_snapshot_is_frozen() -> None:
    """Frozen dataclasses are why a tool cannot write to the snapshot either."""
    snapshot = _snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        # ``setattr`` rather than an assignment statement: the type checker is right that the
        # assignment is invalid, and silencing it would silence the thing being asserted.
        setattr(snapshot, "state", None)  # noqa: B010
