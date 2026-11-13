"""Native execution scope and out-of-band execution evidence.

Importing this module never imports a compiled extension. Ordinary installations
remain compiler-free; explicit Python execution and pre-work numeric safety
fallbacks retain the reference implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

_active: ContextVar[bool] = ContextVar("native_search", default=False)
_evidence: ContextVar[Evidence | None] = ContextVar("native_evidence", default=None)


class Evidence:
    def __init__(self) -> None:
        self._events: tuple[dict[str, Any], ...] = ()

    def add(self, event: dict[str, Any]) -> None:
        self._events = (*self._events, deepcopy(event))

    def snapshot(self) -> dict[str, Any]:
        return {
            "native_requests": sum(row["event"] == "native_request" for row in self._events),
            "fallback_requests": sum(row["event"] == "fallback" for row in self._events),
            "events": deepcopy(list(self._events)),
        }


@contextmanager
def capture() -> Iterator[Evidence]:
    evidence = Evidence()
    token = _evidence.set(evidence)
    try:
        yield evidence
    finally:
        _evidence.reset(token)


def record(event: str, **fields: Any) -> None:
    evidence = _evidence.get()
    if evidence is not None:
        evidence.add({"event": event, **fields})


def merge(diagnostics: dict[str, Any]) -> None:
    evidence = _evidence.get()
    if evidence is not None:
        for event in diagnostics["events"]:
            evidence.add(event)


def active() -> bool:
    return _active.get()


@contextmanager
def execution(enabled: bool) -> Iterator[None]:
    if not isinstance(enabled, bool):
        raise ValueError("Invalid native search option")
    token = _active.set(enabled)
    try:
        yield
    finally:
        _active.reset(token)


def support_reason(request: Any) -> str | None:
    if any(
        role.style not in {"stab", "slash", "crush", "ranged", "magic", "special"}
        for role in request.roles
    ):
        return "unsupported_discipline"
    if len(request.roles) > 4:
        return "unsupported_role_count"
    return None


def create_context(search: Any) -> Any:
    if not active():
        return None
    reason = support_reason(search.request)
    if not search.compact_states or not search.factored_evaluation:
        reason = "requires_combined_compact_execution"
    if reason is None:
        from tracker.gear.native.packing import support_reason as scoring_support
        from tracker.gear.native.stage_context import preflight

        reason = scoring_support(search) or preflight(search)
    if reason is not None:
        record("fallback", reason=reason)
        return None
    try:
        from tracker.gear.native._scoring import ScoringContext
    except ImportError as exc:
        raise ValueError(
            "native_extension_unavailable: run python -m tools.build_gear_native"
        ) from exc
    context = ScoringContext(search)
    record("native_request", roles=tuple(role.style for role in search.request.roles))
    return context


def reset_context(search: Any, *, scoring: bool = False) -> None:
    """Give a copied lane its own stages and repack changed objective constants.

    Stage contexts capture the producing search, its weights and constraints.
    Sharing those across copies silently reuses the wrong objective or marginals.
    Scoring contexts are immutable and may be shared only for unchanged requests.
    """
    search._native_stage_context = None
    if scoring and getattr(search, "native_context", None) is not None:
        search.native_context = create_context(search)
