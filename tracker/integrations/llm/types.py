"""The vendor-neutral half of §21.4: what a guidance provider is, and how it fails.

Nothing in this module imports a provider SDK, and that is the point. Everything upstream —
:mod:`tracker.sync.guidance`, the UI's error handling, the stored note — is written against
these types, so swapping or adding a vendor is a new module under this package plus one
branch in :mod:`tracker.integrations.llm.factory`, with no edit above this line.

The failure taxonomy is three-way because the caller genuinely acts differently on each:

* :class:`LlmUnavailable` — nobody answered. Try later; the recommendation is unaffected.
* :class:`LlmRateLimited` — answered, and said *not now*, sometimes with a delay to honour.
* :class:`LlmRefused` — answered, and declined. Retrying the same request will not help.

Collapsing the third into the first would have the UI tell a user to try again at something
that will never succeed, which is worse than the failure itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from tracker.advisor.prompt import AdvisorPrompt
from tracker.guidance.prompt import GuidancePrompt


class LlmUnavailable(RuntimeError):
    """The provider could not be reached, or answered with a server error.

    Also raised when §7.5's circuit breaker is open: a sustained outage should stop the
    application asking, and from the caller's side "we did not ask" and "we asked and got
    nothing" are the same fact.
    """


class LlmRateLimited(LlmUnavailable):
    """The provider declined for volume. A subclass because it *is* a form of unavailable.

    A caller that only wants to know "did this work" catches :class:`LlmUnavailable` and is
    correct; one that wants to say *"try again in 30 seconds"* catches this first and reads
    :attr:`retry_after`.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LlmRefused(RuntimeError):
    """The provider answered and declined to write the guidance.

    Deliberately **not** a subclass of :class:`LlmUnavailable`: the provider was reachable
    and the request was well-formed, so every retry-shaped remedy is wrong. §7.5's breaker
    counts this as a success for the same reason.
    """

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True, slots=True)
class GuidanceStep:
    """One ordered action. ``order`` is 1-based and assigned by the provider adapter."""

    order: int
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class GuidanceDTO:
    """One generated answer, in the shape §21.3 asked for.

    ``warnings`` and ``uncertain`` are separate fields rather than one list because they are
    different sentences with different remedies — *"this will get you killed"* is acted on,
    *"this method may no longer exist"* is verified. §15's honesty discipline needs the UI to
    be able to mark the second as a hedge, which it cannot do if it arrives as prose.

    ``estimated_session_minutes`` is the model's, and is never merged with §8's hours (D14).

    The token counts are carried so the stored note can answer *"what did this cost"* without
    a second call. ``cache_read_input_tokens`` is the one worth watching: if it stays zero
    across requests, §21.3's stable prefix has stopped being stable.
    """

    summary: str
    prerequisites: tuple[str, ...]
    steps: tuple[GuidanceStep, ...]
    warnings: tuple[str, ...]
    estimated_session_minutes: int | None
    uncertain: tuple[str, ...]
    model: str
    generated_at: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


@runtime_checkable
class GuidanceProvider(Protocol):
    """What §21.4 requires of a vendor adapter. One method, plus a lifecycle.

    ``runtime_checkable`` so a test double can be asserted against the protocol rather than
    only against the call that happens to be exercised.
    """

    @property
    def model(self) -> str:
        """The model identity to record on the note, for provenance (§15)."""

    def generate(self, prompt: GuidancePrompt) -> GuidanceDTO:
        """Ask for guidance, or raise one of the three failures above."""

    def close(self) -> None:
        """Release the underlying connection pool."""


# ---------------------------------------------------------------------------
# §22.5 — the advisor's protocol, sharing this module's failure taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool, described in terms no vendor owns (§22.4).

    ``input_schema`` is plain JSON Schema, which every plausible provider accepts in some
    wrapper; the adapter is the only thing that knows the wire key names. Keeping it a
    ``Mapping`` rather than a Pydantic model is deliberate — these are declarations, not
    validated payloads, and the validation that matters happens on the *call* in
    :mod:`tracker.advisor.dispatch`.
    """

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One request from the model. ``call_id`` is the provider's, and is echoed back verbatim."""

    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One answer to a :class:`ToolCall`.

    ``is_error`` is not an exception channel — it is a *conversational* one. A malformed
    argument or an unknown id is something the model can see and correct on the next iteration,
    and raising instead would convert a recoverable mistake into a failed turn (§22.4).
    """

    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolTraceEntry:
    """What is remembered about a tool call once the turn is over.

    The result itself is deliberately absent — **D16**. What survives is enough to tell the user
    which lookups an answer rests on (§22.8) and enough to audit cost, and nothing that could be
    re-sent as though it were still true.
    """

    name: str
    arguments: Mapping[str, Any]
    result_chars: int
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class AdvisorTurn:
    """One completed answer, however many model round trips it took.

    ``uncertain`` is separate from ``answer`` for the reason :class:`GuidanceDTO` separates
    ``uncertain`` from ``warnings``: §15 requires the interface to mark a hedge *as* a hedge,
    which it cannot do if the hedge arrives as a sentence inside a paragraph.

    ``iterations`` and ``tool_trace`` are carried because a turn's cost is not visible from the
    token counts alone — six iterations at one tool each is a different bill from one iteration,
    and only this DTO knows which happened.
    """

    answer: str
    uncertain: tuple[str, ...] = ()
    tool_trace: tuple[ToolTraceEntry, ...] = ()
    model: str = ""
    generated_at: datetime | None = None
    stop_reason: str = ""
    iterations: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def truncated(self) -> bool:
        """The provider stopped on its output ceiling rather than because it was finished."""
        return self.stop_reason == "max_tokens"


@runtime_checkable
class AdvisorProvider(Protocol):
    """What §22.5 requires of a vendor adapter.

    ``execute`` is passed in rather than being a method on the provider, and the loop runs
    inside the implementation rather than in the caller. Both follow from the same fact: the
    transcript a tool loop maintains is vendor-shaped, and hoisting it into
    :mod:`tracker.sync.advisor` would make the orchestration layer aware of provider message
    blocks — the exact coupling this module exists to prevent. The bounds come in as arguments
    and the whole trace comes back in the DTO, so the *policy* still belongs to the service.
    """

    @property
    def model(self) -> str:
        """The model identity to record on the message, for provenance (§15, §22.8)."""

    def converse(
        self,
        prompt: AdvisorPrompt,
        tools: Sequence[ToolSpec],
        execute: Callable[[ToolCall], ToolResult],
        *,
        max_iterations: int,
        max_tool_calls: int,
    ) -> AdvisorTurn:
        """Answer one question, or raise one of this module's three failures."""

    def close(self) -> None:
        """Release the underlying connection pool."""
