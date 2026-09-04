"""Dependency constraints that protect tested integration seams."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_anthropic_stays_on_the_httpx_compatible_sdk() -> None:
    """Anthropic 1.x uses httpx2, while our injected transports use httpx."""
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = metadata["project"]["dependencies"]

    assert "anthropic>=0.121,<1" in dependencies
