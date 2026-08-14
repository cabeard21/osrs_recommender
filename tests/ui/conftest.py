"""Fixtures for the Step 10 UI tests.

Two tiers, on purpose.

Most of §15's rules are decidable from data — what ``unknown`` renders as, whether an
unranked skill can show a level, whether blockers and unknowns stay apart — and those are
tested against :mod:`tracker.ui.view_model` and :mod:`tracker.ui.read_model` with no browser
at all. What genuinely needs a DOM is narrow: that two states produce **disjoint selectors**,
that the two lists are **separate nodes**, and that the page does not scroll sideways at
390 px. Those get a real browser.

The live server is session-scoped and there is exactly one of it. NiceGUI's ``@ui.page``
registers routes on a process-global router, so a second ``create_app(mount_ui=True)`` in one
pytest process would register the same paths twice. One app, one database, one seeded
account — and the seed therefore has to contain every state the tests need to see at once,
which is why it is deliberately a *worst case* account rather than a tidy one.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tracker.app import create_app
from tracker.config.settings import CONFIG_FILE_ENV_VAR, Settings
from tracker.content.loader import Content, load_content
from tracker.db.enums import RecommendationCandidateKind
from tracker.db.models import (
    ActiveRoadmap,
    Base,
    CapabilityState,
    ContainerScan,
    Milestone,
    Player,
    RecommendationEntry,
    RecommendationSnapshot,
    SkillSnapshot,
    Unlock,
)
from tracker.db.session import build_engine, build_session_factory
from tracker.domain.types import (
    Confidence,
    Container,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    Source,
    Status,
    UnlockState,
)
from tracker.integrations.llm.types import AdvisorTurn, ToolTraceEntry

#: A fixed clock, aware UTC. The staleness copy is a function of now (§6.5) and "3 weeks
#: ago" is not assertable against a moving one.
NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)

SEED_USERNAME = "zezima"


def _free_port() -> int:
    """An unused localhost port.

    Bound and released rather than hardcoded: a fixed port turns a leftover process from a
    previous run into a test that passes against the wrong application.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def seed(session: Session) -> int:
    """Write the worst-case account and return its id.

    Deliberately covers, in one player:

    * a capability that is ``unlocked`` with ``high`` readiness and recommended;
    * one ``unlocked`` with ``low`` readiness and **not** recommended — §4.4's middle case,
      where collapsing the layers would read as either "locked" or "go do it";
    * one ``unknown`` carrying both a blocker and an unknown leaf, so the two lists are
      non-empty simultaneously and cannot pass the separation test by both being empty;
    * one ``locked``, so ``unknown`` and ``locked`` are on screen together;
    * all four §6.3 unlock states;
    * a ranked skill and an unranked one (``xp = NULL``, §6.2);
    * a bank scanned three weeks ago and equipment never scanned at all (§6.5).
    """
    player = Player(
        username=SEED_USERNAME,
        display_name="Zezima",
        created_at=NOW - timedelta(days=400),
        last_sync_at=NOW - timedelta(hours=2),
        combat_level=126,
        quest_points=300,
        gp_sensitivity=GpSensitivity.NORMAL,
    )
    session.add(player)
    session.flush()
    player_id = int(player.id)

    session.add_all(
        [
            SkillSnapshot(
                player_id=player_id,
                skill="magic",
                level=94,
                xp=7_195_629,
                source=Source.RUNELITE,
                observed_at=NOW,
            ),
            # xp NULL is the whole point: §6.2 says NULL means unranked, never 0, and the
            # stored level of 1 is exactly the number §15 forbids rendering.
            SkillSnapshot(
                player_id=player_id,
                skill="construction",
                level=1,
                xp=None,
                source=Source.RUNELITE,
                observed_at=NOW,
            ),
        ]
    )

    for key, unlock_state in (
        ("ancient_magicks", UnlockState.UNLOCKED),
        ("rigour", UnlockState.AVAILABLE),
        ("augury", UnlockState.LOCKED),
        ("ca_grandmaster", UnlockState.UNKNOWN),
    ):
        session.add(
            Unlock(
                player_id=player_id,
                key=key,
                state=unlock_state,
                source=Source.RUNELITE,
                observed_at=NOW,
            )
        )

    session.add(
        ContainerScan(
            player_id=player_id,
            container=Container.BANK,
            scanned_at=NOW - timedelta(days=21),
            source=Source.RUNELITE,
        )
    )

    states = (
        ("budget_nh", Status.UNLOCKED, 1.0, Confidence.HIGH, True, None),
        (
            "ice_barrage_nh",
            Status.UNLOCKED,
            1.0,
            Confidence.LOW,
            False,
            "complete a refresher session first",
        ),
        ("deep_wildy_nh", Status.LOCKED, 0.4, None, False, "requirements are not met"),
        (
            "vengeance_pvp",
            Status.UNKNOWN,
            0.5,
            None,
            False,
            "bank contents have never been observed",
        ),
    )
    for capability_id, status, fraction, readiness, recommended, reason in states:
        session.add(
            CapabilityState(
                player_id=player_id,
                capability_id=capability_id,
                status=status,
                unlock_fraction=fraction,
                blockers=(
                    []
                    if status is Status.UNLOCKED
                    else [
                        {
                            "leaf_type": "skill",
                            "key": "magic",
                            "description": "Magic 94",
                            "target": 94,
                        }
                    ]
                ),
                unknowns=(
                    [
                        {
                            "leaf_type": "item",
                            "key": "voidwaker",
                            "description": "Voidwaker",
                            "target": None,
                        }
                    ]
                    if status is Status.UNKNOWN
                    else []
                ),
                readiness_confidence=readiness,
                warnings=["last practised 5 weeks ago"] if readiness is Confidence.LOW else [],
                recommended_now=recommended,
                recommended_now_reason=reason,
                computed_at=NOW,
            )
        )

    session.add(ActiveRoadmap(player_id=player_id, roadmap_id="main_nh", selection_weight=1.0))
    session.add(ActiveRoadmap(player_id=player_id, roadmap_id="anti_pk", selection_weight=0.25))

    # Step 11: both real corpus practice groups, achieved and stale enough (60d > the
    # 30d STALE_AFTER boundary) that both refresh templates trigger. Two groups, so the
    # G10 split is real on screen: one is persisted as the primary list's refresher entry
    # below, the other has no entry and must appear in the Practice freshness view via
    # subtraction (§9.8).
    stale_since = NOW - timedelta(days=60)
    for key in (
        "comfortable_4_way_switches",
        "consistent_overhead_prayers",
        "freeze_logging_practice",
        "vengeance_timing",
    ):
        session.add(
            Milestone(
                player_id=player_id,
                key=key,
                kind=MilestoneKind.SELF_ATTESTED,
                class_=MilestoneClass.EXECUTION,
                achieved=True,
                last_practiced_at=stale_since,
                source=Source.RUNELITE,
                observed_at=stale_since,
            )
        )

    snapshot = RecommendationSnapshot(
        player_id=player_id,
        run_at=NOW - timedelta(hours=2),
        roadmap_selection={"main_nh": 1.0, "anti_pk": 0.25},
        scoring_profile_version=1,
    )
    session.add(snapshot)
    session.flush()
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="train_magic_87_to_94",
            rank=1,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=1.42,
            factors={"pvp_value": {"value": 0.9, "weight": 1.0, "log_contribution": 0.61}},
            reason="high PvP value (+0.61) - unblocks 2 capabilities (+0.44)",
            estimated_hours=4.5,
            estimated_gp=1_800_000,
            estimate_confidence=Confidence.MEDIUM,
            # Step 8: two bands, one with an authored method and one that fell back, so the
            # browser test sees both halves of §15's "How" line. The fallback band is the
            # one §8.4 requires the UI to qualify rather than render blank.
            bands=[
                {
                    "from_level": 87,
                    "to_level": 94,
                    "method_id": "magic_bursting",
                    "hours": 4.0,
                    "gp": 1_600_000,
                    "fallback": False,
                },
                {
                    "from_level": 94,
                    "to_level": 95,
                    "method_id": None,
                    "hours": 0.5,
                    "gp": 0,
                    "fallback": True,
                },
            ],
            # Step 12: §9.10's consequences, one of each kind, so the browser test sees every
            # heading the renderer can draw. Written as the engine serializes them — ids
            # beside names — including one goal deliberately marked off-roadmap, which is the
            # case the whole feature turns on.
            consequences={
                "unblocks_capabilities": [
                    {"capability_id": "ice_barrage_nh", "name": "Ice Barrage NH"}
                ],
                "gate_progress": [
                    {
                        "candidate_id": "complete_desert_treasure_i",
                        "name": "Complete Desert Treasure I",
                        "remaining_before": 3,
                        "remaining_after": 2,
                        "satisfied": [],
                    }
                ],
                "goal_progress": [
                    {
                        "capability_id": "boss_fundamentals",
                        "name": "Boss fundamentals",
                        "weight": 0.5,
                        "remaining_before": 5,
                        "remaining_after": 4,
                        "on_roadmap": True,
                        "satisfied": [],
                    }
                ],
                "speeds_up": [
                    {
                        "candidate_id": "train_magic_94_to_99",
                        "name": "Train Magic 94 → 99",
                        "hours_before": 113.0,
                        "hours_after": 16.0,
                    }
                ],
                "goal_links": [
                    {
                        "capability_id": "deep_wildy_nh",
                        "name": "Deep Wilderness NH",
                        "weight": 0.0,
                        "on_roadmap": False,
                        "via_candidate_id": "complete_desert_treasure_i",
                        "via_name": "Complete Desert Treasure I",
                        "contribution": 0.6,
                    }
                ],
            },
            blocked=False,
        )
    )
    # G10: the one refresher §9.8 permits in the primary list. refresh_vengeance_fundamentals
    # is left unpersisted so it exercises the "rest go to Practice freshness" half of the rule.
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="refresh_nh_fundamentals",
            rank=2,
            candidate_kind=RecommendationCandidateKind.REFRESHER,
            score=0.55,
            factors={"proximity": {"value": 0.4, "weight": 0.6, "log_contribution": 0.12}},
            reason="practice has decayed (+0.12)",
            estimated_hours=0.5,
            estimated_gp=0,
            estimate_confidence=Confidence.HIGH,
            blocked=False,
        )
    )
    # §16.2: a blocked candidate, surfaced separately and never ranked.
    session.add(
        RecommendationEntry(
            snapshot_id=snapshot.id,
            candidate_id="buy_high_risk_gear",
            rank=3,
            candidate_kind=RecommendationCandidateKind.PROGRESSION,
            score=0.0,
            factors={},
            reason="",
            estimated_hours=None,
            estimated_gp=None,
            estimate_confidence=Confidence.LOW,
            # Step (c): a blocked entry now says *why*. Two leaf kinds, because the
            # rendering has to cope with a numeric target and with one that has none.
            blockers=[
                {
                    "leaf_type": "skill",
                    "key": "magic",
                    "description": "Magic 94",
                    "target": 94,
                },
                {
                    "leaf_type": "quest",
                    "key": "desert_treasure_i",
                    "description": "Desert Treasure I",
                    "target": None,
                },
            ],
            blocked=True,
        )
    )

    session.commit()
    return player_id


