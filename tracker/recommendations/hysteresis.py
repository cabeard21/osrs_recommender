"""§9.9's anti-thrash rule: the top slot is sticky.

Without it, two near-tied candidates swap places on every sync — a price tick, ten
thousand XP — and the app's single most prominent answer to *"what should I work on
next?"* becomes noise. §16.2's stability tests are the same concern stated as assertions.

The incumbent keeps the top slot unless one of three things is true (§9.9):

* a challenger scores ``> 1.10 ×`` the incumbent,
* the incumbent has become **complete**, or
* the incumbent has become **blocked**.

The last two need no code here: a completed candidate never ranks and a blocked one is
excluded from the actionable list (§16.2), so both arrive as *the incumbent is not in the
list*, and the rule below leaves such a ranking untouched.

**Raw scores, not log scores** (A15). §9.5 evaluates in log space, and a 10% margin there
is a different threshold from a 10% margin in raw space — the two coincide only near
``score = 1``. §9.9 means "10% better", which is the raw form.

**Strictly greater.** A challenger at exactly ``1.10 ×`` does **not** displace. The margin
is the size of the improvement required, so an improvement of exactly the margin has not
exceeded it — and a boundary that displaces on equality reintroduces thrash for any pair
whose ratio is pinned at 1.10 by construction.
"""

from __future__ import annotations

from collections.abc import Sequence

from tracker.domain.types import IncumbentRecommendation, Recommendation

#: §9.9's displacement margin. Content-shaped, but not content: unlike τ, κ and the §9.4
#: weights, this does not shape *what is recommended* — it damps how fast the answer is
#: allowed to change. Step 13 tunes the former against the golden corpus (§16.3) and has
#: nothing to say about the latter, so promoting it to ``profile.yaml`` would add a knob
#: with no tuning procedure behind it.
DISPLACEMENT_MARGIN = 1.10


def apply_hysteresis(
    ranked: Sequence[Recommendation],
    incumbent: IncumbentRecommendation | None,
) -> tuple[Recommendation, ...]:
    """Restore the incumbent to the top slot unless §9.9 permits its displacement.

    Only the incumbent moves, and it moves *to the front* rather than swapping with the
    challenger. Swapping would demote the challenger to whatever rank the incumbent held —
    for an incumbent at rank 5, burying the best candidate below three worse ones. The rule
    is about the top slot and nothing else.

    Returns ``ranked`` unchanged when there is no incumbent (a first run), when the
    incumbent is already top, or when the incumbent is absent from the list — the last
    being how *"the incumbent became complete or blocked"* reaches this function.
    """
    if incumbent is None or not ranked:
        return tuple(ranked)

    position = _position_of(ranked, incumbent.candidate_id)
    if position is None or position == 0:
        return tuple(ranked)

    challenger = ranked[0]
    defender = ranked[position]
    if challenger.score > DISPLACEMENT_MARGIN * defender.score:
        return tuple(ranked)

    return (defender, *ranked[:position], *ranked[position + 1 :])


def _position_of(ranked: Sequence[Recommendation], candidate_id: str) -> int | None:
    for index, entry in enumerate(ranked):
        if entry.candidate_id == candidate_id:
            return index
    return None
