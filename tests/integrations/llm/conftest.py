"""Builders for the §21.4 provider tests.

``httpx.MockTransport`` throughout, exactly as ``tests/integrations/prices/`` does — the
Anthropic SDK takes an ``http_client``, and ``DefaultHttpxClient`` forwards ``transport=``,
so the vendor SDK does not cost this directory a different testing style.

``max_retries=0`` on every settings object built here. The SDK retries 429s and 5xx with
backoff by default, and a test that asserts a 500 becomes ``LlmUnavailable`` would otherwise
sleep through the real schedule to get there.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tracker.config.settings import LlmSettings
from tracker.guidance.prompt import GuidancePrompt

#: A fixed generation time, injected as the provider's clock.
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

API_KEY = "test-key"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def api_key() -> str:
    return API_KEY


@pytest.fixture
def llm_settings() -> Callable[..., LlmSettings]:
    def build(**overrides: Any) -> LlmSettings:
        defaults: dict[str, Any] = {
            "enabled": True,
            "model": "claude-opus-5",
            "effort": "medium",
            "max_tokens": 8000,
            "max_retries": 0,
        }
        return LlmSettings(**{**defaults, **overrides})

    return build


@pytest.fixture
def prompt() -> GuidancePrompt:
    return GuidancePrompt(
        system="You are an Old School RuneScape advisor.",
        user="# Task\n\n**Train Slayer to 10** (skill training)",
        context_hash="0" * 64,
    )


@pytest.fixture
def answer_body() -> Callable[..., dict[str, Any]]:
    """A well-formed Messages response carrying §21.3's structured answer."""

    def build(
        *,
        summary: str = "Get a task from Turael and kill it.",
        prerequisites: list[str] | None = None,
        steps: list[dict[str, str]] | None = None,
        warnings: list[str] | None = None,
        estimated_session_minutes: int | None = 30,
        uncertain: list[str] | None = None,
        stop_reason: str = "end_turn",
        usage: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "summary": summary,
            "prerequisites": prerequisites if prerequisites is not None else ["any weapon"],
            "steps": steps
            if steps is not None
            else [
                {"title": "Travel to Burthorpe", "detail": "Use the games necklace."},
                {"title": "Ask Turael for a task", "detail": "Talk to him and accept."},
            ],
            "warnings": warnings if warnings is not None else ["Bank anything you value."],
            "estimated_session_minutes": estimated_session_minutes,
            "uncertain": uncertain if uncertain is not None else [],
        }
        return {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage
            if usage is not None
            else {
                "input_tokens": 1200,
                "output_tokens": 400,
                "cache_read_input_tokens": 900,
            },
        }

    return build


@pytest.fixture
def recording_transport() -> Callable[..., tuple[httpx.MockTransport, list[dict[str, Any]]]]:
    """A transport that answers with a fixed body and records every request body."""

    def build(
        body: dict[str, Any], *, status: int = 200, headers: dict[str, str] | None = None
    ) -> tuple[httpx.MockTransport, list[dict[str, Any]]]:
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(status, json=body, headers=headers)

        return httpx.MockTransport(handler), seen

    return build
