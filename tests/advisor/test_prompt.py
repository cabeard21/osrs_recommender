"""§22.3's prompt: what must not vary, and what the hash must notice.

The cacheability assertions here have no runtime symptom when they fail. A varying system block
does not raise, does not slow anything measurably, and produces correct answers — it simply
stops every request reading from cache, and the only place that shows up is an invoice. Hence
tests.
"""

from __future__ import annotations

import re

from tests.advisor.conftest import make_capability_view, make_snapshot, make_state, make_task
from tracker.advisor.digest import build_digest, render_digest
from tracker.advisor.prompt import (
    ADVISOR_SYSTEM_PROMPT,
    ConversationTurn,
    build_prompt,
    digest_hash,
)
from tracker.guidance.prompt import SYSTEM_PROMPT as GUIDANCE_SYSTEM_PROMPT

#: Anything that looks like a date or a clock reading. A single one of these in the constant
#: would move the prefix daily.
_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b|\b20\d\d\b")


def _digest(**overrides: object) -> str:
    return render_digest(build_digest(make_snapshot(**overrides)))


class TestTheSystemPromptIsStable:
    def test_it_holds_nothing_date_like(self) -> None:
        assert _DATE_LIKE.search(ADVISOR_SYSTEM_PROMPT) is None

    def test_it_names_no_account_fact(self) -> None:
        """Everything account-shaped belongs in the second block, which is cached separately."""
        lowered = ADVISOR_SYSTEM_PROMPT.lower()
        for token in ("player_id", "combat level:", "account type:", "coins on hand"):
            assert token not in lowered

    def test_it_clears_the_minimum_cacheable_prefix(self) -> None:
        """Below roughly 512 tokens a prefix is not cached at all, and the split buys nothing.

        Characters rather than tokens because the tokenizer is the provider's; the ratio is
        conservative enough that clearing this margin clears the real bound.
        """
        assert len(ADVISOR_SYSTEM_PROMPT) > 2048

    def test_it_is_not_the_guidance_prompt(self) -> None:
        """§21 tells the model to answer only about one chosen task — the opposite of §22.1."""
        assert ADVISOR_SYSTEM_PROMPT != GUIDANCE_SYSTEM_PROMPT
        assert "Answer only about that task" not in ADVISOR_SYSTEM_PROMPT

    def test_build_prompt_returns_the_constant_unmodified(self) -> None:
        assert build_prompt(digest=_digest(), question="anything").system == ADVISOR_SYSTEM_PROMPT


class TestTheSystemPromptCarriesItsRules:
    """Each of these is a specific wrong answer the instruction block exists to prevent."""

    def test_it_states_that_unknown_is_not_a_no(self) -> None:
        assert 'not a "no"' in ADVISOR_SYSTEM_PROMPT
        assert "unknown coins are not zero" in ADVISOR_SYSTEM_PROMPT

    def test_it_tells_the_model_to_call_a_tool_rather_than_guess(self) -> None:
        assert "call a tool" in ADVISOR_SYSTEM_PROMPT
        assert "look it up" in ADVISOR_SYSTEM_PROMPT

    def test_it_states_d16s_consequence(self) -> None:
        """Tool results do not survive the turn, so a load-bearing fact must be restated."""
        assert "for this answer only" in ADVISOR_SYSTEM_PROMPT

    def test_it_forbids_restating_the_trackers_numbers_as_measured(self) -> None:
        assert "as your own measurement" in ADVISOR_SYSTEM_PROMPT

    def test_it_marks_gear_as_descriptive_rather_than_gating(self) -> None:
        """§10.5 — an item requirement would reprice the candidate; gear must not read as one."""
        assert "descriptive, not requirements" in ADVISOR_SYSTEM_PROMPT

    def test_it_permits_outside_knowledge_and_requires_it_be_flagged(self) -> None:
        assert "your own knowledge of Old School RuneScape is welcome" in ADVISOR_SYSTEM_PROMPT
        assert "`uncertain`" in ADVISOR_SYSTEM_PROMPT

    def test_it_stays_inside_the_game(self) -> None:
        assert "No real-world trading" in ADVISOR_SYSTEM_PROMPT


class TestTheHash:
    def test_it_is_stable_for_an_unchanged_prefix(self) -> None:
        digest = _digest()
        assert digest_hash(ADVISOR_SYSTEM_PROMPT, digest) == digest_hash(
            ADVISOR_SYSTEM_PROMPT, digest
        )

    def test_it_moves_when_the_account_moves(self) -> None:
        before = _digest(state=make_state(combat_level=90))
        after = _digest(state=make_state(combat_level=91))
        assert digest_hash(ADVISOR_SYSTEM_PROMPT, before) != digest_hash(
            ADVISOR_SYSTEM_PROMPT, after
        )

    def test_it_does_not_move_when_nothing_the_digest_shows_changes(self) -> None:
        """Two snapshots differing only in something the digest omits must share a prefix.

        The score is the example: it orders the list, and the digest prints the resulting rank
        rather than the number, so a rescoring that preserves order must not cost a re-cache.
        """
        quiet = _digest(ranked=(make_task(score=0.42),))
        also_quiet = _digest(ranked=(make_task(score=0.43),))
        assert digest_hash(ADVISOR_SYSTEM_PROMPT, quiet) == digest_hash(
            ADVISOR_SYSTEM_PROMPT, also_quiet
        )

    def test_it_moves_when_the_instruction_block_changes(self) -> None:
        digest = _digest()
        assert digest_hash(ADVISOR_SYSTEM_PROMPT, digest) != digest_hash(
            ADVISOR_SYSTEM_PROMPT + " and one more rule", digest
        )

    def test_it_moves_when_the_tool_catalogue_changes(self) -> None:
        """Tools render at position 0, so a changed catalogue invalidates the whole prefix."""
        digest = _digest()
        assert digest_hash(ADVISOR_SYSTEM_PROMPT, digest, "v1") != digest_hash(
            ADVISOR_SYSTEM_PROMPT, digest, "v2"
        )

    def test_every_layer_is_folded_in_separately(self) -> None:
        assert digest_hash("a", "b", "c") != digest_hash("a", "b", "d")
        assert digest_hash("a", "b", "c") != digest_hash("a", "x", "c")
        assert digest_hash("a", "b", "c") != digest_hash("x", "b", "c")

    def test_the_conversation_itself_is_not_hashed(self) -> None:
        """History grows every turn; a hash covering it could never indicate anything."""
        digest = _digest()
        empty = build_prompt(digest=digest, question="first")
        ongoing = build_prompt(
            digest=digest,
            question="second",
            history=(
                ConversationTurn(role="user", text="first"),
                ConversationTurn(role="assistant", text="an answer"),
            ),
        )
        assert empty.digest_hash == ongoing.digest_hash


class TestThePromptLayers:
    def test_the_digest_is_carried_separately_from_the_instructions(self) -> None:
        """Concatenating them would make a sync invalidate the instruction block too."""
        digest = _digest(capabilities=(make_capability_view(),))
        built = build_prompt(digest=digest, question="anything")
        assert built.digest == digest
        assert digest not in built.system

    def test_history_is_carried_in_order(self) -> None:
        turns = (
            ConversationTurn(role="user", text="one"),
            ConversationTurn(role="assistant", text="two"),
        )
        built = build_prompt(digest=_digest(), question="three", history=turns)
        assert built.history == turns
        assert built.question == "three"

    def test_digest_changed_defaults_to_false_and_is_carried_when_set(self) -> None:
        assert build_prompt(digest=_digest(), question="q").digest_changed is False
        assert build_prompt(digest=_digest(), question="q", digest_changed=True).digest_changed
