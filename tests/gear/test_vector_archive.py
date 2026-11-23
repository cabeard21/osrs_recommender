"""Exact arbitrary-dimensional dominance and configuration identity."""

import pytest

from tracker.gear.vector_archive import VectorArchive, dominates


def row(name, dps, first, second, actions=0):
    return {
        "score": dps,
        "objective_values": {"a": first, "b": second},
        "maximum_actions": actions,
        "loadouts": {"r": {"equipment": {"head": name}}},
        "potions": None,
    }


def test_archive_keeps_interior_and_resource_representative_for_equal_vectors():
    archive = VectorArchive(("a", "b"))
    for solution in [row(1, 10, 1, 9), row(2, 10, 9, 1), row(3, 10, 6, 6), row(4, 10, 6, 6)]:
        archive.add(solution)
    assert len(archive.solutions()) == 3
    assert not archive.add(row(3, 10, 6, 6))
    assert archive.add(row(5, 10, 7, 7))
    assert len(archive.solutions()) == 3
    assert dominates((10, 7, 7), (10, 6, 6))
    assert not dominates((10, 7, 7), (10, 7, 7))


def test_archive_order_does_not_change_membership():
    candidates = [row(1, 9, 9, 1), row(2, 10, 6, 6), row(3, 8, 2, 2)]
    first, second = VectorArchive(("a", "b")), VectorArchive(("a", "b"))
    for candidate in candidates:
        first.add(candidate)
    for candidate in reversed(candidates):
        second.add(candidate)
    assert first.solutions() == second.solutions()


def test_live_native_index_tracks_equal_replacements_and_dominated_deletions():
    pytest.importorskip("tracker.gear.native._frontier")
    native, reference = VectorArchive(("a", "b")), VectorArchive(("a", "b"))
    try:
        initial = row(2, 10, 5, 5)
        for archive in (native, reference):
            archive.add(initial)
        native.enable_native_index()
        for candidate in (
            row(3, 10, 5, 5),
            row(1, 10, 5, 5),
            row(1, 11, 2, 2),
            row(3, 9, 4, 4),
            row(4, 12, 4, 4),
            row(5, 10, 4, 4),
        ):
            assert native.add(candidate) == reference.add(candidate)
            assert native.solutions() == reference.solutions()
            for sample in ((9, 3, 3), (10, 5, 5), (10, 3, 3), (12, 4, 4)):
                assert native.strictly_dominated(sample) == reference.strictly_dominated(sample)
    finally:
        native.close()
        reference.close()


def test_native_archive_updates_use_primary_keys():
    pytest.importorskip("tracker.gear.native._frontier")
    from tracker.gear.vector_archive import solution_identity

    archive = VectorArchive(("a", "b"))
    try:
        archive.enable_native_index()
        trace = []
        archive.connection.set_trace_callback(trace.append)
        left = row(2, 10, 1, 9)
        right = row(3, 10, 9, 1)
        assert archive.add(left)
        assert archive.add(right)
        assert not any(statement.startswith("SELECT") for statement in trace)

        interior = row(4, 10, 9, 9)
        assert archive.add(interior)
        assert {statement for statement in trace if statement.startswith("DELETE")} == {
            f"DELETE FROM candidates WHERE identity='{solution_identity(left)}'",
            f"DELETE FROM candidates WHERE identity='{solution_identity(right)}'",
        }

        trace.clear()
        replacement = row(1, 10, 9, 9)
        assert archive.add(replacement)
        reads = [statement for statement in trace if statement.startswith("SELECT")]
        assert len(reads) == 1
        assert reads[0].endswith(f"WHERE identity='{solution_identity(interior)}'")
        assert archive.solutions() == [replacement]
    finally:
        archive.close()


def test_native_archive_keeps_sql_membership_after_capacity_fallback(monkeypatch):
    pytest.importorskip("tracker.gear.native._frontier")
    monkeypatch.setattr(VectorArchive, "_native_row_capacity", 1)
    archive = VectorArchive(("a", "b"))
    try:
        archive.enable_native_index()
        assert archive.add(row(1, 10, 1, 9))
        assert archive.native_candidate_index is not None
        assert archive.add(row(2, 10, 9, 1))
        assert archive.native_candidate_index is None
        winner = row(3, 10, 9, 9)
        assert archive.add(winner)
        assert archive.solutions() == [winner]
    finally:
        archive.close()


def test_native_archive_uses_sql_when_probe_rejects_numeric_range():
    pytest.importorskip("tracker.gear.native._frontier")
    native, reference = VectorArchive(("a", "b")), VectorArchive(("a", "b"))
    try:
        native.enable_native_index()
        for candidate in (row(1, 10, 2, 2), row(2, 10, float("inf"), 2), row(3, 10, 3, 2)):
            assert native.add(candidate) == reference.add(candidate)
            assert native.solutions() == reference.solutions()
        assert native.native_candidate_index is None
    finally:
        native.close()
        reference.close()


