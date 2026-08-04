"""The OSRS experience curve for levels 1–99 (§8.2).

§8.2 step 1 is *"compute remaining XP to target"*, and step 2 partitions that XP into
level bands. Neither is expressible without the curve, so it lives here as a literal
99-entry table.

**Why this does not violate G9 / §10.8.** The boundary §10.8 draws is *"no game content
lives in code"*, and the content it enumerates is content that **changes**: quests,
items, capabilities, roadmaps, milestones, scoring profiles. *"Adding new game content —
a quest, an item, a capability — never requires a code change."* The XP curve is not in
that class. It is invariant arithmetic: a closed-form sum Jagex has never altered, with
no id, no author and nothing for a content file to say about it. Putting it in YAML would
create a file whose only correct contents are the output of a formula, invite an author to
edit it into being wrong, and add a validation rule (*"is this really the OSRS curve?"*)
that could only be checked by recomputing the formula the file exists to replace.

**Why the table and not the formula at runtime.** The generating formula is

.. code-block:: text

    xp(L) = floor( 1/4 · Σ_{l=1}^{L-1} floor( l + 300 · 2^(l/7) ) )

which is a float exponentiation inside two floors — exactly the shape where a platform's
rounding can move a boundary value by one XP. The table is that formula evaluated once,
checked against the two anchors every OSRS player knows (level 92 is the halfway point at
6,517,253 XP; level 99 is 13,034,431), and frozen. ``tests/estimation/test_xp_table.py``
re-derives it from the formula and asserts equality, so the constant cannot drift from its
own definition without a test failure.
"""

from __future__ import annotations

from bisect import bisect_right

MIN_LEVEL = 1
MAX_LEVEL = 99

#: Total XP required to *reach* each level, indexed by ``level - 1``. Level 1 is 0 XP.
XP_FOR_LEVEL: tuple[int, ...] = (
    0, 83, 174, 276, 388,  # 1-5
    512, 650, 801, 969, 1_154,  # 6-10
    1_358, 1_584, 1_833, 2_107, 2_411,  # 11-15
    2_746, 3_115, 3_523, 3_973, 4_470,  # 16-20
    5_018, 5_624, 6_291, 7_028, 7_842,  # 21-25
    8_740, 9_730, 10_824, 12_031, 13_363,  # 26-30
    14_833, 16_456, 18_247, 20_224, 22_406,  # 31-35
    24_815, 27_473, 30_408, 33_648, 37_224,  # 36-40
    41_171, 45_529, 50_339, 55_649, 61_512,  # 41-45
    67_983, 75_127, 83_014, 91_721, 101_333,  # 46-50
    111_945, 123_660, 136_594, 150_872, 166_636,  # 51-55
    184_040, 203_254, 224_466, 247_886, 273_742,  # 56-60
    302_288, 333_804, 368_599, 407_015, 449_428,  # 61-65
    496_254, 547_953, 605_032, 668_051, 737_627,  # 66-70
    814_445, 899_257, 992_895, 1_096_278, 1_210_421,  # 71-75
    1_336_443, 1_475_581, 1_629_200, 1_798_808, 1_986_068,  # 76-80
    2_192_818, 2_421_087, 2_673_114, 2_951_373, 3_258_594,  # 81-85
    3_597_792, 3_972_294, 4_385_776, 4_842_295, 5_346_332,  # 86-90
    5_902_831, 6_517_253, 7_195_629, 7_944_614, 8_771_558,  # 91-95
    9_684_577, 10_692_629, 11_805_606, 13_034_431,  # 96-99
)  # fmt: skip


def xp_for_level(level: int) -> int:
    """Total XP required to reach ``level``. ``xp_for_level(1) == 0``.

    Raises rather than clamping: a level outside 1–99 reaching this function means a
    band boundary was computed wrongly, and silently returning the level-99 figure would
    turn that into an estimate that is merely implausible instead of an exception naming
    the caller.
    """
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise ValueError(f"level {level} is outside 1–99; the OSRS curve is defined for 1–99 only")
    return XP_FOR_LEVEL[level - 1]


def level_for_xp(xp: int) -> int:
    """The level an XP total confers — the inverse of :func:`xp_for_level`.

    XP above the level-99 threshold still reports 99: the curve ends there while XP does
    not (the cap is 200,000,000), and *"level 108"* is not a fact about any account.
    """
    if xp < 0:
        raise ValueError(f"xp {xp} is negative; an unranked skill is None, never a negative total")
    return bisect_right(XP_FOR_LEVEL, xp)
