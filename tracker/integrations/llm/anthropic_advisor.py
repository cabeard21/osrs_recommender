"""§22.5's Anthropic adapter, and the bounded tool loop §22.4 specifies.

**The loop lives here, not in the service**, and that is the one structural decision in this
module. A tool loop maintains a transcript of provider-shaped blocks — ``tool_use`` inside an
assistant message, ``tool_result`` inside the following user message, matched by
``tool_use_id`` — and hoisting that into :mod:`tracker.sync.advisor` would make the
orchestration layer aware of one vendor's message format, which is precisely what
:mod:`tracker.integrations.llm.types` exists to prevent. The bounds arrive as arguments and the
full trace leaves in the DTO, so the *policy* still belongs to the service; only the shape stays
here.

Cache breakpoints, in the order they matter (§22.3):

* ``system[0]`` — the instruction constant. Read on every turn of every conversation.
* ``system[1]`` — the account digest. Read on every turn after a conversation's first, and
  crucially still lets ``system[0]`` hit when a sync invalidates it.
* the last content block of the newest user message — rolls forward, so a long thread accrues
  hits incrementally rather than re-sending its history cold each time.

**No breakpoint is ever placed on a tool result.** Tool traffic is discarded at the end of the
turn (D16), so caching it would pay to store bytes that are thrown away moments later.

Request-shape constraints, inherited from :mod:`tracker.integrations.llm.anthropic_provider` and
asserted in tests rather than trusted, because each is a 400 rather than a degradation:
``budget_tokens``, ``temperature``, ``top_p`` and ``top_k`` are all rejected by this model
family, and thinking is on by default — so ``max_tokens`` must leave room for reasoning *and*
the answer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import anthropic
import httpx
from anthropic import DefaultHttpxClient
from pydantic import BaseModel, Field, ValidationError

from tracker.advisor.prompt import AdvisorPrompt
from tracker.config.settings import LlmSettings
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.llm.types import (
    AdvisorTurn,
    LlmRateLimited,
    LlmRefused,
    LlmUnavailable,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolTraceEntry,
)

_log = logging.getLogger(__name__)

#: What the model is told when it has spent the turn's tool budget. Phrased as an instruction to
#: finish rather than as a failure, because the alternative — cutting the turn off — throws away
#: everything already paid for.
_BUDGET_EXHAUSTED = (
    "The tool budget for this answer is exhausted. Answer with what you already have, and say "
    "which parts you could not verify."
)

#: §22.3's mid-conversation invalidation, as an operator note. Appended after the newest question
#: so it lands last in ``messages``, which is where a mid-conversation system turn must sit.
_DIGEST_CHANGED_NOTE = (
    "The account snapshot above has been refreshed since the earlier answers in this "
    "conversation; levels, unlocks or the ranked list may have moved. Earlier answers were "
    "written against the previous snapshot."
)


class AdvisorAnswerModel(BaseModel):
    """§22.3's response schema. Two fields, not six.

    A conversational answer is prose, and a richer schema would manufacture filler — the model
    would populate ``prerequisites`` for a question about which boss to fight next. But
    ``uncertain`` stays separate for :class:`~tracker.integrations.llm.types.GuidanceDTO`'s
    reason: §15 needs the interface to mark a hedge *as* a hedge, and it cannot do that if the
    hedge arrives as a sentence inside a paragraph.
    """

    answer: str
    uncertain: list[str] = Field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _UsageTally:
    """Token counts summed across a turn's several requests.

    Per-request counts would understate a tool-using turn severalfold, and the one worth
    watching — ``cache_read_input_tokens`` — is only meaningful as a total: it is how a reader
    can tell whether §22.3's prefix is actually being reused.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0

    def add(self, usage: object | None) -> None:
        self.input_tokens += _usage_field(usage, "input_tokens")
        self.output_tokens += _usage_field(usage, "output_tokens")
        self.cache_read_input_tokens += _usage_field(usage, "cache_read_input_tokens")
        self.cache_creation_input_tokens += _usage_field(usage, "cache_creation_input_tokens")