def test_native_archive_is_discarded_after_insert_failure():
    import sqlite3
    from pathlib import Path

    pytest.importorskip("tracker.gear.native._frontier")
    from tracker.gear.vector_archive import own_vector_archives

    @own_vector_archives
    def fail_after_deleting_dominated_row():
        archive = VectorArchive(("a", "b"))
        archives.append(Path(archive.path))
        archive.enable_native_index()
        assert archive.add(row(1, 10, 1, 1))
        archive.connection.execute(
            "CREATE TRIGGER insert_failure BEFORE INSERT ON candidates "
            "WHEN NOT EXISTS (SELECT 1 FROM candidates) "
            "BEGIN SELECT RAISE(FAIL, 'archive insert failed'); END"
        )
        archive.add(row(2, 10, 2, 2))

    archives = []
    with pytest.raises(sqlite3.IntegrityError, match="archive insert failed"):
        fail_after_deleting_dominated_row()
    assert archives and not archives[0].exists()


def test_equal_potion_resource_ties_do_not_depend_on_branch_completion_order():
    first, second = VectorArchive(("a", "b")), VectorArchive(("a", "b"))
    candidates = [
        {**row(1, 10, 2, 3), "potions": {"selected_ids": [name], "cost_per_application_gp": None}}
        for name in ("magic", "super_magic")
    ]
    for candidate in candidates:
        first.add(candidate)
    for candidate in reversed(candidates):
        second.add(candidate)
    assert first.solutions() == second.solutions()
    first.close()
    second.close()


def test_adopted_worker_archive_is_removed_if_parent_scope_fails():
    import os

    import pytest

    from tracker.gear.vector_archive import adopt_vector_archives, own_vector_archives
    from tracker.gear.vector_publish import FrontierPoints

    archive = VectorArchive(("a", "b"))
    points = FrontierPoints(archive, 0)

    @own_vector_archives
    def operation():
        adopt_vector_archives({"points": points})
        raise ValueError("optimization_cancelled")

    with pytest.raises(ValueError, match="optimization_cancelled"):
        operation()
    assert not os.path.exists(archive.path)


def test_temporary_archive_disables_per_write_durability_on_every_connection():
    import pickle
    import sqlite3

    from tracker.gear.vector_archive import solution_identity

    archive = VectorArchive(("a", "b"))
    ordinary = sqlite3.connect(":memory:")
    try:
        # This setting belongs only to the disposable search archive; another
        # SQLite connection retains its normal durability mode.
        assert archive.connection.execute("PRAGMA synchronous").fetchone()[0] == 0
        assert ordinary.execute("PRAGMA synchronous").fetchone()[0] == 2
        candidates = [row(1, 10, 1, 9), row(2, 10, 9, 1), row(3, 10, 6, 6)]
        for candidate in candidates:
            archive.add(candidate)
        expected = [solution_identity(candidate) for candidate in archive.solutions()]
        transferred = pickle.loads(pickle.dumps(archive))
        assert transferred.connection.execute("PRAGMA synchronous").fetchone()[0] == 0
        assert [solution_identity(candidate) for candidate in transferred.solutions()] == expected
        transferred.connection.close()
        transferred._connection = None
        assert transferred.connection.execute("PRAGMA synchronous").fetchone()[0] == 0
        assert [solution_identity(candidate) for candidate in transferred.solutions()] == expected
        transferred.close()
    finally:
        ordinary.close()
        archive.close()


def test_archive_batches_writes_and_flushes_before_independent_readers():
    import sqlite3
    from contextlib import closing

    archive = VectorArchive(("a", "b"))
    try:
        archive.add(row(1, 10, 1, 9))
        assert archive.connection.in_transaction
        archive.flush()
        assert not archive.connection.in_transaction
        with closing(sqlite3.connect(archive.path)) as reader:
            assert reader.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
        assert archive.connection.execute("PRAGMA cache_size").fetchone()[0] == -2048
    finally:
        archive.close()


def test_seen_candidate_writes_commit_in_bounded_batches():
    archive = VectorArchive(())
    trace = []
    try:
        archive.connection.execute("CREATE TABLE seen(identity INTEGER PRIMARY KEY)")
        archive.connection.set_trace_callback(trace.append)
        for index in range(4097):
            archive.connection.execute("INSERT INTO seen VALUES(?)", (index,))
        assert trace.count("COMMIT") == 1
        assert trace.count("BEGIN DEFERRED") == 2
        assert archive.connection.in_transaction
        archive.flush()
        assert len(archive.connection.execute("SELECT * FROM seen").fetchall()) == 4097
    finally:
        archive.close()
