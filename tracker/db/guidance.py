"""Reading and writing §21.5's stored guidance.

The caller commits, matching every other module in this package. Serialization lives here
rather than on the DTO so that :mod:`tracker.integrations.llm.types` stays free of any
knowledge that a database exists — the DTO is what a provider returns, and this is what a
table holds.

``body`` is written as a plain dict rather than by ``dataclasses.asdict`` so that adding a
field to :class:`~tracker.integrations.llm.types.GuidanceDTO` cannot silently change the
stored shape. When it does need to change, ``GUIDANCE_SCHEMA_VERSION`` is what makes old rows
stop matching.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from tracker.db.models import GuidanceNote
from tracker.integrations.llm.types import GuidanceDTO, GuidanceStep


def dto_to_body(dto: GuidanceDTO) -> dict[str, Any]:
    """The JSON form of one answer. Field-by-field on purpose — see the module docstring."""
    return {
        "summary": dto.summary,
        "prerequisites": list(dto.prerequisites),
        "steps": [
            {"order": step.order, "title": step.title, "detail": step.detail} for step in dto.steps
        ],
        "warnings": list(dto.warnings),
        "estimated_session_minutes": dto.estimated_session_minutes,
        "uncertain": list(dto.uncertain),
    }


def body_to_dto(note: GuidanceNote) -> GuidanceDTO:
    """Rebuild the answer from a stored row.

    Every field is read with a default. A row written by an older schema version should
    render with whatever it has rather than raise: the version check upstream decides whether
    it is still *usable*, and a note that fails to load is worse than one that loads thin.
    """
    body = note.body or {}
    steps = body.get("steps") or []
    return GuidanceDTO(
        summary=body.get("summary", ""),
        prerequisites=tuple(body.get("prerequisites") or ()),
        steps=tuple(
            GuidanceStep(
                order=int(step.get("order", index)),
                title=step.get("title", ""),
                detail=step.get("detail", ""),
            )
            for index, step in enumerate(steps, start=1)
        ),
        warnings=tuple(body.get("warnings") or ()),
        estimated_session_minutes=body.get("estimated_session_minutes"),
        uncertain=tuple(body.get("uncertain") or ()),
        model=note.model,
        generated_at=note.generated_at,
        input_tokens=note.input_tokens,
        output_tokens=note.output_tokens,
        cache_read_input_tokens=note.cache_read_input_tokens,
    )


def latest_note(
    session: Session,
    player_id: int,
    candidate_id: str,
    *,
    context_hash: str,
    schema_version: int,
    not_before: datetime,
) -> GuidanceNote | None:
    """The most recent still-valid note for this exact prompt, if there is one.

    Three conditions, and they are not redundant. ``context_hash`` is the real one — it moves
    when anything the advice depended on moved. ``schema_version`` catches a change in how the
    stored body is *read*. ``not_before`` catches the case neither can see: a corpus or prompt
    edit that leaves the rendered text byte-identical.
    """
    statement = (
        sa.select(GuidanceNote)
        .where(
            GuidanceNote.player_id == player_id,
            GuidanceNote.candidate_id == candidate_id,
            GuidanceNote.context_hash == context_hash,
            GuidanceNote.schema_version == schema_version,
            GuidanceNote.generated_at >= not_before,
        )
        .order_by(GuidanceNote.generated_at.desc(), GuidanceNote.id.desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def record_note(
    session: Session,
    *,
    player_id: int,
    candidate_id: str,
    context_hash: str,
    schema_version: int,
    dto: GuidanceDTO,
    keep: int,
) -> GuidanceNote:
    """Store one answer and prune the task's history to ``keep`` rows.

    Pruned on write rather than by a background job, the same shape as §6.10's snapshot
    retention: the growth is bounded at the only moment it can grow, and there is no
    scheduler to own.

    **A note for an existing context replaces it rather than being added beside it.** That is
    what ``force`` means: the caller asked for a second opinion on the *same* question, and
    two answers to one question are not a history — they are an ambiguity the reader has no
    way to resolve. History accumulates along the axis that actually moves, which is the
    context hash.

    The caller commits.
    """
    existing = session.scalar(
        sa.select(GuidanceNote).where(
            GuidanceNote.player_id == player_id,
            GuidanceNote.candidate_id == candidate_id,
            GuidanceNote.context_hash == context_hash,
        )
    )
    if existing is not None:
        existing.schema_version = schema_version
        existing.model = dto.model
        existing.generated_at = dto.generated_at
        existing.body = dto_to_body(dto)
        existing.input_tokens = dto.input_tokens
        existing.output_tokens = dto.output_tokens
        existing.cache_read_input_tokens = dto.cache_read_input_tokens
        session.flush()
        _prune(session, player_id=player_id, candidate_id=candidate_id, keep=keep)
        return existing

    note = GuidanceNote(
        player_id=player_id,
        candidate_id=candidate_id,
        context_hash=context_hash,
        schema_version=schema_version,
        model=dto.model,
        generated_at=dto.generated_at,
        body=dto_to_body(dto),
        input_tokens=dto.input_tokens,
        output_tokens=dto.output_tokens,
        cache_read_input_tokens=dto.cache_read_input_tokens,
    )
    session.add(note)
    # Flushed so the new row participates in its own retention window — otherwise a `keep`
    # of 1 would prune the previous note and leave two rows, not one.
    session.flush()
    _prune(session, player_id=player_id, candidate_id=candidate_id, keep=keep)
    return note


def notes_generated_since(session: Session, since: datetime) -> int:
    """How many notes have been written since ``since`` — §21.6's daily ceiling.

    Counted from the stored rows rather than from an in-process counter so that a restart
    does not hand the user a fresh allowance.
    """
    statement = (
        sa.select(sa.func.count())
        .select_from(GuidanceNote)
        .where(GuidanceNote.generated_at >= since)
    )
    return int(session.execute(statement).scalar_one())


def _prune(session: Session, *, player_id: int, candidate_id: str, keep: int) -> None:
    doomed = _stale_ids(session, player_id=player_id, candidate_id=candidate_id, keep=keep)
    if not doomed:
        return
    session.execute(sa.delete(GuidanceNote).where(GuidanceNote.id.in_(doomed)))


def _stale_ids(session: Session, *, player_id: int, candidate_id: str, keep: int) -> Sequence[int]:
    statement = (
        sa.select(GuidanceNote.id)
        .where(
            GuidanceNote.player_id == player_id,
            GuidanceNote.candidate_id == candidate_id,
        )
        .order_by(GuidanceNote.generated_at.desc(), GuidanceNote.id.desc())
        .offset(keep)
    )
    return list(session.execute(statement).scalars())
