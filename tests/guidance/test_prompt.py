"""§21.3 — the stable half is stable, and the hash tracks what the advice depends on.

The two properties here are worth more than they look.

**The cacheability assertion is the one that pays for itself.** Providers match cached
prompts by prefix, so a player name or a timestamp in :data:`SYSTEM_PROMPT` would not raise,
would not change a single rendered word, and would multiply the running cost of the whole
feature. It fails no test unless a test looks for it, which is what these do.

**The hash assertions are §21.5's correctness.** Too sensitive and every sync re-bills the
user; too coarse and stale advice outlives the levels it was written for. What the hash must
track is the *rendered facts* — which is why an irrelevant skill moving must not move it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from tracker.content.loader import Content
from tracker.content.schema import Candidate, MethodDetail, TrainingMethod
from tracker.domain.types import (
    AccountType,
    BandEstimate,
    Container,
    ItemObservation,
    LeafRef,
    PlayerState,
    Recommendation,
    RoadmapSelection,
)
from tracker.guidance.context import ItemFact, SkillFact, TaskContext, build_task_context
from tracker.guidance.prompt import (
    SYSTEM_PROMPT,
    build_prompt,
    context_hash,
    render_context,
)


class TestTheStableHalfIsStable:
    """Everything here protects the prompt cache, and nothing here is visible in output."""

    def test_the_system_prompt_holds_no_date_like_run(self) -> None:
        """One interpolated ``datetime.now()`` would silently zero the cache hit rate."""
        assert re.search(r"\d{4}-\d{2}-\d{2}", SYSTEM_PROMPT) is None
        assert re.search(r"\d{2}:\d{2}", SYSTEM_PROMPT) is None

    def test_the_system_prompt_holds_no_account_specifics(self) -> None:
        """It is a module constant; anything account-shaped in it is a bug, not a typo."""
        forbidden = ("player_id", "candidate_id", "level 87", "ironman", "gp (observed)")
        for token in forbidden:
            assert token not in SYSTEM_PROMPT

    def test_the_system_prompt_clears_the_minimum_cacheable_prefix(self) -> None:
        """Providers refuse to cache a short prefix silently — no error, just no caching.

        Asserted in characters rather than tokens because counting tokens needs the provider's
        tokenizer, which is exactly the network dependency this suite does not have. A few
        thousand characters is comfortably past any current minimum, and the failure this
        guards against is someone trimming the instructions to a paragraph.
        """
        assert len(SYSTEM_PROMPT) > 3000

    def test_build_prompt_puts_the_account_only_in_the_user_half(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        context = build_task_context(
            state=make_player_state(skills={"slayer": 4}, account_type=AccountType.IRONMAN),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )
        prompt = build_prompt(context)

        assert prompt.system == SYSTEM_PROMPT
        assert "ironman" in prompt.user
        assert "ironman" not in prompt.system

    def test_the_system_prompt_states_the_grounding_rules_it_is_relied_on_for(self) -> None:
        """Each of these names a behaviour the rest of the feature is built assuming."""
        assert "uncertain" in SYSTEM_PROMPT
        assert "unknown" in SYSTEM_PROMPT
        assert "tracker's" in SYSTEM_PROMPT

    def test_the_system_prompt_demands_an_answer_specific_to_the_account(self) -> None:
        """The instruction that stops §21 producing advice fit for anybody.

        §21.2 spends real money assembling a per-account slice, and an instruction block that
        does not require the model to *use* it fails silently: the answers stay fluent, stay
        correct, and stay generic. There is no exception and no wrong number attached to that
        failure, so a test is the only thing that notices when the rule is trimmed away.
        """
        assert "identically for any account" in SYSTEM_PROMPT


class TestContextHash:
    def test_a_relevant_level_change_moves_the_hash(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """Advice written for Slayer 4 is not advice for Slayer 9."""
        content = make_content(candidates=[make_candidate("train_slayer_10")])
        recommendation = make_recommendation()

        def hash_at(level: int) -> str:
            context = build_task_context(
                state=make_player_state(skills={"slayer": level}),
                recommendation=recommendation,
                content=content,
                roadmaps=no_roadmaps,
            )
            return build_prompt(context).context_hash

        assert hash_at(4) != hash_at(9)

    def test_an_irrelevant_level_change_does_not_move_the_hash(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """Otherwise a Fishing level-up re-bills the user for Slayer advice."""
        content = make_content(candidates=[make_candidate("train_slayer_10")])
        recommendation = make_recommendation()

        def hash_with_fishing(level: int) -> str:
            context = build_task_context(
                state=make_player_state(skills={"slayer": 4, "fishing": level}),
                recommendation=recommendation,
                content=content,
                roadmaps=no_roadmaps,
            )
            return build_prompt(context).context_hash

        assert hash_with_fishing(30) == hash_with_fishing(70)

    def test_the_hash_covers_the_instruction_block(self) -> None:
        """Advice written under different instructions is different advice."""
        assert context_hash("system A", "user") != context_hash("system B", "user")

    def test_the_hash_covers_the_rendered_account(self) -> None:
        assert context_hash("system", "user A") != context_hash("system", "user B")

    def test_the_hash_is_a_sha256_digest(self) -> None:
        digest = context_hash("system", "user")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)

    def test_building_the_same_prompt_twice_gives_the_same_hash(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        context = build_task_context(
            state=make_player_state(skills={"slayer": 4}),
            recommendation=make_recommendation(),
            content=make_content(candidates=[make_candidate("train_slayer_10")]),
            roadmaps=no_roadmaps,
        )

        assert build_prompt(context).context_hash == build_prompt(context).context_hash


class TestRendering:
    def test_unscanned_coins_are_not_rendered_as_a_number(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: datetime,
    ) -> None:
        """§6.5's middle state has to survive into the text, not just into the dataclass."""
        content = make_content(candidates=[make_candidate("train_slayer_10")])
        recommendation = make_recommendation()

        unscanned = render_context(
            build_task_context(
                state=make_player_state(),
                recommendation=recommendation,
                content=content,
                roadmaps=no_roadmaps,
            )
        )
        scanned_empty = render_context(
            build_task_context(
                state=make_player_state(container_scans={Container.BANK: observed_at}),
                recommendation=recommendation,
                content=content,
                roadmaps=no_roadmaps,
            )
        )

        assert "Coins on hand: unknown" in unscanned
        assert "no container has been scanned" in unscanned
        assert "Coins on hand: 0 gp (observed)" in scanned_empty

    def test_an_unobserved_skill_reads_as_never_observed(self) -> None:
        rendered = render_context(
            TaskContext(
                task_name="Train Slayer to 10",
                kind="skill_training",
                relevant_skills=(
                    SkillFact(
                        skill_id="slayer",
                        name="Slayer",
                        level=None,
                        is_ranked=False,
                        target=10,
                    ),
                ),
            )
        )

        assert "Slayer: never observed, target 10" in rendered

    def test_the_selected_method_is_marked_in_the_text(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        methods = [
            make_method("turael", skill="slayer", name="Turael tasks", xp_per_hour=8_000),
            make_method("mazchna", skill="slayer", name="Mazchna tasks", xp_per_hour=15_000),
        ]
        recommendation = make_recommendation(
            bands=[BandEstimate(from_level=1, to_level=10, method_id="turael", hours=2.0, gp=0)]
        )
        rendered = render_context(
            build_task_context(
                state=make_player_state(skills={"slayer": 1}),
                recommendation=recommendation,
                content=make_content(
                    candidates=[make_candidate("train_slayer_10")], methods=methods
                ),
                roadmaps=no_roadmaps,
            )
        )

        assert "## Turael tasks **(the tracker's estimate is based on this one)**" in rendered
        assert "## Mazchna tasks\n" in rendered

    def test_a_blocked_task_says_what_blocks_it(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        blocker = LeafRef(leaf_type="quest", key="lunar_diplomacy", description="Lunar Diplomacy")
        rendered = render_context(
            build_task_context(
                state=make_player_state(),
                recommendation=make_recommendation(blocked=True, blockers=[blocker]),
                content=make_content(candidates=[make_candidate("train_slayer_10")]),
                roadmaps=no_roadmaps,
            )
        )

        assert "currently **blocked**" in rendered
        assert "Lunar Diplomacy" in rendered

    def test_an_unknown_gate_says_nobody_looked_rather_than_naming_a_blocker(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """G3 — an unknown gate is a reason to sync, not a reason to grind."""
        rendered = render_context(
            build_task_context(
                state=make_player_state(),
                recommendation=make_recommendation(unknown_gate=True),
                content=make_content(candidates=[make_candidate("train_slayer_10")]),
                roadmaps=no_roadmaps,
            )
        )

        assert "never been observed" in rendered
        assert "Do not assume either way." in rendered

    def test_the_estimate_is_attributed_to_the_tracker(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """D14 — §8 owns the hours, and the model must not restate them as measurement."""
        rendered = render_context(
            build_task_context(
                state=make_player_state(),
                recommendation=make_recommendation(hours=2.5, gp=15_000),
                content=make_content(candidates=[make_candidate("train_slayer_10")]),
                roadmaps=no_roadmaps,
            )
        )

        assert "The tracker estimates about 2.5 hours and about 15,000 gp" in rendered
        assert "This figure is the tracker's, not yours." in rendered

    def test_empty_sections_are_omitted_rather_than_rendered_empty(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
    ) -> None:
        """An empty heading reads as *"there are none"*; the truth is *"not applicable"*."""
        rendered = render_context(
            build_task_context(
                state=make_player_state(skills={"slayer": 4}),
                recommendation=make_recommendation(),
                content=make_content(candidates=[make_candidate("train_slayer_10")]),
                roadmaps=no_roadmaps,
            )
        )

        assert "# Relevant quests" not in rendered
        assert "# Relevant unlocks" not in rendered
        assert "# Training methods" not in rendered
        assert "# Account" in rendered

    def test_a_held_item_is_named_with_where_it_was_seen(self) -> None:
        """The line that stops the model guessing at gear it was in fact told about."""
        rendered = render_context(
            TaskContext(
                task_name="Train Slayer to 10",
                scanned_containers=("bank", "inventory", "equipment"),
                items=(
                    ItemFact(
                        item_id="rune_crossbow",
                        name="Rune crossbow",
                        state="held",
                        quantity=1,
                        containers=("equipment",),
                    ),
                ),
            )
        )

        assert "- Rune crossbow: held, in equipment" in rendered

    def test_a_required_item_is_listed_even_when_not_held(self) -> None:
        """*"You need this and do not have it"* is the whole point of listing it."""
        rendered = render_context(
            TaskContext(
                scanned_containers=("bank", "inventory", "equipment"),
                items=(
                    ItemFact(
                        item_id="voidwaker",
                        name="Voidwaker",
                        state="not held",
                        required=True,
                    ),
                ),
            )
        )

        assert "- Voidwaker: not held *(this task needs it)*" in rendered

    def test_a_partial_scan_says_absence_is_not_proof(self) -> None:
        """§4.5's middle state, in the one place a model would otherwise read it as a "no"."""
        rendered = render_context(TaskContext(scanned_containers=("bank",)))

        assert "Never scanned: inventory, equipment" in rendered
        assert "absence below is not proof they lack it" in rendered

    def test_nothing_scanned_says_so_rather_than_omitting_the_section(self) -> None:
        """An omitted section reads as *"not applicable"*; here it would read as *"no gear"*."""
        rendered = render_context(TaskContext())

        assert "# Gear and items" in rendered
        assert "No container has ever been scanned" in rendered

    def test_the_item_section_disowns_the_gear_it_cannot_see(self) -> None:
        """The instruction that answers the complaint this section was built for.

        A model shown a short item list and nothing else concludes the bank is empty, or
        opens with a paragraph apologising for not knowing what the player is wearing. Both
        are worse than the truth, which is that the tracker names a few items and no more.
        """
        rendered = render_context(
            TaskContext(
                scanned_containers=("bank", "inventory", "equipment"),
                items=(ItemFact(item_id="voidwaker", name="Voidwaker", state="not held"),),
            )
        )

        assert "the tracker sees nothing else in the bank" in rendered
        assert "unseen rather than absent" in rendered
        assert "apologising for not knowing their gear" in rendered

    def test_the_whole_rendering_is_a_golden_string(
        self,
        make_player_state: Callable[..., PlayerState],
        make_candidate: Callable[..., Candidate],
        make_content: Callable[..., Content],
        make_method: Callable[..., TrainingMethod],
        make_recommendation: Callable[..., Recommendation],
        no_roadmaps: RoadmapSelection,
        observed_at: datetime,
    ) -> None:
        """One canonical context, pinned end to end.

        The per-property tests above each cover one rule; this covers the *composition* —
        section order, spacing, and the fact that a change anywhere moves the hash and
        therefore invalidates every stored note. Updating it is meant to be a deliberate act.
        """
        method = make_method(
            "turael",
            skill="slayer",
            name="Turael tasks",
            from_level=1,
            to_level=20,
            xp_per_hour=8_000,
            detail=MethodDetail(
                location="Turael, Burthorpe",
                target="low-level assigned tasks",
                gear=("any melee weapon",),
                inventory=("food",),
                notes="Short tasks; safe to cancel.",
            ),
        )
        state = make_player_state(
            skills={"slayer": 4},
            account_type=AccountType.IRONMAN,
            members=True,
            combat_level=42,
            quest_points=12,
            container_scans={Container.BANK: observed_at},
            observed_items={
                995: ItemObservation(
                    item_id=995,
                    quantity=250_000,
                    containers=frozenset({Container.BANK}),
                    observed_at=observed_at,
                )
            },
        )
        recommendation = make_recommendation(
            hours=2.0,
            gp=0,
            bands=[BandEstimate(from_level=1, to_level=10, method_id="turael", hours=2.0, gp=0)],
        )
        rendered = render_context(
            build_task_context(
                state=state,
                recommendation=recommendation,
                content=make_content(
                    candidates=[make_candidate("train_slayer_10")], methods=[method]
                ),
                roadmaps=no_roadmaps,
            )
        )

        assert rendered == (
            "# Task\n"
            "\n"
            "**Train Slayer to 10** (skill training)\n"
            "\n"
            "The tracker chose it because: quick to finish\n"
            "\n"
            "The tracker estimates about 2.0 hours and about 0 gp (confidence: medium). "
            "This figure is the tracker's, not yours.\n"
            "\n"
            "Estimated in bands:\n"
            "- level 1 to 10 via turael: 2.0h, 0 gp\n"
            "\n"
            "# Account\n"
            "\n"
            "- Account type: ironman\n"
            "- Members: yes\n"
            "- Combat level: 42\n"
            "- Quest points: 12\n"
            "- Coins on hand: 250,000 gp (observed)\n"
            "\n"
            "# Relevant skills\n"
            "\n"
            "Only the skills this task depends on are listed; the rest of the account is "
            "not shown.\n"
            "\n"
            "- Slayer: level 4, target 10\n"
            "\n"
            "# Gear and items\n"
            "\n"
            "Scanned in full: bank. Never scanned: inventory, equipment — an item could be "
            "sitting there unseen, so absence below is not proof they lack it.\n"
            "\n"
            "The ladders cover weapons, armour and jewellery for all three combat styles. "
            "They do not cover supplies, resources or quest items, and the tracker sees "
            "nothing else in the bank — so a rung is authoritative, and everything off the "
            "ladders is unseen rather than absent.\n"
            "\n"
            "Use this rather than guessing. If they are shown holding a weapon, do not tell "
            "them to buy a worse one, and do not open your answer by apologising for not "
            "knowing their gear. Where advice turns on something off the ladders, put the "
            'condition in the line that needs it — "if you are not already stocked with '
            'food" — and carry on.\n'
            "\n"
            "# Training methods from the tracker's content\n"
            "\n"
            "Prefer these, by these names.\n"
            "\n"
            "## Turael tasks **(the tracker's estimate is based on this one)**\n"
            "- Skill: slayer, levels 1–20\n"
            "- 8,000 xp/hour, 0 gp/hour\n"
            "- Where: Turael, Burthorpe\n"
            "- What: low-level assigned tasks\n"
            "- Gear: any melee weapon\n"
            "- Inventory: food\n"
            "- Notes: Short tasks; safe to cancel."
        )
