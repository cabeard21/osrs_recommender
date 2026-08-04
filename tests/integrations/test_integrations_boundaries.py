"""Package-level boundaries the Step 7 exit criteria call out explicitly.

* Hiscores direct access is documentation-only contingency (§7.3) — no code.
* Every client returns DTOs and imports nothing from `tracker.db` — Step 9's
  orchestration pipeline owns all writes (module docstring of `tracker.integrations`).
"""

from __future__ import annotations

import ast
from pathlib import Path

import tracker.integrations as integrations_package

_INTEGRATIONS_ROOT = Path(integrations_package.__file__).parent


class TestHiscoresIsDocumentationOnly:
    def test_hiscores_directory_has_no_python_beyond_the_empty_package_marker(self) -> None:
        hiscores_dir = _INTEGRATIONS_ROOT / "hiscores"
        python_files = sorted(hiscores_dir.glob("*.py"))

        assert [p.name for p in python_files] == ["__init__.py"]
        assert hiscores_dir.joinpath("__init__.py").read_text(encoding="utf-8").strip() == ""

    def test_hiscores_has_a_readme_explaining_the_contingency(self) -> None:
        readme = _INTEGRATIONS_ROOT / "hiscores" / "README.md"
        assert readme.is_file()
        text = readme.read_text(encoding="utf-8")
        assert "contingency" in text.lower()
        assert "not built for v1" in text.lower() or "not built" in text.lower()


class TestNoDatabaseImports:
    """Clients return DTOs and import nothing from `tracker.db` (§16.1's purity
    mandate, one layer out — see the `tracker.integrations` package docstring)."""

    def test_no_module_in_the_package_imports_tracker_db(self) -> None:
        offenders = []
        for path in _INTEGRATIONS_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                if any(
                    name is not None and name.split(".")[0:2] == ["tracker", "db"] for name in names
                ):
                    offenders.append(str(path))
        assert offenders == []
