"""Exact Pareto archives over raw complete-configuration objective vectors."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from functools import wraps
from typing import Any, cast

from tracker.gear.objectives import MINIMIZED_OBJECTIVES
from tracker.gear.vector_session import archive_directory, receive_archive

_OWNERS: ContextVar[list[VectorArchive] | None] = ContextVar("vector_archive_owners", default=None)
_INDEX_CAPACITY_BYTES = 64 * 1024 * 1024


def adopt_vector_archives(value: Any) -> None:
    """Adopt worker-returned files on the caller's scope, after IPC unpickling."""
    owners = _OWNERS.get()
    if owners is None:
        return
    archive = getattr(value, "archive", None)
    if isinstance(archive, VectorArchive):
        if all(previous.path != archive.path for previous in owners):
            owners.append(archive)
    elif isinstance(value, Mapping):
        for child in value.values():
            adopt_vector_archives(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            adopt_vector_archives(child)


def own_vector_archives[**Parameters, Result](
    function: Callable[Parameters, Result],
) -> Callable[Parameters, Result]:
    """Transfer only result-reachable archive files; close every file on failure."""

    @wraps(function)
    def owned(*args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        if _OWNERS.get() is not None:
            return function(*args, **kwargs)
        archives: list[VectorArchive] = []
        token = _OWNERS.set(archives)
        try:
            result = function(*args, **kwargs)
            reachable: set[str] = set()

            def visit(value: Any) -> None:
                archive = getattr(value, "archive", None)
                if isinstance(archive, VectorArchive):
                    archive.flush()
                    reachable.add(archive.path)
                elif isinstance(value, Mapping):
                    for child in value.values():
                        visit(child)
                elif isinstance(value, (list, tuple)):
                    for child in value:
                        visit(child)

            visit(result)
            for archive in archives:
                if archive.path not in reachable:
                    archive.close()
            return result
        except BaseException:
            for archive in archives:
                archive.close()
            raise
        finally:
            _OWNERS.reset(token)

    return owned


def dominates(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    if len(left) != len(right):
        raise ValueError("Objective vector dimensions do not match")
    return all(a >= b for a, b in zip(left, right, strict=True)) and any(
        a > b for a, b in zip(left, right, strict=True)
    )


def solution_vector(
    solution: Mapping[str, Any], objective_ids: tuple[str, ...]
) -> tuple[float, ...]:
    return (
        float(solution["score"]),
        *(
            (-1 if key in MINIMIZED_OBJECTIVES else 1) * float(solution["objective_values"][key])
            for key in objective_ids
        ),
    )


def solution_identity(solution: Mapping[str, Any]) -> str:
    identity = {
        "loadouts": {
            key: {
                field: row.get(field)
                for field in ("equipment", "combat_option", "selected_prayer_ids", "discipline")
            }
            for key, row in solution["loadouts"].items()
        },
        "potions": solution.get("potions"),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class VectorArchive:
    """Disk-backed exact archive; rich reports never accumulate in process memory.

    Equal objective vectors retain the existing resource-tie representative.
    The database is portable across worker IPC; its consumer explicitly closes it.
    """

    def __init__(self, objective_ids: tuple[str, ...]) -> None:
        self.objective_ids = objective_ids
        descriptor, self.path = tempfile.mkstemp(
            prefix="gear-vector-", suffix=".sqlite3", dir=archive_directory()
        )
        os.close(descriptor)
        self._connection: sqlite3.Connection | None = None
        self._committed_changes = 0
        self._native_index: Any = None
        owners = _OWNERS.get()
        if owners is not None:
            owners.append(self)
        columns = ",".join(f"v{index} REAL NOT NULL" for index in range(len(objective_ids) + 1))
        self.connection.execute(
            f"CREATE TABLE candidates(identity TEXT PRIMARY KEY,{columns},report TEXT NOT NULL)"
        )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.path, isolation_level="DEFERRED", check_same_thread=False
            )
            self._committed_changes = 0
            self._connection.execute("PRAGMA cache_size=-2048")
            self._connection.execute("PRAGMA journal_mode=OFF")
            # Search archives are disposable session files, deleted on failure.
            # Flush-on-commit durability would synchronize every seen-candidate
            # update to disk; account and persistent application DBs retain
            # their own independent connection settings.
            self._connection.execute("PRAGMA synchronous=OFF")
        elif (
            self._connection.in_transaction
            and self._connection.total_changes - self._committed_changes >= 4096
        ):
            self.flush()
        return self._connection

    def flush(self) -> None:
        """Publish the current bounded write batch before handing the file to another reader."""
        if self._connection is not None:
            self._connection.commit()
            self._committed_changes = self._connection.total_changes

    def __getstate__(self) -> dict[str, Any]:
        # IPC consumers rehome the file, so Windows must have no writer handle open.
        if self._connection is not None:
            self.flush()
            self._connection.close()
            self._connection = None
        return {"objective_ids": self.objective_ids, "path": self.path, "_connection": None}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update({**state, "path": receive_archive(state["path"])})
        self._native_index = None

    def enable_native_index(self) -> None:
        """Mirror the numeric frontier in an ephemeral native index."""
        from tracker.gear.native._frontier import ArchiveIndex

        if len(self) > self._native_row_capacity:
            self._disable_native_index("capacity")
            return
        try:
            index = ArchiveIndex(len(self.objective_ids) + 1)
            for _, identity, *vector in self.numeric_rows():
                index.insert(identity, vector)
        except ValueError:
            self._disable_native_index("numeric_range")
            return
        self._native_index = index

    @property
    def _native_row_capacity(self) -> int:
        # Include the digest, vector storage, container entries, and allocator overhead.
        return _INDEX_CAPACITY_BYTES // (256 + 8 * (len(self.objective_ids) + 1))

    @property
    def native_candidate_index(self) -> Any:
        return self._native_index

    def _disable_native_index(self, reason: str) -> None:
        from tracker.gear.native import record

        self._native_index = None
        record("fallback", reason=f"native_archive_index_{reason}")

    def numeric_rows(
        self, minimum_dps: float | None = None, maximum_actions: int | None = None
    ) -> Iterator[tuple[Any, ...]]:
        """Read compact rows in exactly the order used by frontier publication."""
        names = tuple(f"v{index}" for index in range(len(self.objective_ids) + 1))
        order = ",".join(f"{name} DESC" for name in names)
        tests, parameters = [], []
        if minimum_dps is not None:
            tests.append("v0>=?")
            parameters.append(minimum_dps)
        if maximum_actions is not None:
            tests.append("json_extract(report,'$.maximum_actions')<=?")
            parameters.append(maximum_actions)
        condition = " WHERE " + " AND ".join(tests) if tests else ""
        yield from self.connection.execute(
            f"SELECT rowid,identity,{','.join(names)} FROM candidates{condition} "
            f"ORDER BY {order},identity",
            parameters,
        )

    def max_actions(self) -> int:
        """Upper bound on the action count of every row in this backing archive."""
        return int(
            self.connection.execute(
                "SELECT COALESCE(MAX(json_extract(report,'$.maximum_actions')),0) FROM candidates"
            ).fetchone()[0]
        )

    def raw_report(self, rowid: int) -> str:
        return cast(
            str,
            self.connection.execute(
                "SELECT report FROM candidates WHERE rowid=?", (rowid,)
            ).fetchone()[0],
        )

    def write_survivors(self, rows: Iterator[tuple[Any, ...]]) -> None:
        """Insert proven distinct, nondominated rows into a new archive."""
        placeholders = ",".join("?" for _ in range(len(self.objective_ids) + 3))
        self.connection.executemany(f"INSERT INTO candidates VALUES({placeholders})", rows)

    def add(self, solution: Mapping[str, Any]) -> bool:
        if any(solution["objective_values"].get(key) is None for key in self.objective_ids):
            return False
        identity = solution_identity(solution)
        vector = solution_vector(solution, self.objective_ids)
        names = tuple(f"v{index}" for index in range(len(vector)))
        equal = " AND ".join(f"{name}=?" for name in names)
        previous = self.connection.execute(
            f"SELECT identity,report FROM candidates WHERE {equal}", vector
        ).fetchone()
        if previous is not None:
            if resource_tie(json.loads(previous[1])) <= resource_tie(solution):
                return False
            self.connection.execute("DELETE FROM candidates WHERE identity=?", (previous[0],))
            if self._native_index is not None:
                self._native_index.discard(previous[0])
        if self.strictly_dominated(vector):
            return False
        lesser = " AND ".join(f"{name}<=?" for name in names)
        strict_less = " OR ".join(f"{name}<?" for name in names)
        self.connection.execute(
            f"DELETE FROM candidates WHERE {lesser} AND ({strict_less})", (*vector, *vector)
        )
        parameters = ",".join("?" for _ in range(len(vector) + 2))
        self.connection.execute(
            f"INSERT OR REPLACE INTO candidates VALUES({parameters})",
            (identity, *vector, json.dumps(solution, sort_keys=True, separators=(",", ":"))),
        )
        if self._native_index is not None:
            self._native_index.remove_dominated(vector)
            self._native_index.insert(identity, vector)
            if len(self._native_index) > self._native_row_capacity:
                self._disable_native_index("capacity")
        return True

    def solutions(self) -> list[dict[str, Any]]:
        return list(self.iter_solutions())

    def iter_solutions(self, minimum_dps: float | None = None) -> Iterator[dict[str, Any]]:
        for _, solution in self.iter_identified_solutions(minimum_dps):
            yield solution

    def iter_identified_solutions(
        self, minimum_dps: float | None = None
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        order = ",".join(f"v{index} DESC" for index in range(len(self.objective_ids) + 1))
        condition = " WHERE v0>=?" if minimum_dps is not None else ""
        parameters = (minimum_dps,) if minimum_dps is not None else ()
        for identity, report in self.connection.execute(
            f"SELECT identity,report FROM candidates{condition} ORDER BY {order},identity",
            parameters,
        ):
            yield identity, json.loads(report)

    def __len__(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])

    def count(self, minimum_dps: float | None = None) -> int:
        if minimum_dps is None:
            return len(self)
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM candidates WHERE v0>=?", (minimum_dps,)
            ).fetchone()[0]
        )

    def baseline_dps(self) -> float:
        return float(self.connection.execute("SELECT MAX(v0) FROM candidates").fetchone()[0] or 0)

    def strictly_dominated(self, vector: tuple[float, ...]) -> bool:
        if self._native_index is not None:
            try:
                return bool(self._native_index.strictly_dominated(vector))
            except ValueError:
                self._disable_native_index("numeric_range")
        names = tuple(f"v{index}" for index in range(len(vector)))
        greater = " AND ".join(f"{name}>=?" for name in names)
        strict = " OR ".join(f"{name}>?" for name in names)
        return (
            self.connection.execute(
                f"SELECT 1 FROM candidates WHERE {greater} AND ({strict}) LIMIT 1",
                (*vector, *vector),
            ).fetchone()
            is not None
        )

    def close(self) -> None:
        self._native_index = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if os.path.exists(self.path):
            os.unlink(self.path)


def resource_tie(solution: Mapping[str, Any]) -> tuple[Any, ...]:
    potions = solution.get("potions") or {}
    return (
        solution.get("max_gear_inventory_slots", 0),
        solution.get("purchase_cost_gp", 0),
        len(solution.get("unowned_untradeable_item_ids", ())),
        sum(transition["action_count"] for transition in solution.get("transitions", ())),
        potions.get("cost_per_application_gp") is None,
        potions.get("cost_per_application_gp") or 0,
        len(potions.get("selected_ids", ())),
        solution.get("distinct_items", 0)
        if "gp_per_damage" in solution.get("objective_values", {})
        else 0,
        json.dumps(solution["loadouts"], sort_keys=True),
        solution_identity(solution),
    )
