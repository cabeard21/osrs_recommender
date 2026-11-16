"""Process-owned temporary archive roots with safe IPC file transfer."""

from __future__ import annotations

import atexit
import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import BinaryIO
from uuid import uuid4

from tracker.gear.objective_store import _cleanup_orphans, _lock_session

_guard = Lock()
_temporary: tempfile.TemporaryDirectory[str] | None = None
_lease: BinaryIO | None = None


def archive_directory(protect_source: Path | None = None) -> Path:
    """Keep roots locked until process exit; never scavenge an incoming IPC source."""
    global _temporary, _lease
    with _guard:
        if _temporary is None:
            _cleanup_orphans(exclude=protect_source)
            temporary = tempfile.TemporaryDirectory(prefix="gear-objective-session-")
            root = Path(temporary.name)
            (root / ".owner.json").write_text(
                json.dumps({"owner": "gear-objective-store", "version": 1, "id": str(uuid4())}),
                encoding="utf-8",
            )
            lease = (root / ".session-lock").open("w+b")
            lease.write(b"0")
            lease.flush()
            _lock_session(lease)
            _temporary, _lease = temporary, lease
            # Register after TemporaryDirectory's weakref exit hook so our lock
            # closes before that hook tries deleting the directory on Windows.
            atexit.register(_close)
        return Path(_temporary.name)


def receive_archive(path: str) -> str:
    """Move worker-returned files before its process/session can be cleaned up."""
    source = Path(path)
    destination = archive_directory(protect_source=source.parent)
    if source.parent.resolve() == destination.resolve():
        return path
    descriptor, target = tempfile.mkstemp(prefix="gear-vector-", suffix=".sqlite3", dir=destination)
    os.close(descriptor)
    try:
        os.replace(source, target)
    except BaseException:
        Path(target).unlink(missing_ok=True)
        raise
    return target


def _close() -> None:
    global _temporary, _lease
    with _guard:
        if _lease is not None:
            _lease.close()
            _lease = None
        if _temporary is not None:
            _temporary.cleanup()
            _temporary = None
