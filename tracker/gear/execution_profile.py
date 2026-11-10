"""Server-owned desktop execution choices; no public search-policy changes."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from typing import Any, Literal, cast

ExecutionProfile = Literal["baseline", "lazy", "combined"]
_compact_states: ContextVar[bool] = ContextVar("compact_states", default=False)
_factored_evaluation: ContextVar[bool] = ContextVar("factored_evaluation", default=False)


def compact_states_active() -> bool:
    """Whether this leaf uses P3 compact internal state representations."""
    return _compact_states.get()


def factored_evaluation_active() -> bool:
    """Whether this leaf uses the complete P1 evaluation path."""
    return _factored_evaluation.get()


def validate_profile(value: object) -> ExecutionProfile:
    if not isinstance(value, str) or value not in ("baseline", "lazy", "combined"):
        raise ValueError("Invalid desktop execution profile")
    return cast(ExecutionProfile, value)


@contextmanager
def execution_context(
    profile: ExecutionProfile,
    request: Any,
    *,
    fixed_reporting: bool = False,
    factored_evaluation: bool = False,
    compact_states: bool = False,
) -> Iterator[None]:
    """Create fresh per-leaf caches, never attached to worker preparation state."""
    validate_profile(profile)
    if not isinstance(fixed_reporting, bool):
        raise ValueError("Invalid fixed reporting option")
    if not isinstance(factored_evaluation, bool):
        raise ValueError("Invalid factored evaluation option")
    if not isinstance(compact_states, bool):
        raise ValueError("Invalid compact states option")
    with ExitStack() as stack:
        roles = request.roles
        token = _factored_evaluation.set(profile == "combined" and factored_evaluation)
        stack.callback(_factored_evaluation.reset, token)
        compact_token = _compact_states.set(
            profile == "combined" and factored_evaluation and compact_states
        )
        stack.callback(_compact_states.reset, compact_token)
        if compact_states_active():
            from tracker.gear.compact_solutions import solution_scope
            from tracker.gear.compact_states import equipment_pool

            if len(roles) > 1:
                stack.enter_context(equipment_pool())
            stack.enter_context(solution_scope())
        if profile == "combined" and factored_evaluation:
            from tracker.gear.compact_costs import compact_running_costs
            from tracker.gear.prepared_combat import prepared_combat
            from tracker.gear.ranged_score_finalization import ranged_score_finalization
            from tracker.gear.variant_reporting import lazy_variants

            stack.enter_context(prepared_combat())
            stack.enter_context(compact_running_costs())
            stack.enter_context(lazy_variants())
            stack.enter_context(ranged_score_finalization())
        ordinary_single = len(roles) == 1 and roles[0].style != "special"
        factored_multi = len(roles) > 1 and factored_evaluation_active()
        if profile != "baseline" and (ordinary_single or factored_multi):
            from tracker.gear.lazy_reporting import lazy_reporting

            stack.enter_context(lazy_reporting())
            if profile == "combined" and fixed_reporting:
                from tracker.gear.fixed_reporting import fixed_reporting as fixed_context

                stack.enter_context(fixed_context())
            if profile == "combined" and ordinary_single and roles[0].style == "ranged":
                from tracker.gear.ranged_numerics import ranged_experiment

                stack.enter_context(ranged_experiment(65536))
        yield


def validate_worker_options(options: dict[str, Any], allowed: set[str]) -> None:
    """Profile is the sole string option; retain strict boolean flag validation."""
    for key, value in options.items():
        if key == "_execution_profile":
            validate_profile(value)
        elif key not in allowed or not isinstance(value, bool):
            raise ValueError("Invalid desktop worker options")
