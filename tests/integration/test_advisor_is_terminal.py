"""D14, end to end: a whole advisor conversation moves nothing the engine owns.

The unit tests establish the pieces — the advisor package imports no session
(``tests/advisor/test_import_boundary.py``), dispatch writes nothing
(``tests/advisor/test_tools_are_read_only.py``), the migration adds only its own two tables.
This asserts the property those pieces exist to produce, against the real database, by
comparing every engine-owned row before and after.

The comparison is a content hash of the whole table rather than a row count, because the
failure this guards against is not *more rows* — nobody is going to accidentally insert a
recommendation. It is a **changed** one: a reason overwritten, an estimate nudged, a
capability's status recomputed under a model's influence. A count would miss all three.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from tracker.advisor.prompt import AdvisorPrompt
from tracker.advisor.tools import TOOLS
from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.content.validate import load_and_validate
from tracker.db.models import (
    Base,
    CapabilityState,
    ItemPrice,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
    SkillSnapshot,
)
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import Confidence, Status
from tracker.integrations.llm.types import AdvisorTurn, ToolCall, ToolResult, ToolSpec
from tracker.sync.advisor import AdvisorService

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: Every table the engine owns. If the advisor can move any of these, D14 is broken.
ENGINE_TABLES = (
    RecommendationSnapshot,
    RecommendationEntry,
    CapabilityState,
    ItemPrice,
    SkillSnapshot,
    Player,
)

_ARGUMENTS: dict[str, dict[str, Any]] = {
    "search_candidates": {"query": "magic"},
    "get_candidate_detail": {"candidate_id": "train_magic_94_to_99"},
    "get_capability_detail": {"capability_id": "ice_barrage_nh"},
    "get_gear_setup": {"style": "melee"},
    "list_training_methods": {"skill_id": "magic"},
    "get_quest_status": {"name_query": "desert"},
    "get_skill_detail": {"skill_id": "magic"},
    "get_item_price": {"name_query": "coins"},
}


class _ToolUsingAdvisor:
    """Calls every tool, then answers. The most invasive thing a provider can legitimately do."""

    def __init__(self) -> None:
        self.results: list[ToolResult] = []

    @property
    def model(self) -> str:
        return "terminal-test"

    def converse(
        self,
        prompt: AdvisorPrompt,
        tools: Sequence[ToolSpec],
        execute: Callable[[ToolCall], ToolResult],
        *,
        max_iterations: int,
        max_tool_calls: int,
    ) -> AdvisorTurn:
        for index, spec in enumerate(tools):
            self.results.append(
                execute(
                    ToolCall(call_id=f"t{index}", name=spec.name, arguments=_ARGUMENTS[spec.name])
                )
            )
        return AdvisorTurn(answer="an answer", model=self.model, generated_at=NOW)

    def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def corpus() -> Content:
    return load_and_validate(CONTENT_ROOT)


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'terminal.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def seeded(factory: sessionmaker[Session]) -> int:
    """A player with a ranked run, so there is something an advisor could damage."""
    with factory() as session:
        player = Player(username="zezima", display_name="Zezima", created_at=NOW, last_sync_at=NOW)
        session.add(player)
        session.flush()

        snapshot = RecommendationSnapshot(
            player_id=player.id,
            run_at=NOW,
            roadmap_selection={"ice_barrage_nh": 1.0},
            scoring_profile_version=1,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            RecommendationEntry(
                snapshot_id=snapshot.id,
                rank=1,
                candidate_id="train_magic_94_to_99",
                candidate_kind="progression",
                score=0.42,
                reason="unblocks Ice Barrage NH",
                estimated_hours=16.0,
                estimated_gp=19_200_000,
                estimate_confidence=Confidence.MEDIUM,
                factors={"pvp_value": {"value": 0.9, "weight": 1.0, "log_contribution": -0.1}},
                blocked=False,
            )
        )
        session.add(
            CapabilityState(
                player_id=player.id,
                capability_id="ice_barrage_nh",
                status=Status.LOCKED,
                unlock_fraction=0.5,
                computed_at=NOW,
            )
        )
        session.commit()
        return player.id


def _fingerprint(session: Session) -> str:
    """A content hash of every engine-owned table, ordered."""
    digest = hashlib.sha256()
    for model in ENGINE_TABLES:
        table = cast("sa.Table", model.__table__)
        columns = sorted(table.columns.keys())
        rows = session.execute(
            sa.select(*[table.c[name] for name in columns]).order_by(*table.primary_key.columns)
        ).all()
        digest.update(table.name.encode("utf-8"))
        for row in rows:
            digest.update(json.dumps([str(value) for value in row], sort_keys=True).encode())
    return digest.hexdigest()


def _service(factory: sessionmaker[Session], corpus: Content, provider: Any) -> AdvisorService:
    settings = Settings(
        bind_address="127.0.0.1",
        api_token="token",
        integrations={
            "llm": {"enabled": True, "advisor": {"enabled": True, "min_interval_seconds": 0}}
        },
    )
    return AdvisorService(factory, corpus, settings, provider=provider, clock=lambda: NOW)


def test_a_tool_using_conversation_moves_no_engine_row(
    factory: sessionmaker[Session], corpus: Content, seeded: int
) -> None:
    """The headline assertion. Every tool runs; every engine table is byte-identical after."""
    with factory() as session:
        before = _fingerprint(session)

    provider = _ToolUsingAdvisor()
    service = _service(factory, corpus, provider)
    first = service.ask(seeded, "what should I do next?")
    service.ask(seeded, "and after that?", conversation_id=first.conversation_id)

    # The tools really ran, so the assertion below is about a conversation that happened.
    assert len(provider.results) == len(TOOLS) * 2

    with factory() as session:
        assert _fingerprint(session) == before


def test_the_conversation_was_actually_stored(
    factory: sessionmaker[Session], corpus: Content, seeded: int
) -> None:
    """Guards the test above: if nothing was written, its fingerprint would match trivially."""
    _service(factory, corpus, _ToolUsingAdvisor()).ask(seeded, "anything")
    with factory() as session:
        assert session.execute(sa.text("SELECT COUNT(*) FROM advisor_message")).scalar() == 2


def test_every_tool_answered_from_real_data(
    factory: sessionmaker[Session], corpus: Content, seeded: int
) -> None:
    """A snapshot assembled from empty reads would make the terminal test vacuous."""
    provider = _ToolUsingAdvisor()
    _service(factory, corpus, provider).ask(seeded, "anything")
    by_name = {spec.name: result for spec, result in zip(TOOLS, provider.results, strict=True)}
    assert "train_magic_94_to_99" in by_name["search_candidates"].content
    assert "Ice Barrage NH" in by_name["get_capability_detail"].content
    assert "unblocks Ice Barrage NH" in by_name["get_candidate_detail"].content


def test_the_advisor_tables_are_the_only_ones_it_writes(
    factory: sessionmaker[Session], corpus: Content, seeded: int
) -> None:
    """Stated as a property of the schema rather than of this run.

    Row counts across every non-advisor table, before and after — a stricter statement than
    the fingerprint in one respect: it would catch an *insert* into a table the fingerprint
    does not cover.
    """
    names = [name for name in Base.metadata.tables if not name.startswith("advisor_")]
    with factory() as session:
        before = {
            name: session.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar()
            for name in names
        }

    _service(factory, corpus, _ToolUsingAdvisor()).ask(seeded, "anything")

    with factory() as session:
        after = {
            name: session.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar()
            for name in names
        }
    assert after == before
