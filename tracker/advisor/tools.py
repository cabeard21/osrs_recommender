"""§22.4's tool catalogue: the declarations, and the fingerprint that pins them.

Seven tools, reaching exactly what §22.2's digest leaves out. Each one is a *lookup* — D15
allows tools to project already-computed state and nothing else, so there is no tool here that
ranks, scores, estimates on demand, evaluates a hypothetical account, writes, or fetches. That
is not a restraint the implementations happen to observe; it is a property of the catalogue,
and the absence of such a tool is the enforcement.

:data:`TOOLS` is a **module-level tuple, sorted by name, built once**. Providers render tool
definitions at position zero of the prompt, ahead of the instructions and the digest, so a
catalogue assembled per request from an unordered collection would move the whole cached prefix
on every turn. The symptom of getting that wrong is not an error or a wrong answer — it is a
bill, which is why :func:`tools_fingerprint` exists and why §22.3's hash folds it in.

Schemas set ``additionalProperties: false`` throughout. A model that invents an argument should
be told so by the provider's own validation rather than have it silently dropped here, because
a silently dropped filter returns a plausible answer to a different question than the one asked.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from tracker.integrations.llm.types import ToolSpec

#: How much one tool may return. Six thousand characters is roughly a page and a half — enough
#: for a requirement tree or eight methods, and short of the point where one lookup crowds the
#: account summary out of the model's attention. Results are truncated with an explicit marker
#: rather than silently, for §22.2's reason: a cut list that does not say so reads as complete.
MAX_TOOL_RESULT_CHARS: Final = 6000

#: Result caps for the tools that return lists. Bounded here rather than in the schema so the
#: dispatcher enforces them even when a provider ignores a schema maximum.
MAX_SEARCH_RESULTS: Final = 25
MAX_METHOD_RESULTS: Final = 8
MAX_QUEST_RESULTS: Final = 40
MAX_PRICE_RESULTS: Final = 15


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


SEARCH_CANDIDATES = ToolSpec(
    name="search_candidates",
    description=(
        "Search the tracker's candidate corpus — the several hundred tasks the account summary "
        "does not list. Returns id, name, kind, the tracker's time and GP estimate with its "
        "confidence, whether the task is currently blocked, and its rank if it appears in the "
        "latest ranked run. Use this to find a task by name or by the skill it trains before "
        "asking for its detail."
    ),
    input_schema=_schema(
        {
            "query": {
                "type": "string",
                "description": "Case-insensitive substring matched against name and id.",
            },
            "kind": {
                "type": "string",
                "enum": ["skill_training", "quest", "acquisition", "unlock", "practice"],
                "description": "Restrict to one kind of candidate.",
            },
            "skill": {
                "type": "string",
                "description": "Skill id a candidate must name in its requirement trees.",
            },
            "blocked": {
                "type": "boolean",
                "description": "Restrict to blocked (true) or currently actionable (false) tasks.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SEARCH_RESULTS,
                "description": f"Maximum results, default {MAX_SEARCH_RESULTS}.",
            },
        }
    ),
)


GET_CANDIDATE_DETAIL = ToolSpec(
    name="get_candidate_detail",
    description=(
        "Everything the tracker knows about one candidate: its requirement, completion and "
        "grants-facts trees with each leaf marked satisfied, unsatisfied or unknown against "
        "this account; the tracker's estimate broken into level bands with the training method "
        "selected for each; what currently blocks it; what completing it would unblock, "
        "progress and speed up; and its rank and the engine's own reason if it is ranked."
    ),
    input_schema=_schema(
        {"candidate_id": {"type": "string", "description": "The candidate's id."}},
        ["candidate_id"],
    ),
)


GET_CAPABILITY_DETAIL = ToolSpec(
    name="get_capability_detail",
    description=(
        "One capability in full: its status, what fraction of its requirements are met, its "
        "readiness confidence, whether the tracker recommends using it now and why not if it "
        "does not, any warnings, and its complete requirement tree with each leaf marked "
        "satisfied, unsatisfied or unknown."
    ),
    input_schema=_schema(
        {"capability_id": {"type": "string", "description": "The capability's id."}},
        ["capability_id"],
    ),
)


LIST_TRAINING_METHODS = ToolSpec(
    name="list_training_methods",
    description=(
        "The authored training methods for one skill, optionally narrowed to a level range. "
        "Each carries its XP and GP per hour, level range, any requirements that gate it, and "
        "its descriptive detail — location, target, gear, inventory, notes and wiki link. Gear "
        "and inventory are descriptive only: they gate nothing and affect no tracker estimate. "
        "Returns nothing when the corpus holds no method for that skill, which is common; say "
        "so rather than presenting your own suggestion as the tracker's."
    ),
    input_schema=_schema(
        {
            "skill_id": {"type": "string", "description": "The skill's id, e.g. `magic`."},
            "from_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 99,
                "description": "Only methods usable at or above this level.",
            },
            "to_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 99,
                "description": "Only methods that start at or below this level.",
            },
        },
        ["skill_id"],
    ),
)


GET_QUEST_STATUS = ToolSpec(
    name="get_quest_status",
    description=(
        "Status of quests the account summary does not name. Returns complete, in progress, "
        "not started, or unknown — where unknown means nobody has observed it, which is not the "
        "same as not started."
    ),
    input_schema=_schema(
        {
            "quest_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific quest ids.",
            },
            "name_query": {
                "type": "string",
                "description": "Case-insensitive substring matched against quest names and ids.",
            },
            "status": {
                "type": "string",
                "enum": ["complete", "in_progress", "not_started", "unknown"],
                "description": "Restrict to one status.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_QUEST_RESULTS,
                "description": f"Maximum results, default {MAX_QUEST_RESULTS}.",
            },
        }
    ),
)


GET_SKILL_DETAIL = ToolSpec(
    name="get_skill_detail",
    description=(
        "One skill in depth: current level and XP, whether it is ranked, XP remaining to the "
        "next level and to 99, and which capabilities and ranked candidates depend on it."
    ),
    input_schema=_schema(
        {"skill_id": {"type": "string", "description": "The skill's id, e.g. `slayer`."}},
        ["skill_id"],
    ),
)


GET_ITEM_PRICE = ToolSpec(
    name="get_item_price",
    description=(
        "Cached Old School Wiki prices for items, by id or by name. Each result carries when "
        "the underlying trade happened and when the tracker last fetched it, because a fresh "
        "fetch of stale market data is not a current price. Items absent from the cache are "
        "reported as absent — never guess a price in their place. This reads the cache only "
        "and never triggers a request."
    ),
    input_schema=_schema(
        {
            "item_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Specific item ids.",
            },
            "name_query": {
                "type": "string",
                "description": "Case-insensitive substring matched against item names.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_PRICE_RESULTS,
                "description": f"Maximum results, default {MAX_PRICE_RESULTS}.",
            },
        }
    ),
)


#: The catalogue. Sorted by name and frozen at import — see the module docstring.
TOOLS: Final[tuple[ToolSpec, ...]] = tuple(
    sorted(
        (
            SEARCH_CANDIDATES,
            GET_CANDIDATE_DETAIL,
            GET_CAPABILITY_DETAIL,
            LIST_TRAINING_METHODS,
            GET_QUEST_STATUS,
            GET_SKILL_DETAIL,
            GET_ITEM_PRICE,
        ),
        key=lambda spec: spec.name,
    )
)

TOOL_NAMES: Final[frozenset[str]] = frozenset(spec.name for spec in TOOLS)


def tools_fingerprint() -> str:
    """A stable digest of the catalogue, for §22.3's prefix hash.

    Covers names, descriptions **and** schemas, because a provider renders all three and any of
    them changing invalidates the cached prefix. ``sort_keys`` so a dict literal reordered by an
    editor does not read as a semantic change.
    """
    payload = json.dumps(
        [
            {"name": spec.name, "description": spec.description, "schema": spec.input_schema}
            for spec in TOOLS
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
