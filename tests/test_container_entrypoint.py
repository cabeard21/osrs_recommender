"""Execute the production shell dispatcher with a harmless Python stand-in."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], ["-m alembic upgrade head", "-m tracker.app"]),
        (["python", "-m", "tracker.mcp"], ["-m tracker.mcp"]),
        (["python", "-c", "argument with spaces"], ["-c argument with spaces"]),
    ],
)
def test_entrypoint_dispatch(tmp_path: Path, arguments: list[str], expected: list[str]) -> None:
    shell = shutil.which("sh")
    git = shutil.which("git")
    if shell is None and git:
        git_shell = Path(git).resolve().parents[1] / "bin" / "sh.exe"
        if git_shell.exists():
            shell = str(git_shell)
    if shell is None:
        pytest.skip("POSIX shell unavailable; exercised by Linux CI")
    stand_in = tmp_path / "python"
    stand_in.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n', encoding="utf-8")
    stand_in.chmod(0o755)
    result = subprocess.run(
        [shell, str(ROOT / "docker-entrypoint.sh"), *arguments],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == expected