class AnthropicAdvisorProvider:
    """§22.5's provider protocol, over the Anthropic Messages API.

    Constructed exactly as
    :class:`~tracker.integrations.llm.anthropic_provider.AnthropicGuidanceProvider` is,
    including the ``transport`` seam, so the tests read like their neighbours. The ``breaker``
    is shared with the guidance provider when both are built: a provider that is down is down
    for both, and two independent breakers would double an outage's blast radius.
    """

    def __init__(
        self,
        settings: LlmSettings,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._settings = settings
        self._advisor = settings.advisor
        self._clock = clock
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=settings.base_url,
            timeout=self._advisor.timeout_seconds,
            max_retries=settings.max_retries,
            http_client=DefaultHttpxClient(transport=transport) if transport else None,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AnthropicAdvisorProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # §22.4's loop
    # ------------------------------------------------------------------

    def converse(
        self,
        prompt: AdvisorPrompt,
        tools: Sequence[ToolSpec],
        execute: Callable[[ToolCall], ToolResult],
        *,
        max_iterations: int,
        max_tool_calls: int,
    ) -> AdvisorTurn:
        """Answer one question, running tools until the model stops asking for them."""
        if self._breaker.is_open:
            _log.warning("Advisor request skipped: provider failure cooldown")
            raise LlmUnavailable(
                "the advisor provider is in a failure cooldown (§7.5); not asking again yet"
            )

        messages = self._opening_messages(prompt)
        wire_tools = [_wire_tool(spec) for spec in tools]
        trace: list[ToolTraceEntry] = []
        usage = _UsageTally()
        spent = 0
        last_text = ""
        stop_reason = ""

        for iteration in range(1, max_iterations + 1):
            response = self._request(prompt, wire_tools, messages)
            usage.add(getattr(response, "usage", None))
            stop_reason = str(getattr(response, "stop_reason", "") or "")

            # Checked before anything reads content: on a refusal there is nothing to read.
            if stop_reason == "refusal":
                # The provider answered, so the breaker counts this a success (§21.4).
                self._breaker.record_success()
                raise LlmRefused("the advisor declined to answer this request")

            self._breaker.record_success()
            blocks = list(getattr(response, "content", ()) or ())
            text = _text_of(blocks)
            if text:
                last_text = text

            calls = _tool_calls(blocks)
            if not calls:
                # Tool-call commentary is ordinary prose. Validate only the final answer,
                # after the tool loop has finished, rather than every incoming text block.
                parsed = None
                if text:
                    try:
                        parsed = AdvisorAnswerModel.model_validate_json(text)
                    except ValidationError as exc:
                        _log.warning(
                            "Advisor response failed: invalid final answer (stop_reason=%s)",
                            stop_reason,
                        )
                        raise LlmUnavailable(
                            "the advisor returned output that did not match the expected schema"
                        ) from exc
                return self._turn(parsed, last_text, trace, usage, stop_reason, iteration)

            # The assistant turn is echoed back verbatim; dropping a `tool_use` block would
            # leave a `tool_result` with nothing to attach to and fail the next request.
            messages.append({"role": "assistant", "content": blocks})

            results = []
            for call in calls:
                if spent >= max_tool_calls:
                    results.append(_error_block(call.call_id, _BUDGET_EXHAUSTED))
                    trace.append(
                        ToolTraceEntry(
                            name=call.name,
                            arguments=call.arguments,
                            result_chars=0,
                            is_error=True,
                        )
                    )
                    continue
                spent += 1
                outcome = execute(call)
                results.append(_result_block(outcome))
                trace.append(
                    ToolTraceEntry(
                        name=call.name,
                        arguments=call.arguments,
                        result_chars=len(outcome.content),
                        is_error=outcome.is_error,
                    )
                )
            # All results in **one** user message. Splitting them across several would train the
            # model out of asking for tools in parallel, which is the cheaper pattern.
            messages.append({"role": "user", "content": results})

        # The loop ran out. Whatever prose exists is worth more than nothing, but silence is not
        # an answer — a caller told "success, here is an empty string" would store it.
        if not last_text:
            _log.warning("Advisor response failed: iteration limit (%s)", max_iterations)
            raise LlmUnavailable(f"the advisor did not finish within {max_iterations} steps")
        return self._turn(None, last_text, trace, usage, stop_reason, max_iterations)

    # ------------------------------------------------------------------
    # Request assembly
    # ------------------------------------------------------------------

    def _opening_messages(self, prompt: AdvisorPrompt) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": turn.role, "content": turn.text} for turn in prompt.history
        ]
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt.question,
                        # The rolling breakpoint: a long thread accrues hits incrementally.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        )
        if prompt.digest_changed:
            # Must follow a user message and be last in `messages`; both hold here.
            messages.append({"role": "system", "content": _DIGEST_CHANGED_NOTE})
        return messages

    def _request(
        self,
        prompt: AdvisorPrompt,
        wire_tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> Any:
        try:
            return self._client.messages.create(
                model=self._settings.model,
                max_tokens=self._advisor.max_tokens,
                output_config={
                    "effort": self._advisor.effort,
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic.transform_schema(
                            AdvisorAnswerModel.model_json_schema()
                        ),
                    },
                },
                system=[
                    {
                        "type": "text",
                        "text": prompt.system,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": prompt.digest,
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                # Cast because the transcript is assembled dynamically: the SDK's parameter
                # types are TypedDicts that only infer from literals, and a turn's messages
                # accumulate `tool_use` and `tool_result` blocks across iterations. The shapes
                # are asserted against a recording transport in `tests/integrations/llm/`,
                # which checks the bytes actually sent rather than the declared type.
                tools=cast("Any", wire_tools),
                messages=cast("Any", messages),
            )
        except anthropic.RateLimitError as exc:
            self._breaker.record_failure()
            _log.warning("Advisor provider rate limited (request_id=%s)", exc.request_id)
            raise LlmRateLimited(
                "the advisor provider is rate limiting this account",
                retry_after=_retry_after(exc),
            ) from exc
        except anthropic.APIConnectionError as exc:
            self._breaker.record_failure()
            _log.warning(
                "Advisor provider connection failed (error=%s, cause=%s)",
                type(exc).__name__,
                type(exc.__cause__).__name__,
            )
            raise LlmUnavailable(f"could not reach the advisor provider: {exc}") from exc
        except anthropic.APIStatusError as exc:
            self._breaker.record_failure()
            # Status and request ID diagnose provider failures without logging account data,
            # credentials, or the raw response body.
            _log.warning(
                "Advisor provider rejected request (status=%s, request_id=%s)",
                exc.status_code,
                exc.request_id,
            )
            raise LlmUnavailable(f"the advisor provider returned {exc.status_code}") from exc

    def _turn(
        self,
        parsed: AdvisorAnswerModel | None,
        fallback_text: str,
        trace: list[ToolTraceEntry],
        usage: _UsageTally,
        stop_reason: str,
        iterations: int,
    ) -> AdvisorTurn:
        """Prefer the structured output; fall back to the prose the model emitted.

        Unlike §21.4, a missing ``parsed_output`` is **not** fatal here. Guidance caches its
        answer for a week, so storing a non-answer is expensive; a conversation turn is read
        once, and prose without a parsed hedge list is a worse answer rather than a wrong one.
        """
        answer = parsed.answer if parsed is not None else fallback_text
        if not answer:
            _log.warning("Advisor response failed: empty answer (stop_reason=%s)", stop_reason)
            raise LlmUnavailable("the advisor returned an empty answer")
        return AdvisorTurn(
            answer=answer,
            uncertain=tuple(parsed.uncertain) if parsed is not None else (),
            tool_trace=tuple(trace),
            model=self._settings.model,
            generated_at=self._clock(),
            stop_reason=stop_reason,
            iterations=iterations,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
        )


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------


def _wire_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": dict(spec.input_schema),
    }


def _tool_calls(blocks: Sequence[Any]) -> list[ToolCall]:
    return [
        ToolCall(
            call_id=str(getattr(block, "id", "")),
            name=str(getattr(block, "name", "")),
            arguments=dict(getattr(block, "input", {}) or {}),
        )
        for block in blocks
        if getattr(block, "type", None) == "tool_use"
    ]


def _text_of(blocks: Sequence[Any]) -> str:
    parts = [
        str(getattr(block, "text", ""))
        for block in blocks
        if getattr(block, "type", None) == "text"
    ]
    return "\n\n".join(part for part in parts if part)


def _result_block(result: ToolResult) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "content": result.content,
    }
    if result.is_error:
        block["is_error"] = True
    return block


def _error_block(call_id: str, message: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": message,
        "is_error": True,
    }


def _usage_field(usage: object | None, name: str) -> int:
    """Read one token count, tolerating its absence — observability, never correctness."""
    value = getattr(usage, name, None)
    return int(value) if isinstance(value, int) else 0


def _retry_after(exc: anthropic.RateLimitError) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # A `Retry-After` may be an HTTP date rather than seconds; the caller's fallback is
        # the configured minimum interval.
        return None
