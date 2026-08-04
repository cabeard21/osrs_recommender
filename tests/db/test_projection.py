"""``build_player_state`` and the seam it forms with the §9.1 evaluator.

Most of these tests do not stop at the :class:`PlayerState`. They seed rows, project, and
then hand the result to :func:`tracker.progression.evaluate.evaluate` with a real
requirement leaf, asserting the resulting :class:`~tracker.domain.types.Tri`. That is
deliberate: Step 3b produces the facts and Step 4 interprets them, and every rule worth
testing here — §6.5's three-way ownership, A7's ``attested``, A6's ``last_sync_at`` — is
only *meaningful* as the input to a leaf resolver. A projection that is internally
consistent but disagrees with the evaluator about what absence means would pass any
assertion made on the ``PlayerState`` alone, and is precisely the failure this seam has.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from tests.db.conftest import NOW, VOIDWAKER_ITEM_ID
from tracker.content.loader import Content
from tracker.content.requirements import CombatLevelLeaf, ItemLeaf, MilestoneLeaf
from tracker.content.schema import Item
from tracker.content.schema import Milestone as AuthoredMilestone
from tracker.db.models import ContainerScan, Milestone, ObservedItem, QuestState, Unlock
from tracker.db.projection import build_player_state
from tracker.db.repository import PlayerNotFoundError, append_skill_snapshot
from tracker.domain.types import (
    Container,
    GpSensitivity,
    MilestoneClass,
    MilestoneKind,
    QuestStatus,
    Source,
    Tri,
    UnlockState,
)
from tracker.progression.evaluate import evaluate

PlayerFactory = Callable[..., int]
ContentFactory = Callable[..., Content]

VOIDWAKER = Item(id="voidwaker", name="Voidwaker", item_id=VOIDWAKER_ITEM_ID)
VOIDWAKER_LEAF = ItemLeaf(item_id="voidwaker")

SWITCHES = AuthoredMilestone(
    id="comfortable_4_way_switches",
    name="Comfortable 4-way switches",
    class_=MilestoneClass.EXECUTION,
    kind=MilestoneKind.SELF_ATTESTED,
    practice_group="nh_fundamentals",
)
SWITCHES_LEAF = MilestoneLeaf(key="comfortable_4_way_switches")


def _scan(session: Session, player_id: int, container: Container, *, at: datetime = NOW) -> None:
    session.add(
        ContainerScan(
            player_id=player_id, container=container, scanned_at=at, source=Source.RUNELITE
        )
    )


def _sighting(
    session: Session,
    player_id: int,
    container: Container,
    *,
    quantity: int = 1,
    at: datetime = NOW,
    item_id: int = VOIDWAKER_ITEM_ID,
) -> None:
    session.add(
        ObservedItem(
            player_id=player_id,
            item_id=item_id,
            container=container,
            quantity=quantity,
            source=Source.RUNELITE,
            observed_at=at,
        )
    )


class TestItemOwnershipThroughTheEvaluator:
    """§6.5's three-way ownership table, end to end (§4.5, §9.1).

    The rule under test belongs to :meth:`Evaluator._item`, not to the projection — an
    ``item:`` leaf names no container, so the item is only *absent* once every container
    has been scanned. What these tests prove is that the two facts this module supplies
    are the two facts that rule reads.
    """

    def test_item_seen_in_a_scan_resolves_satisfied(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        player_id = new_player(session)
        _scan(session, player_id, Container.BANK)
        _sighting(session, player_id, Container.BANK)
        session.commit()

        state = build_player_state(session, player_id)
        content = build_content(items=[VOIDWAKER])

        assert evaluate(VOIDWAKER_LEAF, state, content).value is Tri.SATISFIED

    def test_every_container_scanned_and_item_absent_resolves_unsatisfied(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """A genuine blocker — we have looked everywhere it could be."""
        player_id = new_player(session)
        for container in Container:
            _scan(session, player_id, container)
        session.commit()

        state = build_player_state(session, player_id)
        assert state.observed_items == {}
        assert set(state.container_scans) == set(Container)

        content = build_content(items=[VOIDWAKER])
        assert evaluate(VOIDWAKER_LEAF, state, content).value is Tri.UNSATISFIED

    def test_a_container_never_scanned_leaves_ownership_unknown(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """Bank and inventory seen, equipment never — *"you don't have one"* is a guess.

        This is the case a projection that defaulted a missing scan to ``datetime.min``
        would get wrong, and it would get it wrong in the direction that tells the user
        to go buy something they may be wearing.
        """
        player_id = new_player(session)
        _scan(session, player_id, Container.BANK)
        _scan(session, player_id, Container.INVENTORY)
        session.commit()

        state = build_player_state(session, player_id)
        assert Container.EQUIPMENT not in state.container_scans

        content = build_content(items=[VOIDWAKER])
        assert evaluate(VOIDWAKER_LEAF, state, content).value is Tri.UNKNOWN

    def test_never_scanned_at_all_is_unknown_not_unsatisfied(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """The first-run case: a fresh account owes ``unknown``, never a blocker (§4.5)."""
        player_id = new_player(session)
        session.commit()

        state = build_player_state(session, player_id)
        assert state.container_scans == {}

        content = build_content(items=[VOIDWAKER])
        assert evaluate(VOIDWAKER_LEAF, state, content).value is Tri.UNKNOWN


class TestItemMerging:
    """§6.5's per-container rows collapse into one per-item observation."""

    def test_two_containers_collapse_into_one_observation(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """Quantities sum, containers union, ``observed_at`` keeps the fresher sighting."""
        player_id = new_player(session)
        yesterday = NOW - timedelta(days=1)
        _sighting(session, player_id, Container.BANK, quantity=2, at=yesterday)
        _sighting(session, player_id, Container.EQUIPMENT, quantity=1, at=NOW)
        session.commit()

        state = build_player_state(session, player_id)

        assert list(state.observed_items) == [VOIDWAKER_ITEM_ID]
        observation = state.observed_items[VOIDWAKER_ITEM_ID]
        assert observation.containers == frozenset({Container.BANK, Container.EQUIPMENT})
        assert observation.quantity == 3
        assert observation.observed_at == NOW

    def test_distinct_items_stay_distinct(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        _sighting(session, player_id, Container.BANK, item_id=VOIDWAKER_ITEM_ID)
        _sighting(session, player_id, Container.BANK, item_id=11_802, quantity=1)
        session.commit()

        state = build_player_state(session, player_id)
        assert set(state.observed_items) == {VOIDWAKER_ITEM_ID, 11_802}


class TestSkills:
    """§6.2 and §7.4 — one current value per skill, and ``NULL`` xp survives."""

    def test_unranked_skill_projects_xp_none_never_zero(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """G5. ``0`` would be a claim about xp; ``None`` is the honest absence."""
        player_id = new_player(session)
        append_skill_snapshot(
            session,
            player_id,
            skill="runecraft",
            level=1,
            xp=None,
            source=Source.HISCORES,
            observed_at=NOW,
        )
        session.commit()

        state = build_player_state(session, player_id)

        assert state.skills["runecraft"].xp is None
        assert state.skills["runecraft"].level == 1

    def test_a_ranked_skill_carries_its_xp(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        append_skill_snapshot(
            session,
            player_id,
            skill="magic",
            level=94,
            xp=7_195_629,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        state = build_player_state(session, player_id)
        assert state.skills["magic"].xp == 7_195_629
        assert state.skills["magic"].source is Source.RUNELITE

    def test_the_most_recent_snapshot_wins(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """§7.4 rule 1. ``SkillSnapshot`` is a log, so the projection must select."""
        player_id = new_player(session)
        for level, days_ago in ((87, 30), (94, 1), (90, 10)):
            append_skill_snapshot(
                session,
                player_id,
                skill="magic",
                level=level,
                xp=None,
                source=Source.RUNELITE,
                observed_at=NOW - timedelta(days=days_ago),
            )
        session.commit()

        state = build_player_state(session, player_id)
        assert state.skills["magic"].level == 94

    def test_runelite_beats_hiscores_on_an_exact_tie(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """§7.4 rule 2. The hiscores only update on logout, so they are the stale one."""
        player_id = new_player(session)
        append_skill_snapshot(
            session,
            player_id,
            skill="magic",
            level=87,
            xp=4_000_000,
            source=Source.HISCORES,
            observed_at=NOW,
        )
        append_skill_snapshot(
            session,
            player_id,
            skill="magic",
            level=94,
            xp=7_195_629,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        state = build_player_state(session, player_id)
        assert state.skills["magic"].level == 94
        assert state.skills["magic"].source is Source.RUNELITE

    def test_a_skill_with_no_snapshot_is_absent_not_defaulted(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """§4.5. A skill nobody has observed is not level 1 — it is not in the mapping."""
        player_id = new_player(session)
        append_skill_snapshot(
            session,
            player_id,
            skill="magic",
            level=94,
            xp=None,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        state = build_player_state(session, player_id)
        assert "defence" not in state.skills


class TestMilestoneAttestation:
    """A7 — never prompted, declined and achieved are three different facts (§6.6)."""

    def _seed(
        self,
        session: Session,
        player_id: int,
        *,
        achieved: bool,
        attested_at: datetime | None,
    ) -> None:
        session.add(
            Milestone(
                player_id=player_id,
                key=SWITCHES.id,
                kind=MilestoneKind.SELF_ATTESTED,
                class_=MilestoneClass.EXECUTION,
                achieved=achieved,
                attested_at=attested_at,
                last_practiced_at=NOW - timedelta(days=3),
                source=Source.MANUAL,
                observed_at=NOW,
            )
        )
        session.commit()

    def test_never_prompted_projects_unknown_and_resolves_unknown(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """``attested_at IS NULL`` — *"we should ask"*, not *"you cannot do this"*."""
        player_id = new_player(session)
        self._seed(session, player_id, achieved=False, attested_at=None)

        state = build_player_state(session, player_id)
        assert state.milestones[SWITCHES.id].attested is Tri.UNKNOWN

        content = build_content(milestones=[SWITCHES])
        assert evaluate(SWITCHES_LEAF, state, content).value is Tri.UNKNOWN

    def test_declined_projects_unsatisfied_and_resolves_unsatisfied(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """Asked and answered no. Same ``achieved`` column, different fact (§4.5)."""
        player_id = new_player(session)
        self._seed(session, player_id, achieved=False, attested_at=NOW - timedelta(days=2))

        state = build_player_state(session, player_id)
        assert state.milestones[SWITCHES.id].attested is Tri.UNSATISFIED

        content = build_content(milestones=[SWITCHES])
        assert evaluate(SWITCHES_LEAF, state, content).value is Tri.UNSATISFIED

    def test_achieved_projects_satisfied_and_resolves_satisfied(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        player_id = new_player(session)
        self._seed(session, player_id, achieved=True, attested_at=NOW - timedelta(days=2))

        state = build_player_state(session, player_id)
        assert state.milestones[SWITCHES.id].attested is Tri.SATISFIED

        content = build_content(milestones=[SWITCHES])
        assert evaluate(SWITCHES_LEAF, state, content).value is Tri.SATISFIED

    def test_last_practiced_at_and_class_are_carried(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        """A6/§6.6 — the freshness service (§9.8) has nothing to age without these."""
        player_id = new_player(session)
        self._seed(session, player_id, achieved=True, attested_at=NOW)

        projected = build_player_state(session, player_id).milestones[SWITCHES.id]
        assert projected.last_practiced_at == NOW - timedelta(days=3)
        assert projected.class_ is MilestoneClass.EXECUTION
        assert projected.kind is MilestoneKind.SELF_ATTESTED

    def test_an_unpractised_milestone_carries_none_not_a_substituted_date(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        session.add(
            Milestone(
                player_id=player_id,
                key=SWITCHES.id,
                kind=MilestoneKind.SELF_ATTESTED,
                class_=MilestoneClass.EXECUTION,
                achieved=True,
                attested_at=NOW,
                source=Source.MANUAL,
                observed_at=NOW,
            )
        )
        session.commit()

        projected = build_player_state(session, player_id).milestones[SWITCHES.id]
        assert projected.last_practiced_at is None


class TestAccountLevelFacts:
    """§6.1 columns, and A6's ``last_sync_at`` gate."""

    def test_last_sync_at_null_makes_a_combat_level_leaf_unknown(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        """A6. The stored ``combat_level`` is deliberately *not* absent — only the sync is.

        ``Evaluator._combat_level`` checks ``last_sync_at`` before it looks at the value,
        so a projection that substituted a timestamp would flip this leaf to
        ``unsatisfied`` and turn *"sync this account"* into *"go train"* (G3).
        """
        player_id = new_player(session, last_sync_at=None, combat_level=126)
        session.commit()

        state = build_player_state(session, player_id)
        assert state.last_sync_at is None
        assert state.combat_level == 126

        content = build_content()
        assert evaluate(CombatLevelLeaf(level=100), state, content).value is Tri.UNKNOWN

    def test_a_synced_account_resolves_the_same_leaf(
        self, session: Session, new_player: PlayerFactory, build_content: ContentFactory
    ) -> None:
        player_id = new_player(session, last_sync_at=NOW, combat_level=126)
        session.commit()

        state = build_player_state(session, player_id)
        assert evaluate(CombatLevelLeaf(level=100), state, build_content()).value is Tri.SATISFIED

    def test_gp_sensitivity_and_quest_points_are_carried(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(
            session, quest_points=214, gp_sensitivity=GpSensitivity.HIGH, username="rag"
        )
        session.commit()

        state = build_player_state(session, player_id)
        assert state.player_id == player_id
        assert state.quest_points == 214
        assert state.gp_sensitivity is GpSensitivity.HIGH


class TestUnlocksAndQuests:
    """§6.3, §6.4 — stored enums pass through; a missing key is absent, not defaulted."""

    def test_unlocks_and_quests_project_by_key(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session)
        session.add_all(
            [
                Unlock(
                    player_id=player_id,
                    key="ancient_magicks",
                    state=UnlockState.UNLOCKED,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                ),
                Unlock(
                    player_id=player_id,
                    key="rigour",
                    state=UnlockState.AVAILABLE,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                ),
                QuestState(
                    player_id=player_id,
                    quest_id="desert_treasure_i",
                    status=QuestStatus.IN_PROGRESS,
                    source=Source.RUNELITE,
                    observed_at=NOW,
                ),
            ]
        )
        session.commit()

        state = build_player_state(session, player_id)

        assert state.unlocks == {
            "ancient_magicks": UnlockState.UNLOCKED,
            "rigour": UnlockState.AVAILABLE,
        }
        assert state.quests == {"desert_treasure_i": QuestStatus.IN_PROGRESS}
        assert "augury" not in state.unlocks


class TestPlayerIdentity:
    """A brand-new account is not an error; a nonexistent one is."""

    def test_a_player_with_no_fact_rows_projects_an_empty_but_valid_state(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        player_id = new_player(session, last_sync_at=None, combat_level=None, quest_points=None)
        session.commit()

        state = build_player_state(session, player_id)

        assert state.player_id == player_id
        assert state.skills == {}
        assert state.unlocks == {}
        assert state.quests == {}
        assert state.observed_items == {}
        assert state.container_scans == {}
        assert state.milestones == {}
        assert state.combat_level is None
        assert state.quest_points is None
        assert state.last_sync_at is None
        assert state.gp_sensitivity is GpSensitivity.NORMAL

    def test_an_unknown_player_id_raises(self, session: Session) -> None:
        """No row at all is a caller bug, not an unsynced account (§4.5)."""
        with pytest.raises(PlayerNotFoundError):
            build_player_state(session, 4_242)

    def test_one_players_facts_never_leak_into_anothers_state(
        self, session: Session, new_player: PlayerFactory
    ) -> None:
        mine = new_player(session, username="zezima")
        theirs = new_player(session, username="woox")
        _scan(session, theirs, Container.BANK)
        _sighting(session, theirs, Container.BANK)
        append_skill_snapshot(
            session,
            theirs,
            skill="magic",
            level=99,
            xp=None,
            source=Source.RUNELITE,
            observed_at=NOW,
        )
        session.commit()

        state = build_player_state(session, mine)
        assert state.observed_items == {}
        assert state.container_scans == {}
        assert state.skills == {}
