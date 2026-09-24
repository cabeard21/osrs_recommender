"""Standalone, versioned factual content. Never loads the recommendation corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tracker.content.requirements import QuestLeaf, Requirement, iter_leaves, parse


class QuestDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str
    counts_for_cape: bool
    requires: Requirement | None = None
    # None means reward information has not been verified, never a guessed zero.
    quest_points: int | None = Field(default=None, ge=0)
    requirements_verified: bool = False
    unmodeled: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    wiki_url: str
    revision: int | None = None
    # A terminal chapter may finish a parent quest, without completing any prerequisites.
    completes_parent: str | None = None
    staged_rewards: bool = False

    @field_validator("requires", mode="before")
    @classmethod
    def requirement(cls, value: Any) -> Any:
        if value is None or not isinstance(value, dict) or "type" in value:
            return value
        return parse(value)

    @property
    def prerequisites(self) -> tuple[str, ...]:
        if self.requires is None:
            return ()
        return tuple(
            sorted({n.quest_id for n in iter_leaves(self.requires) if isinstance(n, QuestLeaf)})
        )


class QuestCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str
    source: str
    quests: tuple[QuestDefinition, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> QuestCatalog:
        index = self.index()
        if len(index) != len(self.quests):
            raise ValueError("duplicate quest identity")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key not in index:
                raise ValueError(f"unresolved prerequisite: {key}")
            if key in visiting:
                raise ValueError(f"quest prerequisite cycle: {key}")
            if key in visited:
                return
            visiting.add(key)
            for parent in index[key].prerequisites:
                visit(parent)
            visiting.remove(key)
            visited.add(key)

        for quest in self.quests:
            visit(quest.id)
            if quest.completes_parent is not None and quest.completes_parent not in index:
                raise ValueError(f"missing parent for {quest.id}")
        return self

    def index(self) -> dict[str, QuestDefinition]:
        return {q.id: q for q in self.quests}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def relevant_ids(self) -> frozenset[str]:
        index = self.index()
        relevant: set[str] = set()

        def add(key: str) -> None:
            if key in relevant:
                return
            relevant.add(key)
            for parent in index[key].prerequisites:
                add(parent)

        for quest in self.quests:
            if quest.counts_for_cape:
                add(quest.id)
        return frozenset(relevant)


def load_catalog(path: Path) -> QuestCatalog:
    return QuestCatalog.model_validate_json(path.read_text(encoding="utf-8"))