@pytest.fixture(scope="session", autouse=True)
def _ignore_the_developers_config(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Point ``Settings`` at a file that does not exist, for the whole UI session.

    ``Settings()`` layers ``config.yaml`` from the working directory beneath its constructor
    arguments, so on a machine that has actually configured §21 or §22 — which is to say, on
    the machine of anyone working on those features — the app under test comes up with a live
    provider. The "reports itself unconfigured" assertions then fail, and they fail *only*
    there: in CI, where no ``config.yaml`` exists, they pass.

    Session-scoped and autouse because the ``app`` fixture builds ``Settings`` once, before any
    individual test runs; a function-scoped fixture would be too late to matter.
    """
    absent = tmp_path_factory.mktemp("config") / "absent.yaml"
    previous = os.environ.get(CONFIG_FILE_ENV_VAR)
    os.environ[CONFIG_FILE_ENV_VAR] = str(absent)
    try:
        yield
    finally:
        if previous is None:
            del os.environ[CONFIG_FILE_ENV_VAR]
        else:
            os.environ[CONFIG_FILE_ENV_VAR] = previous


@pytest.fixture(scope="session")
def now() -> datetime:
    return NOW


@pytest.fixture(scope="session")
def content() -> Content:
    """The real seed corpus — the capability names and ids the pages render."""
    return load_content()


@pytest.fixture(scope="session")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    """One file-backed database for the whole session.

    A file rather than ``:memory:``: the live server opens its own connections from another
    thread, and an in-memory database is per-connection, so the server would find an empty
    schema.
    """
    directory: Path = tmp_path_factory.mktemp("ui")
    built = build_engine(f"sqlite:///{(directory / 'ui.db').as_posix()}")
    Base.metadata.create_all(built)
    yield built
    built.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


@pytest.fixture(scope="session")
def player_id(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as opened:
        return seed(opened)


@pytest.fixture
def session(session_factory: sessionmaker[Session], player_id: int) -> Iterator[Session]:
    with session_factory() as opened:
        yield opened


class ScriptedAdvisor:
    """A §22.5 provider that answers without a network.

    Injected rather than mocked at the transport, because what the browser tests are about is
    the *page* — that a question renders, that a hedge is drawn apart from the prose, that a
    failure lands in the conversation. Driving those through a scripted HTTP layer would add a
    second thing that can break without adding a second thing worth asserting.

    ``failure`` makes the next turn raise, which is how the error paths are reached: each of
    §21.4's three kinds renders its own sentence, and a page that collapsed them would be
    telling someone to retry something that will never succeed.
    """

    def __init__(self) -> None:
        self.failure: Exception | None = None
        self.answer = "Bring a whip and food."
        self.uncertain: tuple[str, ...] = ("crocodile spawns are from my own knowledge",)
        self.tool_trace: tuple[ToolTraceEntry, ...] = (
            ToolTraceEntry(name="list_training_methods", arguments={}, result_chars=120),
        )

    @property
    def model(self) -> str:
        return "scripted-advisor"

    def converse(self, prompt, tools, execute, *, max_iterations, max_tool_calls):  # type: ignore[no-untyped-def]
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure
        return AdvisorTurn(
            answer=self.answer,
            uncertain=self.uncertain,
            tool_trace=self.tool_trace,
            model=self.model,
            generated_at=NOW,
            stop_reason="end_turn",
        )

    def close(self) -> None:
        return None


@pytest.fixture(scope="session")
def advisor() -> ScriptedAdvisor:
    return ScriptedAdvisor()


@pytest.fixture(scope="session")
def app(
    session_factory: sessionmaker[Session],
    content: Content,
    player_id: int,
    advisor: ScriptedAdvisor,
) -> FastAPI:
    """The real application with the UI mounted. Exactly one per pytest process."""
    settings = Settings(
        bind_address="127.0.0.1",
        api_token="ui-test-token-1234567890",
        # The advisor's own throttles would otherwise refuse the second browser test to ask a
        # question — §22.7's interval is measured against a real clock this fixture does not own.
        integrations={"llm": {"advisor": {"min_interval_seconds": 0}}},
    )
    return create_app(
        settings,
        session_factory=session_factory,
        content=content,
        advisor_provider=advisor,  # type: ignore[arg-type]
        mount_ui=True,
    )


@pytest.fixture(scope="session")
def ui_base_url(app: FastAPI) -> Iterator[str]:
    """A live uvicorn serving ``app`` on a free port, for the duration of the session.

    A real server rather than a test client, because the assertions that need a browser need
    a websocket: NiceGUI delivers the element tree over one, so the HTML a test client
    receives contains none of the markup under test.

    Named ``ui_base_url`` and **not** ``base_url``: ``pytest-playwright`` ships a fixture of
    that name and consumes it from an autouse fixture, so overriding it would start this
    server — database, corpus and all — before every unit test in the package, including the
    ones that exist precisely so they need neither.
    """
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    waited = 0.0
    while not server.started and waited < 20.0:
        threading.Event().wait(0.05)
        waited += 0.05
    if not server.started:  # pragma: no cover — startup failure, not a test condition
        raise RuntimeError("the UI test server did not start")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)
