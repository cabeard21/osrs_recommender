"""Opt-in ranged numerical experiment; legality and reporting remain with combat."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from math import floor
from typing import NamedTuple

Key = tuple[int | None, int, int, int, str, int, int, int, str, int, int, int, int | None]


class CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class Outgoing(NamedTuple):
    max_hit: int
    attack: int
    defence: int
    speed: int
    accuracy: float
    maxima: tuple[int, ...]
    probabilities: tuple[float, ...]
    expected: float
    capped: bool


def calculate(key: Key) -> Outgoing:
    """Evaluate only reviewed ranged outgoing dependencies, in original order."""
    (
        _weapon_id,
        level,
        strength_prayer,
        accuracy_prayer,
        stance,
        strength_bonus,
        attack_bonus,
        speed,
        pattern,
        defence_level,
        defence_bonus,
        armour,
        cap,
    ) = key
    stance_bonus = 3 if stance == "accurate" else 0
    effective_strength = level * strength_prayer // 100 + 8 + stance_bonus
    maximum = max(0, floor(0.5 + effective_strength * (strength_bonus + 64) / 640))
    attack = (level * accuracy_prayer // 100 + 8 + stance_bonus) * (attack_bonus + 64)
    defence = (defence_level + 9) * (defence_bonus + 64)
    if stance == "rapid":
        speed = max(1, speed - 1)
    a, d = max(0, attack), max(0, defence)
    accuracy = 1 - (d + 2) / (2 * (a + 1)) if a > d else a / (2 * (d + 1))
    maxima = (maximum,) if pattern == "single" else (maximum // 2, maximum - maximum // 2)
    probabilities = (
        (accuracy,)
        if pattern == "single"
        else (accuracy, accuracy**2 if pattern == "conditional_double" else accuracy)
    )

    def mean(m: int) -> float:
        first = max(1, armour + 1)
        count = max(0, m - first + 1)
        positive_sum = count * (first + m - 2 * armour) / 2
        # Match combat._armoured_mean, including accurate zero -> one.
        return (max(0, 1 - armour) + positive_sum) / (m + 1)

    expected = sum(p * mean(m) for m, p in zip(maxima, probabilities, strict=True))
    return Outgoing(
        maximum,
        attack,
        defence,
        speed,
        accuracy,
        maxima,
        probabilities,
        expected,
        cap is not None and any(max(1, m) > cap for m in maxima),
    )


@dataclass
class RangedExperiment:
    capacity: int
    observe: bool
    accesses: list[tuple[Key, Outgoing]] = field(default_factory=list)
    key_seconds: float = 0.0

    def __post_init__(self) -> None:
        self._cached = lru_cache(maxsize=self.capacity)(calculate)

    def evaluate(self, key: Key) -> Outgoing:
        result = self._cached(key)
        if self.observe:
            self.accesses.append((key, result))
        return result

    def cache_info(self) -> CacheInfo:
        return CacheInfo(*self._cached.cache_info())


_ACTIVE: ContextVar[RangedExperiment | None] = ContextVar("ranged_experiment", default=None)


@contextmanager
def ranged_experiment(capacity: int = 0, observe: bool = False) -> Iterator[RangedExperiment]:
    """Confine optional reuse and observations to this execution context."""
    if capacity < 0:
        raise ValueError("capacity must be nonnegative")
    experiment = RangedExperiment(capacity, observe)
    token = _ACTIVE.set(experiment)
    try:
        yield experiment
    finally:
        _ACTIVE.reset(token)


def evaluate(key: Key) -> Outgoing:
    experiment = _ACTIVE.get()
    return calculate(key) if experiment is None else experiment.evaluate(key)


def active() -> bool:
    """Whether this execution opted into the experiment."""
    return _ACTIVE.get() is not None


def observer() -> RangedExperiment | None:
    """Return the active observer without timing uninstrumented experiments."""
    experiment = _ACTIVE.get()
    return experiment if experiment is not None and experiment.observe else None
