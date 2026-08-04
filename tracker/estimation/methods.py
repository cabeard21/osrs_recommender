"""Level-band partitioning and per-band method selection (§8.2, §8.1).

§8.2 steps 2 and 3, which are one algorithm and not two:

1. partition the remaining XP into the level bands the available methods span, then
2. per band, take the highest ``xp_per_hour`` method **whose requirements the player
   currently satisfies**.

The partition exists *because of* the selection. §8.1's own example — ``magic_bursting``,
``level_range: {min: 82, max: 99}`` — is why a single rate over the whole 87→94 span would
be wrong in both directions: it either credits bursting to levels that cannot burst, or
denies it to levels that can. Cutting at every method boundary makes each band a stretch
over which exactly one rate is correct.

**A method gated ``unknown`` is not available.** §9.1's rule reaches here unchanged: an
account that has never synced its unlocks does not *"currently satisfy"* Ancients, and
selecting bursting on that basis would quote 4.5 hours for training the player cannot
start. The plausible wrong version is ``if result.value != Tri.UNSATISFIED`` — it reads as
caution and is the D8 collapse in the other direction. Every comparison here names the
member it means, because :meth:`Tri.__bool__` raises rather than let the idiom compile.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from tracker.content.loader import Content
from tracker.content.schema import TrainingMethod
from tracker.domain.types import BandEstimate, Confidence, Tri
from tracker.estimation.xp_table import MAX_LEVEL, xp_for_level
from tracker.progression.evaluate import Evaluator

#: §8.2's *"conservative default rate"* for a band no authored method covers.
#:
#: Deliberately slower than every rate in the corpus. The failure this guards against is
#: an under-estimate: §9.4 ranks on ``effort_decay = exp(−hours/τ)``, so a generous
#: default would make the least-understood candidate look like the cheapest one. The band
#: is also flagged ``fallback=True``, which drags ``estimate_confidence`` to ``low``
#: (§8.4) — the number is a placeholder the UI is required to qualify, not a claim.
#:
#: It is a code constant rather than content because it is the *absence* of content: a
#: YAML file authored for the case where the corpus says nothing would itself be the
#: missing method (§10.8 — the boundary is game content, and this is a policy default).
FALLBACK_XP_PER_HOUR = 15_000

#: Zero, and not a conservative guess. Hours are already pessimistic above; inventing a
#: GP rate as well would put a fabricated number into §9.4's ``cost_decay`` where nothing
#: distinguishes it from a measured one. ``low`` confidence on the band is how the
#: uncertainty is carried (§8.4), rather than by a second invented figure.
FALLBACK_COST_PER_HOUR_GP = 0


@dataclass(frozen=True, slots=True)
class LevelBand:
    """A half-open level span ``[from_level, to_level)`` — the levels *trained through*.

    Half-open because bands abut: an 87→94 span cut at bursting's level 82 boundary is
    ``[87, 94)`` alone, and a 70→94 span becomes ``[70, 82)`` then ``[82, 94)`` with level
    82 trained once, not twice. ``to_level`` is the level *reached*, never a level trained
    at, which is why :func:`covers` tests ``to_level - 1``.
    """

    from_level: int
    to_level: int


def partition_bands(
    from_level: int, to_level: int, methods: tuple[TrainingMethod, ...]
) -> tuple[LevelBand, ...]:
    """Cut ``[from_level, to_level)`` at every method boundary inside it (§8.2 step 2).

    The cut points are each method's ``level_range.min`` and ``level_range.max + 1``:
    the first level a method becomes usable, and the first level it stops being. Every
    resulting band is therefore covered by a method wholly or not at all, which is what
    lets :func:`select_method` treat one band as one rate.

    An empty result means the target is already met — the caller has nothing to estimate,
    not zero hours of work at an unknown rate.
    """
    if to_level <= from_level:
        return ()

    cuts = {from_level, to_level}
    for method in methods:
        for boundary in (method.level_range.min, method.level_range.max + 1):
            if from_level < boundary < to_level:
                cuts.add(boundary)

    return tuple(LevelBand(from_level=start, to_level=end) for start, end in pairwise(sorted(cuts)))


def covers(method: TrainingMethod, band: LevelBand) -> bool:
    """Whether ``method`` is usable for every level in ``band``.

    ``band.to_level - 1`` is the last level actually *trained at*: a method capped at 99
    covers a band ending at level 99's threshold, and one capped at 81 does not cover a
    band that starts at 82.
    """
    return method.level_range.min <= band.from_level and method.level_range.max >= band.to_level - 1


def select_method(
    band: LevelBand, methods: tuple[TrainingMethod, ...], evaluator: Evaluator
) -> TrainingMethod | None:
    """The fastest method covering ``band`` that the player **currently satisfies** (§8.2).

    ``methods`` must already be fastest-first — :meth:`Content.methods_for_skill` sorts
    them — so the first satisfied match is the highest ``xp_per_hour`` one. A method with
    no ``requires`` is satisfied by everyone; ``unknown`` is not satisfied (§9.1).

    ``None`` means the band has no available method and the caller must fall back (§8.2).
    """
    for method in methods:
        if not covers(method, band):
            continue
        if method.requires is None:
            return method
        if evaluator.evaluate(method.requires).value is Tri.SATISFIED:
            return method
    return None


def plan_bands(
    skill: str,
    *,
    current_xp: int,
    from_level: int,
    to_level: int,
    content: Content,
    evaluator: Evaluator,
) -> tuple[BandEstimate, ...]:
    """§8.2 end to end for one skill: partition, select, and integrate per band.

    ``current_xp`` is the account's actual total, not ``xp_for_level(from_level)``: a
    player two-thirds of the way through level 87 has already done that XP, and charging
    for it again would overstate the first band by up to a full level. Later bands start
    on a threshold exactly, so the ``max`` below only ever bites on the first.

    ``xp`` is nullable on ``SkillState`` (unranked, §6.2 / G5); callers with no total pass
    ``xp_for_level(from_level)``, which is the honest floor rather than a guess.
    """
    methods = content.methods_for_skill(skill)
    bands: list[BandEstimate] = []

    for band in partition_bands(from_level, min(to_level, MAX_LEVEL), methods):
        band_xp = xp_for_level(band.to_level) - max(current_xp, xp_for_level(band.from_level))
        if band_xp <= 0:
            continue

        method = select_method(band, methods, evaluator)
        xp_per_hour = method.xp_per_hour if method is not None else FALLBACK_XP_PER_HOUR
        cost_per_hour = method.cost_per_hour_gp if method is not None else FALLBACK_COST_PER_HOUR_GP
        hours = band_xp / xp_per_hour

        bands.append(
            BandEstimate(
                from_level=band.from_level,
                to_level=band.to_level,
                method_id=method.id if method is not None else None,
                hours=hours,
                gp=round(hours * cost_per_hour),
                fallback=method is None,
            )
        )

    return tuple(bands)


def method_confidence(bands: tuple[BandEstimate, ...]) -> Confidence:
    """§8.4 — ``high`` when every band has an authored available method, else ``low``.

    Two-valued on purpose. §8.4 gives the training half of the estimate exactly these two
    outcomes; the third level exists for *prices*, where a cached figure from yesterday
    genuinely sits between a live trade and a hand-authored guess. There is no equivalent
    middle for a band nobody authored a method for — either the corpus describes how to
    train it or the rate is invented.
    """
    if any(band.fallback for band in bands):
        return Confidence.LOW
    return Confidence.HIGH
