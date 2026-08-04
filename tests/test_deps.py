"""Tripwire for downstream headline imports.

Every import here is hard-required by a later step. Without this test, omitting one of
them lets ``make install`` succeed and Steps 8, 9 and 10 fail at import time instead —
far from the change that caused it.
"""

from __future__ import annotations


def test_downstream_imports_resolve() -> None:
    import alembic  # noqa: F401  — step 3a
    import fastapi  # noqa: F401  — step 8a
    import httpx  # noqa: F401  — step 7
    import hypothesis  # noqa: F401  — step 4
    import jsonschema  # noqa: F401  — step 8a, sync payload contract
    import plotly  # noqa: F401  — step 11
    import pydantic
    import pydantic_settings  # noqa: F401  — step 1
    import sqlalchemy  # noqa: F401  — step 3a
    import uvicorn  # noqa: F401  — step 9
    import yaml  # noqa: F401  — step 2b
    from nicegui import ui  # noqa: F401  — steps 10, 11

    assert int(pydantic.VERSION.split(".")[0]) >= 2, "§14.1 requires Pydantic v2"


def test_nicegui_test_harness_is_installed() -> None:
    """Steps 10–11 drive the UI through NiceGUI's pytest plugin."""
    import nicegui.testing  # noqa: F401
