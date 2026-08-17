"""§22.4's gear tool: what it projects, and what it refuses.

The interesting assertions are the refusals. A tool that answered a malformed call by raising
would turn a recoverable model mistake into a failed turn, and one that quietly flattened
*unknown* into *no* would reintroduce, one layer out, the failure §23.4 is built to prevent.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from tests.advisor.conftest import NOW, make_content, make_snapshot, make_state
from tracker.advisor.dispatch import execute_tool
from tracker.advisor.snapshot import AdvisorSnapshot
from tracker.advisor.tools import MAX_TOOL_RESULT_CHARS, TOOLS
from tracker.content.schema import Item, ItemSlot, Skill
from tracker.domain.types import SkillState, Source
from tracker.integrations.llm.types import ToolCall

SPEC = next(spec for spec in TOOLS if spec.name == "get_gear_setup")

_LADDER = {
    "rune_scimitar": Item(
        id="rune_scimitar",
        name="Rune scimitar",
        item_id=1333,
        slot="weapon",
        style="melee",
        tier=1,
    ),
    "abyssal_whip": Item(
        id="abyssal_whip",
        name="Abyssal whip",
        item_id=4151,
        slot="weapon",
        style="melee",
        tier=2,
        requires={"skill": {"attack": 70}},  # type: ignore[arg-type]
    ),
}


def _snapshot(**overrides: Any) -> AdvisorSnapshot:
    content = make_content(
        items=_LADDER,
        skills={"attack": Skill(id="attack", name="Attack")},
    )
    return make_snapshot(content=content, **overrides)


def _at_attack(level: int) -> dict[str, SkillState]:
    return {"attack": SkillState(level=level, xp=None, source=Source.RUNELITE, observed_at=NOW)}


def _call(**arguments: Any) -> ToolCall:
    return ToolCall(call_id="c1", name="get_gear_setup", arguments=arguments)


class TestTheSpec:
    """Enums come from the content types, so the catalogue cannot drift from the corpus."""

    def test_the_slot_enum_matches_the_content_literal(self) -> None:
        assert SPEC.input_schema["properties"]["slot"]["enum"] == list(get_args(ItemSlot))

    def test_style_is_required(self) -> None:
        """All three ladders at once would exceed the result bound and truncate silently."""
        assert SPEC.input_schema["required"] == ["style"]

    def test_it_forbids_extra_arguments(self) -> None:
        assert SPEC.input_schema["additionalProperties"] is False

    def test_it_offers_no_hypothetical(self) -> None:
        """D15. A parameter positing different stats would make this an evaluator."""
        assert set(SPEC.input_schema["properties"]) == {"style", "slot"}


class TestBadInputIsAnErrorResult:
    """§22.4: the model can correct itself from an error; it cannot from an exception."""

    @pytest.mark.parametrize(
        "arguments", [{"style": "ranged_but_wrong"}, {}, {"style": "melee", "slot": "backpack"}]
    )
    def test_it_refuses_without_raising(self, arguments: dict[str, Any]) -> None:
        result = execute_tool(_snapshot(), _call(**arguments))
        assert result.is_error is True

    def test_an_unknown_style_names_the_real_ones(self) -> None:
        result = execute_tool(_snapshot(), _call(style="ranged_but_wrong"))
        assert "melee" in result.content


class TestTheResult:
    def test_it_reports_the_rung_the_account_can_actually_equip(self) -> None:
        state = make_state(skills=_at_attack(60))
        result = execute_tool(_snapshot(state=state), _call(style="melee", slot="weapon"))

        assert result.is_error is False
        assert "Rune scimitar" in result.content
        assert "Abyssal whip" in result.content

    def test_an_unscanned_account_is_told_so_before_anything_else(self) -> None:
        """The qualifier leads, because it qualifies every line beneath it."""
        result = execute_tool(_snapshot(), _call(style="melee"))
        assert result.content.startswith("Not every container has been scanned")

    def test_it_stays_within_the_result_bound(self) -> None:
        result = execute_tool(_snapshot(), _call(style="melee"))
        assert len(result.content) <= MAX_TOOL_RESULT_CHARS

    def test_dispatch_computes_nothing_and_repeats_itself(self) -> None:
        """D17: the work happened at snapshot time, so two calls cannot disagree."""
        snapshot = _snapshot()
        first = execute_tool(snapshot, _call(style="melee"))
        second = execute_tool(snapshot, _call(style="melee"))
        assert first.content == second.content
