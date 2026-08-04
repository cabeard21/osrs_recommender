"""Shared transport tests (§7.5): retry schedule, `Retry-After`, circuit breaker.

Every test injects ``sleep=recorded_sleep.append`` (or similar) instead of using
``time.sleep`` — the real §7.5 schedule sums to 10s per exhausted retry sequence, and
this suite would be unbearably slow if it actually waited.
"""

from __future__ import annotations

import httpx
import pytest

from tracker.integrations.http import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RequestFailed,
    build_client,
    get_with_retry,
)


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return build_client(
        base_url="https://example.test", user_agent="test-agent/1.0", transport=handler
    )


class TestUserAgent:
    """§7.5, §11.6: every outbound request carries the configured User-Agent."""

    def test_user_agent_header_is_applied(self) -> None:
        seen_headers: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers["user-agent"])
            return httpx.Response(200, json={})

        client = _client(httpx.MockTransport(handler))
        get_with_retry(client, "/x", sleep=lambda _: None)

        assert seen_headers == ["test-agent/1.0"]


class TestRetrySchedule:
    """§7.5: "Retry schedule: immediate -> 2s -> 8s, then stop and fall back.\""""

    def test_success_on_first_attempt_never_sleeps(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        response = get_with_retry(client, "/x", sleep=sleeps.append)

        assert response.status_code == 200
        assert calls == 1
        assert sleeps == []

    def test_429_then_success_follows_the_2s_8s_schedule(self) -> None:
        statuses = iter([429, 429, 200])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(next(statuses), json={})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        response = get_with_retry(client, "/x", sleep=sleeps.append)

        assert response.status_code == 200
        assert sleeps == [2.0, 8.0]

    def test_schedule_exhausted_raises_request_failed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", sleep=sleeps.append)

        assert sleeps == [2.0, 8.0]  # three attempts total: immediate, +2s, +8s

    def test_non_retryable_4xx_fails_without_exhausting_the_schedule(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(404, json={})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", sleep=sleeps.append)

        assert calls == 1
        assert sleeps == []

    def test_retry_after_stretches_the_next_scheduled_wait(self) -> None:
        statuses_and_headers = iter(
            [
                (429, {"Retry-After": "5"}),
                (200, {}),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            status, headers = next(statuses_and_headers)
            return httpx.Response(status, headers=headers, json={})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        get_with_retry(client, "/x", sleep=sleeps.append)

        # Retry-After (5s) exceeds the schedule's 2s, so it wins.
        assert sleeps == [5.0]

    def test_retry_after_never_shrinks_the_scheduled_wait(self) -> None:
        statuses_and_headers = iter(
            [
                (429, {"Retry-After": "1"}),
                (200, {}),
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            status, headers = next(statuses_and_headers)
            return httpx.Response(status, headers=headers, json={})

        sleeps: list[float] = []
        client = _client(httpx.MockTransport(handler))
        get_with_retry(client, "/x", sleep=sleeps.append)

        # Retry-After (1s) is smaller than the schedule's 2s; the schedule wins.
        assert sleeps == [2.0]


class TestCircuitBreaker:
    """§7.5: "Circuit breaker after repeated failures.\""""

    def test_opens_after_the_failure_threshold(self) -> None:
        breaker = CircuitBreaker(failure_threshold=2)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        client = _client(httpx.MockTransport(handler))

        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)
        assert breaker.is_open is False  # one exhausted sequence = one failure

        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)
        assert breaker.is_open is True

    def test_open_breaker_short_circuits_before_any_request(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={})

        breaker = CircuitBreaker(failure_threshold=1)
        breaker.record_failure()
        assert breaker.is_open is True

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(CircuitBreakerOpen):
            get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)
        assert calls == 0

    def test_success_resets_the_failure_count(self) -> None:
        breaker = CircuitBreaker(failure_threshold=2)
        # Calls 1-3: the first get_with_retry's whole 3-attempt schedule fails.
        # Call 4: the second get_with_retry succeeds on its first attempt.
        # Calls 5-7: the third get_with_retry's whole schedule fails again.
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200 if call_count == 4 else 500, json={})

        client = _client(httpx.MockTransport(handler))
        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)

        response = get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)
        assert response.status_code == 200
        assert breaker.is_open is False

        with pytest.raises(RequestFailed):
            get_with_retry(client, "/x", breaker=breaker, sleep=lambda _: None)
        assert breaker.is_open is False  # only one consecutive failure since the reset

    def test_half_opens_after_the_cooldown(self) -> None:
        fake_time = [0.0]
        breaker = CircuitBreaker(
            failure_threshold=1, reset_after_seconds=60.0, clock=lambda: fake_time[0]
        )
        breaker.record_failure()
        assert breaker.is_open is True

        fake_time[0] = 61.0
        assert breaker.is_open is False
