"""§22.4's loop and §22.3's breakpoints, driven over a scripted transport.

The transport is stateful and replies from a queue, so one test can drive a genuine multi-turn
conversation: ask → tool_use → two parallel tool_use → final answer. Every request body is
recorded, and most assertions here are about **what was sent** rather than what came back —
because the expensive mistakes in this module are all send-side. A misplaced cache breakpoint,
a dropped ``tool_use_id``, a tool list rebuilt in a new order: none of them raises, none of them
produces a wrong answer, and all of them show up only on an invoice.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tracker.advisor.prompt import AdvisorPrompt, ConversationTurn, build_prompt
from tracker.advisor.tools import TOOLS
from tracker.config.settings import LlmSettings
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.llm.anthropic_advisor import AnthropicAdvisorProvider
from tracker.integrations.llm.types import (
    LlmRateLimited,
    LlmRefused,
    LlmUnavailable,
    ToolCall,
    ToolResult,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _body(
    *,
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage
        or {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _answer(text: str = "Bring a whip.", uncertain: list[str] | None = None) -> dict[str, Any]:
    """A final turn. Structured output arrives as a text block of JSON the SDK parses."""
    payload = {"answer": text, "uncertain": uncertain or []}
    return _body(content=[{"type": "text", "text": json.dumps(payload)}])


def _tool_use(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments}


class _Script:
    """Replies from a queue and records every request body."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        if not self._replies:
            raise AssertionError("the provider made more requests than the script allows")
        return httpx.Response(200, json=self._replies.pop(0))


def _provider(
    script: _Script | Callable[[httpx.Request], httpx.Response],
    *,
    breaker: CircuitBreaker | None = None,
    **advisor: Any,
) -> AnthropicAdvisorProvider:
    # `max_retries=0` because the SDK's own backoff is not what these tests are about, and
    # leaving it at the default spends a minute of wall clock sleeping through the 429 and 5xx
    # cases. Retry behaviour belongs to the SDK; the taxonomy below is what this module owns.
    settings = LlmSettings(enabled=True, max_retries=0, advisor={"enabled": True, **advisor})
    return AnthropicAdvisorProvider(
        settings,
        api_key="test-key",
        transport=httpx.MockTransport(script),
        breaker=breaker,
        clock=lambda: NOW,
    )


def _prompt(**overrides: Any) -> AdvisorPrompt:
    defaults: dict[str, Any] = {
        "digest": "# Account\n\n- Account type: unknown",
        "question": "what should I bring to crocodiles?",
        "tools_fingerprint": "fp",
    }
    defaults.update(overrides)
    return build_prompt(**defaults)


def _echo(call: ToolCall) -> ToolResult:
    return ToolResult(call_id=call.call_id, content=f"result for {call.name}")


def _blocks(message: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict) and block.get("type") == kind]


@pytest.fixture
def script() -> _Script:
    """ask → one tool → two parallel tools → answer."""
    return _Script(
        [
            _body(
                content=[_tool_use("t1", "get_skill_detail", {"skill_id": "slayer"})],
                stop_reason="tool_use",
            ),
            _body(
                content=[
                    _tool_use("t2", "list_training_methods", {"skill_id": "slayer"}),
                    _tool_use("t3", "get_item_price", {"item_ids": [4151]}),
                ],
                stop_reason="tool_use",
            ),
            _answer("Bring a whip.", ["crocodile spawns are from my own knowledge"]),
        ]
    )


def _converse(provider: AnthropicAdvisorProvider, prompt: AdvisorPrompt | None = None) -> Any:
    return provider.converse(
        prompt if prompt is not None else _prompt(),
        TOOLS,
        _echo,
        max_iterations=6,
        max_tool_calls=10,
    )


class TestTheLoop:
    def test_it_runs_to_a_final_answer(self, script: _Script) -> None:
        turn = _converse(_provider(script))
        assert turn.answer == "Bring a whip."
        assert turn.uncertain == ("crocodile spawns are from my own knowledge",)
        assert turn.iterations == 3
        assert len(script.requests) == 3

    def test_every_tool_call_is_traced(self, script: _Script) -> None:
        turn = _converse(_provider(script))
        assert [entry.name for entry in turn.tool_trace] == [
            "get_skill_detail",
            "list_training_methods",
            "get_item_price",
        ]
        assert all(entry.result_chars > 0 for entry in turn.tool_trace)

    def test_the_trace_carries_no_tool_output(self, script: _Script) -> None:
        """D16 — sizes and arguments survive the turn; results do not."""
        turn = _converse(_provider(script))
        for entry in turn.tool_trace:
            assert not hasattr(entry, "content")
            assert "result for" not in json.dumps(dict(entry.arguments))

    def test_parallel_calls_return_in_one_user_message(self, script: _Script) -> None:
        """Splitting them would train the model out of the cheaper parallel pattern."""
        _converse(_provider(script))
        third = script.requests[2]["messages"]
        assert len([m for m in third if len(_blocks(m, "tool_result")) == 2]) == 1
        assert sum(len(_blocks(m, "tool_result")) for m in third) == 3

    def test_every_tool_result_carries_its_matching_id(self, script: _Script) -> None:
        _converse(_provider(script))
        sent = {
            block["tool_use_id"]
            for request in script.requests
            for message in request["messages"]
            for block in _blocks(message, "tool_result")
        }
        assert sent == {"t1", "t2", "t3"}

    def test_the_transcript_always_ends_on_a_user_turn(self, script: _Script) -> None:
        """A transcript ending on an assistant message is rejected by the API."""
        _converse(_provider(script))
        for request in script.requests:
            assert request["messages"][-1]["role"] == "user"

    def test_usage_is_summed_across_every_request(self, script: _Script) -> None:
        """Per-request counts would understate a tool-using turn severalfold."""
        turn = _converse(_provider(script))
        assert turn.input_tokens == 300
        assert turn.output_tokens == 60


