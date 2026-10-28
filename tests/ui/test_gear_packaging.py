"""Wheel assets are self-contained and independent of a developer's Vite output."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_contains_nested_gear_assets(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(root / name, source / name)
    ui = source / "tracker" / "ui"
    ui.mkdir(parents=True)
    (source / "tracker" / "__init__.py").touch()
    (ui / "__init__.py").touch()
    assets = {
        "gear_static/index.html": b'<script src="/gear-ui/assets/app.js"></script>',
        "gear_static/assets/app.js": b"console.log('packaged')",
        "gear_static/assets/app.css": b"body { color: white; }",
        "gear_static/assets/fonts/body.woff2": b"font fixture",
        "assets/items/4151.png": b"sprite fixture",
    }
    for name, value in assets.items():
        destination = ui / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools.build_meta import build_wheel; build_wheel('dist')",
        ],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    with zipfile.ZipFile(next((source / "dist").glob("*.whl"))) as wheel:
        for name, value in assets.items():
            assert wheel.read(f"tracker/ui/{name}") == value
