"""Shared HTTP transport for outbound integrations (§7.5, §11.6).

Both the OSRS Wiki prices client (:mod:`tracker.integrations.prices.client`) and the
Wise Old Man client (:mod:`tracker.integrations.wise_old_man.client`) are read-only
HTTP consumers with the same defensive shape, so it lives once, here, rather than
being re-derived per client:

* a descriptive ``User-Agent`` — §7.5 notes the provider pre-emptively blocks the
  default identifier strings various HTTP libraries send when nobody overrides them
  (Python's popular request library, its standard-library URL opener, Java's common
  HTTP client, bare ``curl``); :class:`tracker.config.settings.PricesSettings` already
  rejects those at config-load time (see its ``_reject_generic_user_agent`` validator),
  so this module only has to *apply* the header, never validate it again;
* a bounded retry schedule — immediate → 2s → 8s, then stop;
* ``Retry-After`` honoured whenever the provider sends it, stretching the next
  scheduled wait rather than ignoring it;
* exponential backoff on ``429`` and ``5xx`` (the schedule itself *is* the backoff);
* a circuit breaker, so a sustained provider outage degrades to "stop asking" instead
  of forcing every subsequent recommendation run through the full retry schedule.

Every function here takes ``sleep`` as a parameter with a real-time default. Tests
inject a no-op so the §7.5 retry schedule (up to 10s of real sleeping) never slows the
suite down, and no test needs to touch ``time.sleep`` globally.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: §7.5, §7.6 (Step 7 task list): "immediate → 2s → 8s, then stop and fall back."
RETRY_DELAYS_SECONDS: tuple[float, ...] = (0.0, 2.0, 8.0)

_RETRYABLE_MIN_STATUS = 500
_TOO_MANY_REQUESTS = 429


def build_client(
    *,
    base_url: str,
    user_agent: str,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build an ``httpx.Client`` with the outbound User-Agent set (§7.5, §11.6).

    ``transport`` is the seam tests use: pass an ``httpx.MockTransport`` and no call
    through this client issues a real network request.
    """
    return httpx.Client(
        base_url=base_url,
        headers={"User-Agent": user_agent},
        timeout=timeout,
        transport=transport,
    )


class CircuitBreakerOpen(RuntimeError):
    """Raised in place of attempting a request while the breaker is open."""


class RequestFailed(RuntimeError):
    """The retry schedule was exhausted, or the provider returned a non-retryable error."""


@dataclass
class CircuitBreaker:
    """Opens after repeated failures (§7.5) and closes again after a cooldown.

    Retries absorb one flaky request; the breaker exists for the case retries do not
    help — a sustained provider outage — so that a recommendation run stops asking
    instead of burning the full 10s retry schedule on every scoped item, run after run.
    Half-open on the next call after ``reset_after_seconds``: one probe request decides
    whether to stay open or resume normal service.
    """

    failure_threshold: int = 3
    reset_after_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _opened_at: float | None = field(default=None, init=False, repr=False)

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return self.clock() - self._opened_at < self.reset_after_seconds

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = self.clock()


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    breaker: CircuitBreaker | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """``GET`` under the §7.5 retry policy.

    Three attempts at ``RETRY_DELAYS_SECONDS`` (0s, 2s, 8s). A ``Retry-After`` header
    on a ``429``/``5xx`` response stretches the *next* scheduled wait rather than
    adding a second sleep on top of it. A non-retryable ``4xx`` fails fast — no amount
    of waiting fixes a malformed request, and burning the schedule on one would only
    delay the fallback §8.3 already provides.

    Raises :class:`RequestFailed` or :class:`CircuitBreakerOpen` rather than returning
    a sentinel, so *this* module has no opinion on what a caller does about a failure —
    §7.5's "no user-visible failure when a cached or static fallback exists" is a
    decision for :mod:`tracker.integrations.prices.cache`, not for the transport.
    """
    if breaker is not None and breaker.is_open:
        raise CircuitBreakerOpen(f"circuit open for {url}")

    pending_retry_after: float | None = None
    last_error: Exception | None = None

    for attempt, scheduled_delay in enumerate(RETRY_DELAYS_SECONDS):
        delay = (
            scheduled_delay
            if pending_retry_after is None
            else max(scheduled_delay, pending_retry_after)
        )
        if delay:
            sleep(delay)
        pending_retry_after = None

        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("GET %s failed on attempt %d: %s", url, attempt + 1, exc)
            continue

        logger.info("GET %s -> %d (attempt %d)", url, response.status_code, attempt + 1)

        if response.status_code < 400:
            if breaker is not None:
                breaker.record_success()
            return response

        if (
            response.status_code == _TOO_MANY_REQUESTS
            or response.status_code >= _RETRYABLE_MIN_STATUS
        ):
            pending_retry_after = _retry_after_seconds(response)
            last_error = RequestFailed(f"{url} returned {response.status_code}")
            continue

        if breaker is not None:
            breaker.record_failure()
        raise RequestFailed(f"{url} returned {response.status_code}")

    if breaker is not None:
        breaker.record_failure()
    raise RequestFailed(f"{url}: retry schedule exhausted") from last_error


def _retry_after_seconds(response: httpx.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        # §7.5 also allows an HTTP-date form; v1 keeps it simple and falls back to the
        # scheduled delay rather than parsing RFC 7231 dates for a case the provider
        # has not been observed to use.
        return None
