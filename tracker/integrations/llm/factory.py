"""The one place a vendor is named (§21.4).

Everything above this module talks to
:class:`~tracker.integrations.llm.types.GuidanceProvider`. Everything below it is one
vendor's SDK. Adding a second vendor is a module beside ``anthropic_provider`` plus a branch
here plus a widened ``Literal`` in :class:`~tracker.config.settings.LlmSettings` — and no
edit anywhere else.

Returning ``None`` rather than raising when the feature is off or unkeyed is what makes
"disabled by default" structural rather than a flag someone can forget to check: with no
provider there is no object to call, and D14's promise that a missing key changes nothing
else holds by construction rather than by discipline.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from tracker.config.settings import LlmSettings
from tracker.integrations.http import CircuitBreaker
from tracker.integrations.llm.types import AdvisorProvider, GuidanceProvider


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_provider(
    settings: LlmSettings,
    *,
    api_key: str | None,
    transport: httpx.BaseTransport | None = None,
    breaker: CircuitBreaker | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> GuidanceProvider | None:
    """Construct the configured provider, or ``None`` if the feature cannot run.

    ``None`` for two reasons, and the caller treats them identically because the user-facing
    remedy is the same sentence: the feature is switched off, or nobody has supplied a key.

    The import is function-local so that an install which never enables guidance does not
    pay for the SDK at startup — and, more usefully, so a missing optional dependency
    degrades to a disabled button rather than to an application that will not boot.
    """
    if not settings.enabled or not api_key:
        return None

    if settings.provider == "anthropic":
        from tracker.integrations.llm.anthropic_provider import AnthropicGuidanceProvider

        return AnthropicGuidanceProvider(
            settings,
            api_key=api_key,
            transport=transport,
            breaker=breaker,
            clock=clock,
        )

    # Unreachable while `provider` is a one-member Literal, and deliberately not a silent
    # fallback to the default vendor: a typo in config should stop, not quietly bill someone
    # for a model they did not choose.
    raise ValueError(f"unknown guidance provider {settings.provider!r} (§21.4)")


def build_advisor_provider(
    settings: LlmSettings,
    *,
    api_key: str | None,
    transport: httpx.BaseTransport | None = None,
    breaker: CircuitBreaker | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> AdvisorProvider | None:
    """Construct §22's provider, or ``None`` if the feature cannot run.

    **Three conditions where :func:`build_provider` has two**, and the third is the point: the
    vendor client must be enabled, *and* the advisor specifically must be enabled, *and* a key
    must resolve. Enabling §21's guidance is not consent to a chat surface whose per-question
    cost is several times higher (§22.1), so the two features have independent switches and
    neither can turn the other on.

    ``breaker`` is passed through rather than defaulted so the caller can share one instance
    with the guidance provider: a provider that is down is down for both (§22.5).
    """
    if not settings.enabled or not settings.advisor.enabled or not api_key:
        return None

    if settings.provider == "anthropic":
        from tracker.integrations.llm.anthropic_advisor import AnthropicAdvisorProvider

        return AnthropicAdvisorProvider(
            settings,
            api_key=api_key,
            transport=transport,
            breaker=breaker,
            clock=clock,
        )

    raise ValueError(f"unknown advisor provider {settings.provider!r} (§22.5)")
