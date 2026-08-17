"""Task-scoped context assembly for §21's generated guidance.

Pure by the same rule as :mod:`tracker.domain` and :mod:`tracker.recommendations` (§16.1):
no database, no network, no clock. Everything arrives as an argument and leaves as a frozen
value. ``tests/progression/test_import_boundary.py`` enforces it.

This package is deliberately **not** reachable from the ranking path. §10.5 makes
``MethodDetail`` descriptive content that no recommendation may read, and this is the one
module in the tree that reads it heavily — putting it under
:mod:`tracker.recommendations` would leave that rule one careless import from breaking.
D14 states the same boundary from the other end: what happens here is a terminal output.
"""

# §23 hoisted the ladder projection out of this package; it is still re-exported here
# because §21 is what renders it and callers reasonably look for it beside TaskContext.
from tracker.gear.ladders import GearRung
from tracker.guidance.context import (
    ItemFact,
    MethodFact,
    SkillFact,
    TaskContext,
    build_task_context,
)
from tracker.guidance.prompt import (
    GUIDANCE_SCHEMA_VERSION,
    SYSTEM_PROMPT,
    GuidancePrompt,
    build_prompt,
    context_hash,
    render_context,
)

__all__ = [
    "GUIDANCE_SCHEMA_VERSION",
    "SYSTEM_PROMPT",
    "GearRung",
    "GuidancePrompt",
    "ItemFact",
    "MethodFact",
    "SkillFact",
    "TaskContext",
    "build_prompt",
    "build_task_context",
    "context_hash",
    "render_context",
]
