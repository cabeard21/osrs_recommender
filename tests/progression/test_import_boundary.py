"""The pure core imports nothing that can perform I/O (§16.1, §14).

§16.1 requires the recommendation engine to be a pure function over a state object:

    def recommend(state, selection, content, profile) -> list[Recommendation]

An import is how that guarantee is lost. Nobody sets out to run a query inside the
scorer; it happens when a module that *can* reach the session does, three refactors
later. Forbidding the import makes the violation impossible to introduce quietly.

The check walks the **AST**, not the text. A grep is defeated by a line continuation, a
string, or a comment, and it cannot tell an import from a mention of one — including the
mentions in this very docstring, which name every forbidden module.

This test lives in Step 4 rather than Step 3 deliberately: Steps 3 and 4 run in parallel,
and at Step 3's merge ``tracker/progression/`` may not exist yet, so the same assertion
written there would pass by finding nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import tracker

#: The packages §16.1 requires to be pure.
#:
#: ``guidance`` joins them for a reason §16.1 does not itself give. §21.2's context assembly
#: is not on the ranking path and could in principle read anything; the rule it must not
#: break is §10.5's — ``MethodDetail`` is descriptive content no recommendation may consult —
#: and the cheapest way to keep that true is to make the module that consults it heavily
#: incapable of reaching a session. D14 is the same boundary named from the output side.
PURE_PACKAGES = frozenset({"progression", "recommendations", "estimation", "domain", "guidance"})

#: Persistence, transport, and the two libraries that provide them. A module reaching for
#: any of these is either querying or fetching, and neither belongs in a pure function.
FORBIDDEN_PREFIXES = ("tracker.db", "tracker.api", "httpx", "sqlalchemy")

TRACKER_ROOT = Path(tracker.__file__).parent


def imported_modules(tree: ast.AST) -> list[str]:
    """Every module named by an ``import`` or ``from ... import`` statement.

    Relative imports resolve to the empty string for ``node.module``; they cannot reach
    another top-level package, so they are never forbidden.
    """
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module or "")
    return modules


def pure_modules() -> list[Path]:
    return sorted(
        path
        for path in TRACKER_ROOT.rglob("*.py")
        if path.relative_to(TRACKER_ROOT).parts[0] in PURE_PACKAGES
    )


class TestPureCoreImports:
    def test_the_pure_packages_are_actually_present(self) -> None:
        """A boundary test that scans nothing passes for the wrong reason."""
        found = {path.relative_to(TRACKER_ROOT).parts[0] for path in pure_modules()}
        assert found == PURE_PACKAGES

    @pytest.mark.parametrize("path", pure_modules(), ids=lambda path: str(path.name))
    def test_no_pure_module_imports_persistence_or_transport(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offending = [
            module for module in imported_modules(tree) if module.startswith(FORBIDDEN_PREFIXES)
        ]
        assert not offending, (
            f"{path.relative_to(TRACKER_ROOT.parent)} imports {offending}. §16.1 makes the "
            "engine a pure function over PlayerState; persistence belongs to the projection "
            "(§3b) and transport to the integrations layer"
        )

    def test_the_check_would_catch_a_violation(self) -> None:
        """The detector itself, on a module that does what the rule forbids."""
        source = "from tracker.db.session import Session\nimport httpx\n"
        found = imported_modules(ast.parse(source))
        assert sorted(found) == ["httpx", "tracker.db.session"]
        assert all(module.startswith(FORBIDDEN_PREFIXES) for module in found)

    def test_a_mention_in_a_docstring_is_not_an_import(self) -> None:
        """Why this walks the AST instead of grepping."""
        source = '"""This module must never import sqlalchemy."""\n# import httpx\n'
        assert imported_modules(ast.parse(source)) == []