class TestCaching:
    def test_the_system_block_is_split_in_two_with_a_breakpoint_on_each(self) -> None:
        script = _Script([_answer()])
        _converse(_provider(script))
        system = script.requests[0]["system"]
        assert len(system) == 2
        assert all(block["cache_control"] == {"type": "ephemeral"} for block in system)

    def test_the_instructions_precede_the_digest(self) -> None:
        """Reversed, a sync would invalidate the instruction block as well."""
        script = _Script([_answer()])
        prompt = _prompt(digest="# Account\n\n- Combat level: 90")
        _converse(_provider(script), prompt)
        system = script.requests[0]["system"]
        assert system[0]["text"] == prompt.system
        assert system[1]["text"] == prompt.digest

    def test_the_newest_question_carries_the_rolling_breakpoint(self) -> None:
        script = _Script([_answer()])
        _converse(_provider(script))
        last = script.requests[0]["messages"][-1]
        assert last["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_no_breakpoint_is_placed_on_a_tool_result(self, script: _Script) -> None:
        """Tool traffic is discarded at the end of the turn (D16); caching it pays for nothing."""
        _converse(_provider(script))
        for request in script.requests:
            for message in request["messages"]:
                for block in _blocks(message, "tool_result"):
                    assert "cache_control" not in block

    def test_tools_are_sent_in_catalogue_order(self) -> None:
        script = _Script([_answer()])
        _converse(_provider(script))
        sent = [tool["name"] for tool in script.requests[0]["tools"]]
        assert sent == [spec.name for spec in TOOLS]
        assert sent == sorted(sent)

    def test_the_prefix_bytes_are_identical_across_a_conversations_turns(
        self, script: _Script
    ) -> None:
        """The whole point of the split. If this drifts, nothing caches."""
        _converse(_provider(script))
        prefixes = {
            json.dumps([request["system"], request["tools"]], sort_keys=True)
            for request in script.requests
        }
        assert len(prefixes) == 1

    def test_history_is_replayed_before_the_new_question(self) -> None:
        script = _Script([_answer()])
        prompt = _prompt(
            history=(
                ConversationTurn(role="user", text="first question"),
                ConversationTurn(role="assistant", text="first answer"),
            )
        )
        _converse(_provider(script), prompt)
        messages = script.requests[0]["messages"]
        assert messages[0]["content"] == "first question"
        assert messages[1]["content"] == "first answer"
        assert messages[2]["content"][0]["text"] == "what should I bring to crocodiles?"

    def test_a_changed_digest_appends_an_operator_note_last(self) -> None:
        """§22.3 — mid-conversation invalidation, and it must be the final message."""
        script = _Script([_answer()])
        _converse(_provider(script), _prompt(digest_changed=True))
        messages = script.requests[0]["messages"]
        assert messages[-1]["role"] == "system"
        assert "has been refreshed" in messages[-1]["content"]

    def test_an_unchanged_digest_appends_no_note(self) -> None:
        script = _Script([_answer()])
        _converse(_provider(script))
        assert all(message["role"] != "system" for message in script.requests[0]["messages"])


class TestRequestShape:
    def test_no_rejected_parameter_is_sent(self) -> None:
        """Each of these is a 400 on this model family, not a degradation."""
        script = _Script([_answer()])
        _converse(_provider(script))
        body = script.requests[0]
        for rejected in ("temperature", "top_p", "top_k", "budget_tokens", "thinking"):
            assert rejected not in body

    def test_effort_and_max_tokens_come_from_the_advisor_settings(self) -> None:
        script = _Script([_answer()])
        _converse(_provider(script, effort="high", max_tokens=4321))
        body = script.requests[0]
        assert body["output_config"]["effort"] == "high"
        assert body["max_tokens"] == 4321


class TestBounds:
    def test_exhausting_the_tool_budget_lets_the_model_finish(self) -> None:
        """Cutting the turn off would discard everything already paid for."""
        script = _Script(
            [
                _body(
                    content=[_tool_use("t1", "get_skill_detail", {"skill_id": "magic"})],
                    stop_reason="tool_use",
                ),
                _answer("Answered without the lookup."),
            ]
        )
        turn = _provider(script).converse(
            _prompt(), TOOLS, _echo, max_iterations=6, max_tool_calls=0
        )
        assert turn.answer == "Answered without the lookup."
        assert turn.tool_trace[0].is_error
        assert turn.tool_trace[0].result_chars == 0
        sent = script.requests[1]["messages"][-1]["content"][0]
        assert "budget for this answer is exhausted" in sent["content"]

    def test_the_tool_budget_counts_across_iterations(self) -> None:
        script = _Script(
            [
                _body(
                    content=[_tool_use("t1", "get_skill_detail", {"skill_id": "magic"})],
                    stop_reason="tool_use",
                ),
                _body(
                    content=[_tool_use("t2", "get_skill_detail", {"skill_id": "slayer"})],
                    stop_reason="tool_use",
                ),
                _answer(),
            ]
        )
        turn = _provider(script).converse(
            _prompt(), TOOLS, _echo, max_iterations=6, max_tool_calls=1
        )
        assert turn.tool_trace[0].is_error is False
        assert turn.tool_trace[1].is_error is True

    @pytest.mark.parametrize("digest_changed", [False, True])
    def test_follow_up_can_include_prose_alongside_a_tool_call(self, digest_changed: bool) -> None:
        """Tool-call commentary is not the final structured answer."""
        script = _Script(
            [
                _body(
                    content=[
                        {"type": "text", "text": "Partial thought."},
                        _tool_use("t1", "get_skill_detail", {"skill_id": "magic"}),
                    ],
                    stop_reason="tool_use",
                ),
                _answer("Train Magic next.", ["Check the current costs."]),
            ]
        )
        breaker = CircuitBreaker()
        prompt = _prompt(
            history=(
                ConversationTurn(role="user", text="What should I train?"),
                ConversationTurn(role="assistant", text="Consider Magic."),
            ),
            question="Why that skill?",
            digest_changed=digest_changed,
        )
        turn = _converse(_provider(script, breaker=breaker), prompt)
        assert turn.answer == "Train Magic next."
        assert turn.uncertain == ("Check the current costs.",)
        assert len(turn.tool_trace) == 1
        assert turn.iterations == 2
        echoed = script.requests[1]["messages"][-2]["content"]
        assert echoed[0]["text"] == "Partial thought."
        assert echoed[1]["id"] == "t1"
        result = script.requests[1]["messages"][-1]["content"][0]
        assert result["tool_use_id"] == "t1"
        assert script.requests[0]["output_config"]["format"]["type"] == "json_schema"
        assert not breaker.is_open

    def test_invalid_final_answer_is_logged_without_response_content(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        script = _Script([_body(content=[{"type": "text", "text": "private response"}])])
        with pytest.raises(LlmUnavailable, match="expected schema"):
            _converse(_provider(script))
        assert "invalid final answer" in caplog.text
        assert "private response" not in caplog.text

    def test_exhausting_iterations_with_no_answer_is_unavailable(self) -> None:
        """A caller told 'success, here is an empty string' would store the empty string."""
        script = _Script(
            [
                _body(
                    content=[_tool_use("t1", "get_skill_detail", {"skill_id": "magic"})],
                    stop_reason="tool_use",
                )
            ]
        )
        with pytest.raises(LlmUnavailable, match="did not finish within 1 steps"):
            _provider(script).converse(_prompt(), TOOLS, _echo, max_iterations=1, max_tool_calls=10)


class TestFailures:
    def test_a_refusal_is_refused_and_counts_as_a_successful_call(self) -> None:
        """The provider was reachable, so the breaker must not open on it (§21.4)."""
        breaker = CircuitBreaker()
        script = _Script([_body(content=[], stop_reason="refusal")])
        with pytest.raises(LlmRefused):
            _converse(_provider(script, breaker=breaker))
        assert not breaker.is_open

    def test_a_429_is_rate_limited_with_its_retry_after(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "30"}, json={"error": {}})

        with pytest.raises(LlmRateLimited) as raised:
            _converse(_provider(handler))
        assert raised.value.retry_after == 30.0

    def test_a_500_is_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": {}})

        with pytest.raises(LlmUnavailable):
            _converse(_provider(handler))

    def test_provider_failure_logs_status_and_request_id_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                headers={"request-id": "req_diagnostic"},
                json={"error": {"message": "private account detail"}},
            )

        with pytest.raises(LlmUnavailable):
            _converse(_provider(handler))
        assert "status=400" in caplog.text
        assert "req_diagnostic" in caplog.text
        assert "private account detail" not in caplog.text
        assert "test-key" not in caplog.text

    def test_a_connection_error_is_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(LlmUnavailable):
            _converse(_provider(handler))

    def test_an_open_breaker_short_circuits_without_a_request(self) -> None:
        breaker = CircuitBreaker()
        for _ in range(20):
            breaker.record_failure()
        script = _Script([])
        with pytest.raises(LlmUnavailable, match="cooldown"):
            _converse(_provider(script, breaker=breaker))
        assert script.requests == []
