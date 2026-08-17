"""D15's structural half, asserted over the AST rather than trusted.

Modelled on ``tests/progression/test_import_boundary.py``. Two directions, and they exist for
different reasons:

* **Nothing in the advisor may import the database.** This is what makes "tools cannot write" a
  property of the code rather than a habit of its author: a function with no session in scope
  has nothing to write through, and no future edit can quietly acquire one without failing here.
* **Nothing in the ranking path may import the advisor.** D14's containment runs the other way —
  if :mod:`tracker.recommendations` could reach advisor code, a model-authored string would have
  a path into a score.

Import statements are read from source rather than from ``sys.modules`` because a module that is
merely *importable* from the wrong place is already the defect; waiting for it to be imported at
runtime would make the test depend on which code paths a suite happens to exercise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Scanned for forbidden imports. ``tracker/gear`` is here because the advisor imports it
#: (§23.5), and this test reads *direct* imports only — so a `sqlalchemy` import one module
#: deep in the gear package would be reachable from tool dispatch and invisible here.
#: Extending the scan is not tidiness; it is what keeps D15 an enforced property.
_PURE_ROOTS = (Path("tracker/advisor"), Path("tracker/gear"))

#: Packages the advisor must never reach. ``sqlalchemy`` as well as ``tracker.db`` because the
#: ORM is the capability, and importing it directly would evade a check on the wrapper alone.
_FORBIDDEN_TO_ADVISOR = ("tracker.db", "sqlalchemy", "alembic", "httpx", "anthropic", "nicegui")

#: Packages that must never reach the advisor — D14's direction.
_MUST_NOT_IMPORT_ADVISOR = (
    Path("tracker/progression"),
    Path("tracker/recommendations"),
    Path("tracker/estimation"),
    Path("tracker/domain"),
    Path("tracker/freshness"),
    Path("tracker/gear"),
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


@pytest.mark.parametrize(
    "path",
    [path for root in _PURE_ROOTS for path in _python_files(root)],
    ids=lambda path: f"{path.parent.name}/{path.name}",
)
def test_the_advisor_reaches_no_session_and_no_client(path: Path) -> None:
    """D15 — purity is the enforcement, so the imports are the thing to check."""
    for imported in _imported_modules(path):
        for forbidden in _FORBIDDEN_TO_ADVISOR:
            assert imported != forbidden and not imported.startswith(f"{forbidden}."), (
                f"{path} imports {imported!r}. The advisor package is pure (D15): tool dispatch "
                "must have no session to write through and no client to fetch with."
            )


@pytest.mark.parametrize("root", _MUST_NOT_IMPORT_ADVISOR, ids=lambda path: path.name)
def test_the_ranking_path_never_imports_the_advisor(root: Path) -> None:
    """D14 — a model-authored string must have no route into a score."""
    for path in _python_files(root):
        for imported in _imported_modules(path):
            assert not imported.startswith("tracker.advisor"), (
                f"{path} imports {imported!r}. Nothing that ranks, estimates or evaluates may "
                "reach advisor code (D14)."
            )


def test_the_advisor_package_is_not_empty() -> None:
    """Guards the parametrisation: an empty glob would make every test above vacuous."""
    assert len(_python_files(_PURE_ROOTS[0])) >= 5
    assert len(_python_files(_PURE_ROOTS[1])) >= 3
