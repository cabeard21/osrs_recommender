"""Raw archive files survive IPC ownership transfer and are scavenged after crashes."""

import multiprocessing
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tracker.gear.objective_store import ObjectiveRunStore
from tracker.gear.vector_archive import VectorArchive


def _worker_archive():
    archive = VectorArchive(())
    archive.add(
        {
            "score": 1,
            "objective_values": {},
            "maximum_actions": 0,
            "loadouts": {"a": {"equipment": {}}},
        }
    )
    return archive, archive.path


def test_ipc_rehomes_archive_before_worker_shutdown():
    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        archive, original = pool.submit(_worker_archive).result(timeout=30)
        assert archive.path != original
        assert Path(archive.path).parent.name.startswith("gear-objective-session-")
        assert not Path(original).exists()
    try:
        assert archive.solutions()[0]["score"] == 1
    finally:
        archive.close()


def test_abrupt_worker_exit_leaves_only_marked_orphan_and_next_session_removes_it():
    script = (
        "import os; from tracker.gear.vector_archive import VectorArchive; "
        "archive=VectorArchive(()); print(archive.path,flush=True); os._exit(0)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True, timeout=30
    )
    orphan = Path(completed.stdout.strip())
    assert orphan.exists()
    root = orphan.parent
    assert (root / ".owner.json").exists()
    with ObjectiveRunStore() as live:
        assert live.directory.exists()
        assert not root.exists()
