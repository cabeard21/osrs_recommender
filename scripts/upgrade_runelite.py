"""Upgrade the local RuneLite pin and validate it without launching a client."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]
METADATA_URL = "https://repo.runelite.net/net/runelite/client/maven-metadata.xml"
PIN = re.compile(rb"(?m)^([ \t]*def[ \t]+runeLiteVersion[ \t]*=[ \t]*')([^'\r\n]+)('[^\n]*)$")
FIXTURE_INIT = """gradle.projectsEvaluated {
    rootProject.tasks.named('test') {
        systemProperty 'tracker.fixture', rootProject.layout.buildDirectory.file(
            'upgrade-fixtures/plugin_sample.json').get().asFile.absolutePath
    }
}
"""


class UpgradeError(RuntimeError):
    """A release lookup, pin update, or build failed."""


def version_number(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version):
        raise UpgradeError(f"Expected a stable numeric RuneLite version, got {version!r}.")
    return tuple(int(part) for part in version.split(".")) + (0,) * (4 - len(version.split(".")))


def latest_release() -> str:
    try:
        with urlopen(METADATA_URL, timeout=10) as response:
            metadata = ET.fromstring(response.read(1_000_000))
        release = metadata.findtext("versioning/release", "").strip()
        version_number(release)
        return release
    except (OSError, ValueError, ET.ParseError, UpgradeError) as exc:
        raise UpgradeError(f"Could not resolve the latest RuneLite release: {exc}") from exc


def validate_build(repo: Path) -> None:
    # The serializer normally regenerates a tracked fixture. Keep upgrade checks in build/.
    with tempfile.TemporaryDirectory(prefix="runelite-upgrade-") as temporary:
        init = Path(temporary) / "fixture.gradle"
        init.write_text(FIXTURE_INIT, encoding="utf-8")
        wrapper = "gradlew.bat" if sys.platform == "win32" else "gradlew"
        subprocess.run(
            [str(repo / "plugin" / wrapper), "build", "--no-daemon", "--init-script", str(init)],
            cwd=repo / "plugin",
            check=True,
        )


def upgrade(repo: Path, *, version: str | None = None, check: bool = False) -> None:
    pin = repo / "plugin" / "build.gradle"
    original = pin.read_bytes()
    matches = list(PIN.finditer(original))
    if len(matches) != 1:
        raise UpgradeError("Expected exactly one runeLiteVersion pin in plugin/build.gradle.")
    match = matches[0]
    current = match[2].decode("utf-8")
    target = latest_release() if version is None else version
    if version_number(target) < version_number(current):
        raise UpgradeError(f"Refusing to downgrade RuneLite {current} to {target}.")
    if target == current:
        print(f"RuneLite is already pinned to {current}; nothing changed.", flush=True)
        return
    print(f"RuneLite {current} -> {target}", flush=True)
    if check:
        print("Check only; no files changed.")
        return
    updated = original[: match.start(2)] + target.encode("ascii") + original[match.end(2) :]
    if pin.read_bytes() != original:
        raise UpgradeError("plugin/build.gradle changed during release lookup; retry the upgrade.")
    pin.write_bytes(updated)
    try:
        validate_build(repo)
    except (OSError, subprocess.CalledProcessError, KeyboardInterrupt) as exc:
        if pin.read_bytes() != updated:
            raise UpgradeError(
                "Build failed and plugin/build.gradle changed during validation; "
                f"preserved that edit. Previous pin was {current}."
            ) from exc
        pin.write_bytes(original)
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise UpgradeError(f"Plugin build failed; restored RuneLite {current}: {exc}") from exc
    print(f"RuneLite {target} pinned; plugin build, tests, and runtime checks passed.")
    print("Next: launch plugin/gradlew.bat runClient and verify a fresh account sync.")
    print("Review version-sensitive findings in docs/CONTRACT_RECONCILIATION.md.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Upgrade to a specific stable release instead of latest.")
    parser.add_argument(
        "--check", action="store_true", help="Show the update without editing/building."
    )
    args = parser.parse_args(argv)
    try:
        upgrade(REPO, version=args.version, check=args.check)
    except (UpgradeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Upgrade interrupted; previous pin restored.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
