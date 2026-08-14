"""§21.4 — the request is the one the model accepts, and every failure has its own name.

Two groups, and they fail differently.

The **request-shape** assertions guard against 400s that no unit test would otherwise reach:
`temperature`, `top_p`, `top_k` and `budget_tokens` are all rejected outright by this model
family, and an assistant-turn prefill is too. None of these are things the code does today;
they are things a later edit would add without knowing, and the request body is the only
place that knowledge lives.

The **failure-taxonomy** assertions guard §21.4's three-way split. Merging refusal into
unavailable is the tempting simplification, and it produces a UI that tells the user to try
again at something that will never succeed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from tracker.config.settings import LlmSettings
from tracker.guidance.prompt import GuidancePrompt
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.llm import build_provider
from tracker.integrations.llm.anthropic_provider import AnthropicGuidanceProvider
from tracker.integrations.llm.types import (
    GuidanceProvider,
    LlmRateLimited,
    LlmRefused,
    LlmUnavailable,
)

REFUSAL_BODY: dict[str, Any] = {
    "id": "msg_refusal",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-5",
    "content": [],
    "stop_reason": "refusal",
    "stop_sequence": None,
    "usage": {"input_tokens": 1200, "output_tokens": 0},
}


def make_provider(
    settings: LlmSettings,
    transport: httpx.BaseTransport,
    *,
    api_key: str = "test-key",
    breaker: CircuitBreaker | None = None,
    now: datetime | None = None,
) -> AnthropicGuidanceProvider:
    extra: dict[str, Any] = {} if now is None else {"clock": lambda: now}
    return AnthropicGuidanceProvider(
        settings, api_key=api_key, transport=transport, breaker=breaker, **extra
    )


class TestRequestShape:
    """What goes on the wire. Each assertion here names a 400 someone could reintroduce."""

    def test_the_configured_model_and_effort_are_sent(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        transport, seen = recording_transport(answer_body())
        settings = llm_settings(effort="xhigh")

        with make_provider(settings, transport) as provider:
            provider.generate(prompt)

        assert seen[0]["model"] == "claude-opus-5"
        assert seen[0]["output_config"]["effort"] == "xhigh"

    @pytest.mark.parametrize(
        "rejected", ["temperature", "top_p", "top_k", "budget_tokens", "thinking"]
    )
    def test_no_rejected_parameter_is_sent(
        self,
        rejected: str,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """Sampling parameters and a thinking budget are 400s on this model family.

        ``thinking`` is checked as a whole because the accepted form is *omission*: thinking
        is on by default, and the only thing that can be spelled here is a rejected one.
        """
        transport, seen = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            provider.generate(prompt)

        assert rejected not in json.dumps(seen[0])

    def test_the_cache_breakpoint_is_on_the_last_system_block(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """§21.3's whole cost argument. Silent when wrong; visible only on a bill."""
        transport, seen = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            provider.generate(prompt)

        system = seen[0]["system"]
        assert system[-1]["cache_control"] == {"type": "ephemeral"}
        assert system[-1]["text"] == prompt.system

    def test_no_message_block_carries_a_cache_breakpoint(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """Caching the volatile half writes a fresh entry per account and reads none."""
        transport, seen = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            provider.generate(prompt)

        assert "cache_control" not in json.dumps(seen[0]["messages"])

    def test_the_conversation_ends_on_the_user_turn(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """An assistant prefill is rejected by this model family."""
        transport, seen = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            provider.generate(prompt)

        messages = seen[0]["messages"]
        assert [message["role"] for message in messages] == ["user"]
        assert messages[0]["content"] == prompt.user

    def test_structured_output_is_requested(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        transport, seen = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            provider.generate(prompt)

        schema = seen[0]["output_config"]["format"]
        assert schema["type"] == "json_schema"
        assert set(schema["schema"]["properties"]) == {
            "summary",
            "prerequisites",
            "steps",
            "warnings",
            "estimated_session_minutes",
            "uncertain",
        }


class TestSuccessfulAnswer:
    def test_the_answer_becomes_a_dto_with_ordered_steps(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
        now: datetime,
    ) -> None:
        transport, _ = recording_transport(answer_body())

        with make_provider(llm_settings(), transport, now=now) as provider:
            dto = provider.generate(prompt)

        assert dto.summary == "Get a task from Turael and kill it."
        assert [step.order for step in dto.steps] == [1, 2]
        assert dto.steps[0].title == "Travel to Burthorpe"
        assert dto.model == "claude-opus-5"
        assert dto.generated_at == now

    def test_warnings_and_uncertainty_stay_separate(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """§15 — a hedge and a hazard are different sentences with different remedies."""
        transport, _ = recording_transport(
            answer_body(
                warnings=["The Wilderness section is dangerous."],
                uncertain=["Turael's task list may have changed."],
            )
        )

        with make_provider(llm_settings(), transport) as provider:
            dto = provider.generate(prompt)

        assert dto.warnings == ("The Wilderness section is dangerous.",)
        assert dto.uncertain == ("Turael's task list may have changed.",)

    def test_token_counts_are_carried_for_cost_visibility(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """``cache_read_input_tokens`` staying zero is how a broken prefix announces itself."""
        transport, _ = recording_transport(answer_body())

        with make_provider(llm_settings(), transport) as provider:
            dto = provider.generate(prompt)

        assert (dto.input_tokens, dto.output_tokens) == (1200, 400)
        assert dto.cache_read_input_tokens == 900

    def test_an_answer_with_nothing_to_warn_about_is_still_an_answer(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        answer_body: Callable[..., dict[str, Any]],
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """Empty lists are legitimate; requiring them is how a schema manufactures filler."""
        transport, _ = recording_transport(
            answer_body(
                prerequisites=[],
                warnings=[],
                uncertain=[],
                estimated_session_minutes=None,
            )
        )

        with make_provider(llm_settings(), transport) as provider:
            dto = provider.generate(prompt)

        assert dto.prerequisites == ()
        assert dto.warnings == ()
        assert dto.estimated_session_minutes is None


class TestFailureTaxonomy:
    def test_a_refusal_is_raised_rather_than_read_as_an_empty_answer(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """The provider answered and declined. Content is empty; reading it would crash."""
        transport, _ = recording_transport(REFUSAL_BODY)

        with (
            make_provider(llm_settings(), transport) as provider,
            pytest.raises(LlmRefused),
        ):
            provider.generate(prompt)

    def test_a_refusal_is_not_an_unavailability(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """Merging the two would have the UI advise a retry that cannot succeed."""
        transport, _ = recording_transport(REFUSAL_BODY)

        with (
            make_provider(llm_settings(), transport) as provider,
            pytest.raises(LlmRefused) as caught,
        ):
            provider.generate(prompt)

        assert not isinstance(caught.value, LlmUnavailable)

    def test_a_429_is_rate_limited_and_carries_the_providers_own_advice(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        transport, _ = recording_transport(
            {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
            status=429,
            headers={"retry-after": "42"},
        )

        with (
            make_provider(llm_settings(), transport) as provider,
            pytest.raises(LlmRateLimited) as caught,
        ):
            provider.generate(prompt)

        assert caught.value.retry_after == 42.0

    def test_a_rate_limit_is_still_catchable_as_unavailable(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """A caller that only wants "did this work" should not have to know about volume."""
        transport, _ = recording_transport(
            {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
            status=429,
        )

        with (
            make_provider(llm_settings(), transport) as provider,
            pytest.raises(LlmUnavailable),
        ):
            provider.generate(prompt)

    def test_a_server_error_is_unavailable(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        transport, _ = recording_transport(
            {"type": "error", "error": {"type": "api_error", "message": "boom"}}, status=500
        )

        with (
            make_provider(llm_settings(), transport) as provider,
            pytest.raises(LlmUnavailable),
        ):
            provider.generate(prompt)

    def test_a_connection_failure_is_unavailable(
        self, llm_settings: Callable[..., LlmSettings], prompt: GuidancePrompt
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with (
            make_provider(llm_settings(), httpx.MockTransport(handler)) as provider,
            pytest.raises(LlmUnavailable),
        ):
            provider.generate(prompt)


class TestCircuitBreaker:
    def test_a_sustained_outage_stops_the_application_asking(
        self, llm_settings: Callable[..., LlmSettings], prompt: GuidancePrompt
    ) -> None:
        """§7.5's reason for a breaker: retries absorb a blip, not an outage."""
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("down")

        breaker = CircuitBreaker(failure_threshold=3)
        with make_provider(
            llm_settings(), httpx.MockTransport(handler), breaker=breaker
        ) as provider:
            for _ in range(3):
                with pytest.raises(LlmUnavailable):
                    provider.generate(prompt)

            assert attempts == 3

            # The fourth call must not reach the transport at all.
            with pytest.raises(LlmUnavailable):
                provider.generate(prompt)

        assert attempts == 3

    def test_a_refusal_does_not_trip_the_breaker(
        self,
        llm_settings: Callable[..., LlmSettings],
        prompt: GuidancePrompt,
        recording_transport: Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]],
    ) -> None:
        """The provider was reachable. Counting a refusal as an outage would blind the app."""
        transport, seen = recording_transport(REFUSAL_BODY)
        breaker = CircuitBreaker(failure_threshold=3)

        with make_provider(llm_settings(), transport, breaker=breaker) as provider:
            for _ in range(4):
                with pytest.raises(LlmRefused):
                    provider.generate(prompt)

        assert breaker.is_open is False
        assert len(seen) == 4


class TestFactory:
    def test_a_disabled_feature_builds_no_provider(
        self, llm_settings: Callable[..., LlmSettings]
    ) -> None:
        assert build_provider(llm_settings(enabled=False), api_key="test-key") is None

    def test_a_missing_key_builds_no_provider(
        self, llm_settings: Callable[..., LlmSettings]
    ) -> None:
        """D14's promise, made structural: with no key there is no object to call."""
        assert build_provider(llm_settings(enabled=True), api_key=None) is None
        assert build_provider(llm_settings(enabled=True), api_key="") is None

    def test_an_enabled_and_keyed_feature_builds_the_configured_provider(
        self, llm_settings: Callable[..., LlmSettings]
    ) -> None:
        provider = build_provider(llm_settings(), api_key="test-key")

        assert isinstance(provider, AnthropicGuidanceProvider)
        assert isinstance(provider, GuidanceProvider)
        assert provider.model == "claude-opus-5"
        provider.close()
