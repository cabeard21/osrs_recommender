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

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

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
