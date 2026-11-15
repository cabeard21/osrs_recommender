"""Expected ordinary halberd status damage over a finite exposure window.

Sources: https://oldschool.runescape.wiki/w/Venom and /w/Poison.
NPC timer phase is averaged uniformly over 1..30 game ticks. Attacks land
at tick zero and every weapon interval thereafter; an attack on a timer tick
is resolved first. Poison fallback has severity 26, refreshed by applications.
No prior affliction, death, healing, downtime or cross-role carryover is modeled.
"""

from functools import lru_cache
from math import isfinite
from typing import Literal

MODEL_VERSION = "halberd-status-v1"
SERPENTINE_HEADS = frozenset({12931})
HALBERD_IDS = frozenset({3190, 3192, 3194, 3196, 3198, 3200, 3202, 3204, 6599, 28049, 23987, 29796})


def application_chance(weapon_id: int | None, head_id: int | None, style: str) -> float:
    """Only reviewed ordinary halberd/charged-helmet combinations apply."""
    if style not in {"stab", "slash", "crush"} or weapon_id not in HALBERD_IDS:
        return 0.0
    if weapon_id == 29796:
        return 0.5 if head_id in SERPENTINE_HEADS else 1 / 3
    return 1 / 6 if head_id in SERPENTINE_HEADS else 0.0


def status_kind(poison: str, venom: str) -> Literal["venom", "poison", "unknown"] | None:
    if venom == "susceptible":
        return "venom"
    if venom == "immune" and poison == "susceptible":
        return "poison"
    return None if venom == poison == "immune" else "unknown"


@lru_cache(maxsize=8192)
def expected_damage(chance: float, speed: int, duration: int, kind: str) -> float:
    """Exact expectation across application outcomes and discrete timer phases."""
    if (
        not isfinite(chance)
        or not 0 <= chance <= 1
        or speed < 1
        or not 1 <= duration <= 3600
        or kind not in {"venom", "poison"}
    ):
        raise ValueError("Invalid status damage context")
    if not chance:
        return 0.0
    end = duration * 5 // 3
    maximum = 8 if kind == "venom" else 26
    total = 0.0
    for phase in range(1, 31):
        states = [1.0, *([0.0] * maximum)]
        attacks = 0
        for tick in range(phase, end + 1, 30):
            count = tick // speed + 1
            unchanged = (1 - chance) ** (count - attacks)
            attacks = count
            if kind == "venom":
                applied = states[0] * (1 - unchanged)
                states = [states[0] * unchanged, states[1] + applied, *states[2:]]
                total += sum(states[s] * (4 + 2 * s) for s in range(1, 9))
                states = [states[0], 0.0, *states[1:7], states[7] + states[8]]
            else:
                states = [v * unchanged for v in states]
                states[26] += 1 - unchanged
                total += sum(states[s] * ((s + 4) // 5) for s in range(1, 27))
                states = [states[0] + states[1], *states[2:], 0.0]
    return total / 30
