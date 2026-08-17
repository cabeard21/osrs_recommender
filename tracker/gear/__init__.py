"""§23. Where an account stands on the authored gear ladders, and what it can wear.

Pure by the same rule as :mod:`tracker.domain`, :mod:`tracker.guidance` and
:mod:`tracker.advisor` (§16.1): no database, no network, no clock. Everything arrives as an
argument and leaves as a frozen value. ``tests/advisor/test_import_boundary.py`` enforces it
here as well as there, and that is not decoration — the advisor imports this package, so a
``sqlalchemy`` import in this tree would be a hole straight through D15's guarantee that an
advisor tool reaches nothing but the frozen snapshot.

Two things live here, for two different callers:

:mod:`~tracker.gear.ladders`  the per-ladder summary §21's guidance has rendered since
                              commit ``33ab4a2``, hoisted so §23 runs the same code rather
                              than a second copy written to match. **Frozen by §21.5** —
                              its decisions are hashed into every stored guidance note.
:mod:`~tracker.gear.setup`    §23.4's computed recommendation, which is new.

Like :mod:`tracker.guidance`, this package is deliberately **not** reachable from the
ranking path. A wear requirement that fed §9 would silently reprice every candidate whose
``completion`` names an item — a ranking change disguised as a content edit — so §23 reads
the corpus and nothing reads §23 back. That is D14's shape applied to a computed projection
rather than to a generated one.
"""

from tracker.gear.ladders import (
    GearRung,
    Ladder,
    build_ladders,
    gear_rungs,
    held_observation,
    item_state,
)
from tracker.gear.render import render_setup
from tracker.gear.setup import (
    STYLES,
    GearPick,
    GearProgress,
    GearSetup,
    SetupSlot,
    gear_progress,
)

__all__ = [
    "STYLES",
    "GearPick",
    "GearProgress",
    "GearRung",
    "GearSetup",
    "Ladder",
    "SetupSlot",
    "build_ladders",
    "gear_progress",
    "gear_rungs",
    "held_observation",
    "item_state",
    "render_setup",
]
