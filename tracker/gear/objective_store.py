"""Session-owned, disk-backed complete objective results; never account data."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
import zlib
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, BinaryIO
from uuid import UUID, uuid4


class RunUnavailable(LookupError):
    """The requested run is absent from this server session or account."""


def _lock_session(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _cleanup_orphans(exclude: Path | None = None) -> None:
    """Delete only marked session roots with no active process lock."""
    root = Path(tempfile.gettempdir()).resolve()
    for directory in root.glob("gear-objective-session-*"):
        if directory.is_symlink() or directory.resolve().parent != root:
            continue
        if exclude is not None and directory.resolve() == exclude.resolve():
            continue
        marker = directory / ".owner.json"
        lock = directory / ".session-lock"
        try:
            if marker.is_symlink() or lock.is_symlink() or marker.stat().st_size > 256:
                continue
            owner = json.loads(marker.read_text(encoding="utf-8"))
            if owner.get("owner") != "gear-objective-store" or owner.get("version") != 1:
                continue
            UUID(owner["id"])
            with lock.open("r+b") as handle:
                _lock_session(handle)
            shutil.rmtree(directory)
        except (OSError, ValueError, TypeError, KeyError):
            logging.getLogger(__name__).debug("Session directory is active or not removable")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _summary(identity: str, solution: Mapping[str, Any]) -> dict[str, Any]:
    wilderness = solution.get("wilderness_risk")
    return {
        "id": identity,
        "score": solution["score"],
        "objective_values": solution.get("objective_values", {}),
        "purchase_cost_gp": solution.get("purchase_cost_gp", 0),
        "maximum_actions": solution.get("maximum_actions", 0),
        "max_gear_inventory_slots": solution.get("max_gear_inventory_slots", 0),
        **({"wilderness_loss_gp": wilderness["loss_gp"]} if wilderness is not None else {}),
    }


def _point_summary(summary: Mapping[str, Any], group_id: str) -> dict[str, Any]:
    return {
        **summary,
        "id": f"{group_id}-{summary['id']}",
        "solution_id": summary["id"],
        "group_id": group_id,
    }


def close_result_archives(result: Any) -> None:
    """Release completed raw results even when a stale/disconnected route abandons them."""
    from tracker.gear.vector_publish import FrontierPoints

    if not isinstance(result, Mapping):
        return
    nested = result.get("result")
    if isinstance(nested, Mapping):
        close_result_archives(nested)
    results = (result, *result.get("discipline_results", ()))
    for source in results:
        for group in source.get("objective_frontiers", ()):
            points = group["points"]
            if isinstance(points, FrontierPoints):
                points.close()


@contextmanager
def _archive_sources(result: Mapping[str, Any]) -> Iterator[None]:
    """The publisher consumes branch archives, including cancelled publications."""
    try:
        yield
    finally:
        close_result_archives(result)


class ObjectiveRunStore:
    """Atomic SQLite result publication and bounded compressed-detail cache."""

    def __init__(self, memory_budget_bytes: int = 256 * 1024 * 1024) -> None:
        if memory_budget_bytes < 0:
            raise ValueError("Invalid result cache budget")
        _cleanup_orphans()
        self._temporary = tempfile.TemporaryDirectory(prefix="gear-objective-session-")
        self.directory = Path(self._temporary.name)
        (self.directory / ".owner.json").write_text(
            _json({"owner": "gear-objective-store", "version": 1, "id": str(uuid4())}),
            encoding="utf-8",
        )
        self._session_lock = (self.directory / ".session-lock").open("w+b")
        self._session_lock.write(b"0")
        self._session_lock.flush()
        _lock_session(self._session_lock)
        self._connection = sqlite3.connect(
            self.directory / "results.sqlite", check_same_thread=False
        )
        self._connection.execute("PRAGMA cache_size=-2048")
        self._connection.execute("PRAGMA temp_store=FILE")
        self._connection.executescript("""
            CREATE TABLE runs (id TEXT PRIMARY KEY, player TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE solutions (
                run TEXT NOT NULL, id TEXT NOT NULL, report BLOB NOT NULL, summary TEXT NOT NULL,
                PRIMARY KEY(run,id));
            CREATE TABLE groups (
                run TEXT NOT NULL, id TEXT NOT NULL, metadata TEXT NOT NULL, PRIMARY KEY(run,id));
            CREATE TABLE members (
                run TEXT NOT NULL, group_id TEXT NOT NULL, solution TEXT NOT NULL,
                PRIMARY KEY(run,group_id,solution));
            CREATE INDEX member_groups ON members(run,group_id);
        """)
        self._lock = RLock()
        self._closed = False
        self._budget = memory_budget_bytes
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._cache_bytes = 0
        self._contexts: dict[str, Any] = {}
        self._reads: OrderedDict[str, deque[float]] = OrderedDict()

    def __enter__(self) -> ObjectiveRunStore:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._cache.clear()
                self._contexts.clear()
                self._cache_bytes = 0
                self._closed = True
                self._session_lock.close()
                self._temporary.cleanup()

    def _run(self, run_id: str, player_id: str | int) -> dict[str, Any]:
        if self._closed:
            raise RunUnavailable("Optimization run is no longer available; rerun optimization")
        row = self._connection.execute(
            "SELECT metadata FROM runs WHERE id=? AND player=?", (run_id, str(player_id))
        ).fetchone()
        if row is None:
            raise RunUnavailable("Optimization run is no longer available; rerun optimization")
        return json.loads(row[0])  # type: ignore[no-any-return]

    def publish_result(
        self,
        result: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any],
        player_id: str | int,
        cancelled: Callable[[], bool] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Detach every report before committing; cancellation leaves no partial run."""
        run_id = str(uuid4())
        definitions = json.loads(_json(result.get("objective_definitions", [])))
        groups: list[dict[str, Any]] = []
        published: list[dict[str, Any]] = []

        def check() -> None:
            if cancelled is not None and cancelled():
                raise ValueError("optimization_cancelled")

        with self._lock, self._connection, _archive_sources(result):
            check()
            references = {}

            def reference(alias: str, solution: Any) -> None:
                if solution is not None:
                    check()
                    references[alias] = self._put_solution(run_id, solution)

            reference("best-found", result.get("selected_solution"))
            for point in result.get("curve", ()):
                reference(f"curve-{point['swap_limit']}", point.get("solution"))
            reference("unrestricted", result.get("unrestricted"))
            published, groups = self._publish_groups(
                run_id, result.get("objective_frontiers", []), "global", definitions, check
            )
            children = []
            for child in result.get("discipline_results", []):
                name = str(child.get("discipline", "unknown"))
                reference(f"discipline-{name}-best-found", child.get("selected_solution"))
                view = "discipline-" + name
                child_groups, child_metadata = self._publish_groups(
                    run_id, child.get("objective_frontiers", []), view, definitions, check
                )
                children.append({**child, "objective_frontiers": child_groups})
                groups.extend(child_metadata)
            manifest = {
                **metadata,
                "run_id": run_id,
                "objective_definitions": definitions,
                "groups": groups,
                "selected_solution_id": references.get("best-found"),
                "solution_references": references,
            }
            check()
            self._connection.execute(
                "INSERT INTO runs VALUES(?,?,?)", (run_id, str(player_id), _json(manifest))
            )
        if context is not None:
            self.set_context(run_id, player_id=player_id, context=context)
        return {
            **result,
            "run_id": run_id,
            "objective_run": manifest,
            "objective_frontiers": published,
            **({"discipline_results": children} if "discipline_results" in result else {}),
        }

    def _publish_groups(
        self,
        run_id: str,
        input_groups: Any,
        view: str,
        definitions: list[dict[str, Any]],
        check: Callable[[], None],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        published, groups = [], []
        for index, group in enumerate(input_groups):
            check()
            group_id = f"frontier-{view}-{index}"
            for point in group["points"]:
                check()
                solution_id = self._put_solution(run_id, point["solution"])
                self._connection.execute(
                    "INSERT OR IGNORE INTO members VALUES(?,?,?)",
                    (run_id, group_id, solution_id),
                )
            total = self._connection.execute(
                "SELECT count(*) FROM members WHERE run=? AND group_id=?", (run_id, group_id)
            ).fetchone()[0]
            sample = self._sample_group(run_id, group_id, definitions, check)
            summaries, chart_points = [], []
            baseline = group.get("baseline_dps")
            for key in sample:
                blob, summary = self._connection.execute(
                    "SELECT report,summary FROM solutions WHERE run=? AND id=?", (run_id, key)
                ).fetchone()
                solution = json.loads(zlib.decompress(blob))
                summaries.append(_point_summary(json.loads(summary), group_id))
                chart_points.append(
                    {
                        "id": f"{group_id}-{key}",
                        "solution_id": key,
                        "solution": solution,
                        "dps_loss": baseline - solution["score"] if baseline is not None else 0,
                        "dps_loss_pct": 100 * (baseline - solution["score"]) / baseline
                        if baseline
                        else None,
                    }
                )
            info = {
                "id": group_id,
                "group_id": group_id,
                "view": view,
                "swap_limit": group["swap_limit"],
                "baseline_dps": baseline,
                "total_count": total,
                "sampled": total > len(sample),
            }
            published.append({**group, **info, "points": chart_points})
            groups.append({**info, "points": summaries})
            self._connection.execute(
                "INSERT INTO groups VALUES(?,?,?)", (run_id, group_id, _json(info))
            )
        return published, groups

    def allow_read(self, client: str) -> bool:
        """Bound inexpensive archive reads without growing per-client state forever."""
        with self._lock:
            now = monotonic()
            events = self._reads.pop(client, deque())
            while events and now - events[0] >= 60:
                events.popleft()
            allowed = len(events) < 120
            if allowed:
                events.append(now)
            self._reads[client] = events
            while len(self._reads) > 1024:
                self._reads.popitem(last=False)
            return allowed

    def update_metadata(
        self, run_id: str, *, player_id: str | int, metadata: Mapping[str, Any]
    ) -> None:
        with self._lock, self._connection:
            current = self._run(run_id, player_id)
            updated = {**current, **metadata, "run_id": run_id}
            self._connection.execute(
                "UPDATE runs SET metadata=? WHERE id=?", (_json(updated), run_id)
            )

    def set_context(self, run_id: str, *, player_id: str | int, context: Mapping[str, Any]) -> None:
        """Retain frozen reporting inputs, never a mutable optimizer or native context."""
        from types import MappingProxyType

        with self._lock:
            self._run(run_id, player_id)
            self._contexts[run_id] = MappingProxyType(dict(context))

    def get_context(self, run_id: str, *, player_id: str | int) -> Mapping[str, Any]:
        with self._lock:
            self._run(run_id, player_id)
            context: Mapping[str, Any] | None = self._contexts.get(run_id)
            if context is None:
                raise RunUnavailable("Frozen reporting inputs are no longer available")
            return context

    def _put_solution(self, run_id: str, solution: Mapping[str, Any]) -> str:
        report = _json(solution).encode()
        identity = "objective-" + hashlib.sha256(report).hexdigest()[:24]
        self._connection.execute(
            "INSERT OR IGNORE INTO solutions VALUES(?,?,?,?)",
            (run_id, identity, zlib.compress(report), _json(_summary(identity, solution))),
        )
        return identity

    def _sample_group(
        self,
        run_id: str,
        group_id: str,
        definitions: list[dict[str, Any]],
        check: Callable[[], None],
    ) -> list[str]:
        """Disk-backed normalized farthest-point selection; RAM is O(axes * 128)."""
        db = self._connection
        db.execute("DROP TABLE IF EXISTS temp.sample_points")
        db.execute(
            "CREATE TEMP TABLE sample_points(id TEXT PRIMARY KEY, summary TEXT, distance REAL)"
        )
        try:
            db.execute(
                "INSERT INTO sample_points SELECT s.id,s.summary,1e300 FROM solutions s "
                "JOIN members m ON s.run=m.run AND s.id=m.solution WHERE m.run=? AND m.group_id=?",
                (run_id, group_id),
            )
            count = db.execute("SELECT count(*) FROM sample_points").fetchone()[0]
            if count <= 128:
                return [row[0] for row in db.execute("SELECT id FROM sample_points ORDER BY id")]
            paths = [
                "$.score",
                *['$.objective_values."' + d["id"].replace('"', '\\"') + '"' for d in definitions],
            ]
            bounds = [
                db.execute(
                    "SELECT min(json_extract(summary,?)),max(json_extract(summary,?)) "
                    "FROM sample_points",
                    (path, path),
                ).fetchone()
                for path in paths
            ]
            selected: list[str] = []
            for path in paths:
                for direction in ("ASC", "DESC"):
                    identity = db.execute(
                        "SELECT id FROM sample_points ORDER BY json_extract(summary,?) "
                        + direction
                        + ",id LIMIT 1",
                        (path,),
                    ).fetchone()[0]
                    if identity not in selected:
                        selected.append(identity)
            pending = list(selected)
            keys = [d["id"] for d in definitions]
            while len(selected) < 128:
                for identity in pending:
                    check()
                    reference = json.loads(
                        db.execute(
                            "SELECT summary FROM sample_points WHERE id=?", (identity,)
                        ).fetchone()[0]
                    )
                    vector = [
                        reference["score"],
                        *[reference["objective_values"][key] for key in keys],
                    ]

                    def distance(text: str, reference_vector: list[float] = vector) -> float:
                        row = json.loads(text)
                        values = [row["score"], *[row["objective_values"][key] for key in keys]]
                        return sum(
                            ((a - b) / (hi - lo)) ** 2 if hi != lo else 0.0
                            for a, b, (lo, hi) in zip(values, reference_vector, bounds, strict=True)
                        )

                    db.create_function("objective_distance", 1, distance)
                    db.execute(
                        "UPDATE sample_points SET distance="
                        "min(distance,objective_distance(summary))"
                    )
                    db.execute("UPDATE sample_points SET distance=-1 WHERE id=?", (identity,))
                candidate = db.execute(
                    "SELECT id FROM sample_points ORDER BY distance DESC,id LIMIT 1"
                ).fetchone()[0]
                selected.append(candidate)
                pending = [candidate]
            return selected
        finally:
            db.create_function("objective_distance", 1, None)
            db.execute("DROP TABLE IF EXISTS temp.sample_points")

    def metadata(self, run_id: str, *, player_id: str | int) -> dict[str, Any]:
        with self._lock:
            return self._run(run_id, player_id)

    def page(
        self,
        run_id: str,
        group_id: str,
        *,
        player_id: str | int,
        sort: str = "dps",
        direction: str = "desc",
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            metadata = self._run(run_id, player_id)
            kinds = {row["id"] for row in metadata["objective_definitions"]}
            fields = {
                "dps": "score",
                "score": "score",
                "purchase_cost_gp": "purchase_cost_gp",
                "maximum_actions": "maximum_actions",
                "max_gear_inventory_slots": "max_gear_inventory_slots",
            }
            if (metadata.get("scenario") or {}).get("wilderness") is not None:
                fields["wilderness_loss_gp"] = "wilderness_loss_gp"
            if (
                sort not in kinds | fields.keys()
                or direction not in {"asc", "desc"}
                or not 1 <= limit <= 100
            ):
                raise ValueError("Invalid objective result ordering or page size")
            if (
                self._connection.execute(
                    "SELECT 1 FROM groups WHERE run=? AND id=?", (run_id, group_id)
                ).fetchone()
                is None
            ):
                raise RunUnavailable("Optimization frontier is no longer available")
            offset = 0
            if cursor:
                try:
                    data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                    if (
                        not isinstance(data, list)
                        or len(data) != 5
                        or data[:4] != [run_id, group_id, sort, direction]
                        or type(data[4]) is not int
                        or not 0 <= data[4] <= 2**63 - 1
                    ):
                        raise ValueError
                    offset = data[4]
                except (ValueError, TypeError, IndexError, UnicodeError, RecursionError) as exc:
                    raise ValueError("Invalid objective result cursor") from exc
            path = (
                "$." + fields[sort]
                if sort in fields
                else '$.objective_values."' + sort.replace('"', '\\"') + '"'
            )
            rows = self._connection.execute(
                "SELECT s.summary FROM solutions s JOIN members m "
                "ON s.run=m.run AND s.id=m.solution "
                "WHERE m.run=? AND m.group_id=? ORDER BY json_extract(s.summary,?) "
                + ("ASC" if direction == "asc" else "DESC")
                + ",s.id ASC LIMIT ? OFFSET ?",
                (run_id, group_id, path, limit, offset),
            ).fetchall()
            total = self._connection.execute(
                "SELECT count(*) FROM members WHERE run=? AND group_id=?", (run_id, group_id)
            ).fetchone()[0]
            next_offset = offset + len(rows)
            next_cursor = (
                None
                if next_offset >= total
                else base64.urlsafe_b64encode(
                    _json([run_id, group_id, sort, direction, next_offset]).encode()
                ).decode()
            )
            return {
                "points": [_point_summary(json.loads(row[0]), group_id) for row in rows],
                "total": total,
                "next_cursor": next_cursor,
            }

    def solution(self, run_id: str, solution_id: str, *, player_id: str | int) -> dict[str, Any]:
        with self._lock:
            self._run(run_id, player_id)
            if not solution_id.startswith("objective-"):
                member = self._connection.execute(
                    "SELECT solution FROM members WHERE run=? AND group_id||'-'||solution=?",
                    (run_id, solution_id),
                ).fetchone()
                if member is None:
                    raise RunUnavailable("Optimization solution is no longer available")
                solution_id = member[0]
            key = (run_id, solution_id)
            report = self._cache.get(key)
            if report is None:
                row = self._connection.execute(
                    "SELECT report FROM solutions WHERE run=? AND id=?", key
                ).fetchone()
                if row is None:
                    raise RunUnavailable("Optimization solution is no longer available")
                report = bytes(row[0])
                if len(report) <= self._budget:
                    while self._cache and self._cache_bytes + len(report) > self._budget:
                        _, old = self._cache.popitem(last=False)
                        self._cache_bytes -= len(old)
                    self._cache[key] = report
                    self._cache_bytes += len(report)
            else:
                self._cache.move_to_end(key)
            return {"solution": json.loads(zlib.decompress(report))}
