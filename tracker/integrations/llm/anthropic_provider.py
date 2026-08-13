"""The Anthropic implementation of §21.4's provider protocol.

Three decisions here depart from what the rest of ``tracker/integrations/`` does, and each
is deliberate:

**No** :func:`tracker.integrations.http.get_with_retry`. The SDK already retries 429s and
5xx with backoff. Layering §7.5's three-attempt schedule on top would produce up to nine
requests and thirty seconds of sleeping behind a single button press. What *is* reused is
:class:`~tracker.integrations.http.CircuitBreaker`, which is transport-agnostic and supplies
the part the SDK does not: after a sustained outage, stop asking.

**No streaming.** The answer is a bounded structured object at a few thousand tokens, an
order of magnitude below the size where a non-streaming request risks an HTTP timeout.
Streaming would buy nothing and would cost the test suite its simplest possible double — one
JSON body instead of a hand-assembled event stream.

**Structured output, not markdown.** §15's layering is ``read_model -> frozen rows ->
renderer``, and a prose blob has no row type. Separate ``warnings`` and ``uncertain`` fields
are also what let the UI mark a hedge *as* a hedge instead of burying it in a paragraph.

The request shape is constrained by the model, and each constraint below is a 400 rather than
a degradation, so they are asserted in ``tests/integrations/llm/`` rather than trusted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import anthropic
import httpx
from anthropic import DefaultHttpxClient
from pydantic import BaseModel, Field

from tracker.config.settings import LlmSettings
from tracker.guidance.prompt import GuidancePrompt
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.llm.types import (
    GuidanceDTO,
    GuidanceStep,
    LlmRateLimited,
    LlmRefused,
    LlmUnavailable,
)


class GuidanceStepModel(BaseModel):
    """One step, as the provider returns it. ``order`` is assigned on the way out."""

    title: str
    detail: str


class GuidanceResponseModel(BaseModel):
    """The structured-output schema. Mirrors §21.3's "What to produce" list exactly.

    Every list defaults to empty rather than being required: a task with no prerequisites and
    nothing to warn about is a real answer, and forcing the model to populate a field it has
    nothing for is how a schema manufactures filler.
    """

    summary: str
    prerequisites: list[str] = Field(default_factory=list)
    steps: list[GuidanceStepModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    estimated_session_minutes: int | None = None
    uncertain: list[str] = Field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AnthropicGuidanceProvider:
    """§21.4's provider protocol, over the Anthropic Messages API.

    ``transport`` is the test seam, and it is the *same* seam the rest of this package uses:
    the SDK accepts an ``http_client``, and ``DefaultHttpxClient`` is an ``httpx.Client``
    subclass that forwards ``transport=``, so ``httpx.MockTransport`` works here exactly as it
    does in ``tracker/integrations/prices/client.py``. No monkeypatching, no SDK-specific
    mocking library, and the tests read like their neighbours.
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
        self._clock = clock
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            http_client=DefaultHttpxClient(transport=transport) if transport else None,
        )

    @property
    def model(self) -> str:
        return self._settings.model

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AnthropicGuidanceProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def generate(self, prompt: GuidancePrompt) -> GuidanceDTO:
        """One request, one answer, or one of §21.4's three failures."""
        if self._breaker.is_open:
            raise LlmUnavailable(
                "the guidance provider is in a failure cooldown (§7.5); not asking again yet"
            )

        try:
            response = self._client.messages.parse(
                model=self._settings.model,
                max_tokens=self._settings.max_tokens,
                # Depth is set here, not with a thinking-token budget: `budget_tokens` is
                # rejected outright by this model family, and `max_tokens` above caps
                # reasoning and answer together.
                output_config={"effort": self._settings.effort},
                # The cache breakpoint. Everything before it is §21.3's module constant;
                # everything after it is this account. Reversing the two would cost real
                # money and raise nothing.
                system=[
                    {
                        "type": "text",
                        "text": prompt.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt.user}],
                output_format=GuidanceResponseModel,
            )
        except anthropic.RateLimitError as exc:
            self._breaker.record_failure()
            raise LlmRateLimited(
                "the guidance provider is rate limiting this account",
                retry_after=_retry_after(exc),
            ) from exc
        except anthropic.APIConnectionError as exc:
            self._breaker.record_failure()
            raise LlmUnavailable(f"could not reach the guidance provider: {exc}") from exc
        except anthropic.APIStatusError as exc:
            self._breaker.record_failure()
            raise LlmUnavailable(f"the guidance provider returned {exc.status_code}") from exc

        # Checked before anything reads the content: on a refusal there is nothing to read,
        # and an unconditional `content[0]` here is the whole bug this ordering avoids.
        if response.stop_reason == "refusal":
            # A refusal is a *successful* call for breaker purposes — the provider answered.
            self._breaker.record_success()
            raise LlmRefused(
                "the guidance provider declined to answer this request",
                category=_refusal_category(response),
            )

        self._breaker.record_success()
        return _to_dto(
            response.parsed_output,
            model=self._settings.model,
            generated_at=self._clock(),
            usage=getattr(response, "usage", None),
        )


def _to_dto(
    parsed: GuidanceResponseModel | None,
    *,
    model: str,
    generated_at: datetime,
    usage: object | None,
) -> GuidanceDTO:
    """Convert the validated response into the vendor-neutral DTO.

    A ``None`` ``parsed_output`` is treated as unavailable rather than as an empty answer:
    structured output was requested, so its absence means the turn did not produce one, and
    storing an empty note would cache that non-answer for a week (§21.5).
    """
    if parsed is None:
        raise LlmUnavailable("the guidance provider returned no structured output")

    return GuidanceDTO(
        summary=parsed.summary,
        prerequisites=tuple(parsed.prerequisites),
        steps=tuple(
            GuidanceStep(order=index, title=step.title, detail=step.detail)
            for index, step in enumerate(parsed.steps, start=1)
        ),
        warnings=tuple(parsed.warnings),
        estimated_session_minutes=parsed.estimated_session_minutes,
        uncertain=tuple(parsed.uncertain),
        model=model,
        generated_at=generated_at,
        input_tokens=_usage_field(usage, "input_tokens"),
        output_tokens=_usage_field(usage, "output_tokens"),
        cache_read_input_tokens=_usage_field(usage, "cache_read_input_tokens"),
    )


def _usage_field(usage: object | None, name: str) -> int:
    """Read one token count, tolerating its absence.

    Token accounting is observability, not correctness — a provider or SDK version that omits
    a field should cost the note its cost figure, never the advice.
    """
    value = getattr(usage, name, None)
    return int(value) if isinstance(value, int) else 0


def _refusal_category(response: object) -> str | None:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    return str(category) if category is not None else None


def _retry_after(exc: anthropic.RateLimitError) -> float | None:
    """The provider's own advice on when to come back, if it gave any."""
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
        # A `Retry-After` may be an HTTP date rather than seconds. Parsing that would be
        # precision nobody uses: the caller's fallback is the configured minimum interval.
        return None
