"""§22.4's catalogue: the declarations, and the stability the cache depends on."""

from __future__ import annotations

import json

import pytest

import tracker.advisor.tools as tools_module
from tests.advisor.conftest import make_snapshot
from tracker.advisor.dispatch import execute_tool
from tracker.advisor.tools import TOOL_NAMES, TOOLS, tools_fingerprint
from tracker.integrations.llm.types import ToolCall, ToolSpec


class TestTheCatalogueIsWellFormed:
    def test_every_tool_is_a_toolspec(self) -> None:
        assert all(isinstance(spec, ToolSpec) for spec in TOOLS)

    def test_names_are_unique(self) -> None:
        assert len(TOOL_NAMES) == len(TOOLS)

    def test_names_are_sorted(self) -> None:
        """Tools render at position 0; a reordering would move the whole cached prefix."""
        assert [spec.name for spec in TOOLS] == sorted(spec.name for spec in TOOLS)

    def test_every_schema_forbids_additional_properties(self) -> None:
        """An invented argument should be rejected, not silently dropped.

        A dropped filter returns a plausible answer to a different question than the one asked,
        which is the worst available outcome.
        """
        for spec in TOOLS:
            assert spec.input_schema["additionalProperties"] is False, spec.name

    def test_every_schema_is_json_serialisable(self) -> None:
        for spec in TOOLS:
            json.dumps(spec.input_schema)

    def test_every_property_is_described(self) -> None:
        """The description is the whole interface; an undescribed argument goes unused."""
        for spec in TOOLS:
            for name, prop in spec.input_schema["properties"].items():
                assert prop.get("description") or prop.get("enum"), f"{spec.name}.{name}"

    def test_every_description_is_substantial(self) -> None:
        for spec in TOOLS:
            assert len(spec.description) > 80, spec.name

    def test_every_required_argument_is_declared_as_a_property(self) -> None:
        for spec in TOOLS:
            for name in spec.input_schema["required"]:
                assert name in spec.input_schema["properties"], f"{spec.name}.{name}"

    def test_every_declared_tool_has_a_handler(self) -> None:
        """A declared tool with no handler would answer 'no such tool' to a model we invited."""
        snapshot = make_snapshot()
        for spec in TOOLS:
            result = execute_tool(snapshot, ToolCall(call_id="x", name=spec.name, arguments={}))
            assert "there is no tool named" not in result.content, spec.name


class TestTheFingerprint:
    def test_it_is_stable_across_calls(self) -> None:
        assert tools_fingerprint() == tools_fingerprint()

    def test_it_moves_when_the_catalogue_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        baseline = tools_fingerprint()
        monkeypatch.setattr(tools_module, "TOOLS", tools_module.TOOLS[:-1])
        assert tools_fingerprint() != baseline
        monkeypatch.undo()
        assert tools_fingerprint() == baseline


class TestD15:
    """The catalogue's *absences* are the enforcement, so they are asserted directly."""

    def test_no_tool_ranks_scores_or_estimates_on_demand(self) -> None:
        forbidden = ("rank_", "score_", "estimate_", "simulate", "evaluate_", "recommend")
        for name in TOOL_NAMES:
            assert not any(fragment in name for fragment in forbidden), name

    def test_no_tool_writes(self) -> None:
        forbidden = ("set_", "update_", "create_", "delete_", "write_", "record_", "save_")
        for name in TOOL_NAMES:
            assert not any(name.startswith(fragment) for fragment in forbidden), name

    def test_no_tool_fetches(self) -> None:
        forbidden = ("fetch", "refresh", "sync", "download")
        for name in TOOL_NAMES:
            assert not any(fragment in name for fragment in forbidden), name

    def test_the_price_tool_says_it_reads_the_cache_only(self) -> None:
        price = next(spec for spec in TOOLS if spec.name == "get_item_price")
        assert "never triggers a request" in price.description
