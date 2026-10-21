"""The upgrade shortcut changes the pin only after resolving a valid release."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from urllib.error import URLError

import pytest

from scripts import upgrade_runelite as upgrade


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "plugin").mkdir()
    (tmp_path / "plugin" / "build.gradle").write_bytes(
        b"// keep this\r\ndef runeLiteVersion = '1.13.1'\r\n// and this\r\n"
    )
    return tmp_path


def test_fetch_latest_uses_release_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch(url: str, *, timeout: int) -> io.BytesIO:
        assert url == upgrade.METADATA_URL
        assert timeout == 10
        return io.BytesIO(
            b"<metadata><versioning><latest>9.0.0-SNAPSHOT</latest>"
            b"<release>1.13.2</release></versioning></metadata>"
        )

    monkeypatch.setattr(upgrade, "urlopen", fetch)
    assert upgrade.latest_release() == "1.13.2"


@pytest.mark.parametrize(
    "metadata",
    [
        b"bad XML",
        b"<metadata/>",
        b"""<metadata>
    <versioning><release>1.14.0-SNAPSHOT</release></versioning></metadata>""",
    ],
)
def test_bad_metadata_fails(monkeypatch: pytest.MonkeyPatch, metadata: bytes) -> None:
    monkeypatch.setattr(upgrade, "urlopen", lambda *a, **kw: io.BytesIO(metadata))
    with pytest.raises(upgrade.UpgradeError):
        upgrade.latest_release()


def test_network_failure_leaves_pin_untouched(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin = repo / "plugin" / "build.gradle"
    before = pin.read_bytes()

    def offline(*args: object, **kwargs: object) -> None:
        raise URLError("offline")

    monkeypatch.setattr(upgrade, "urlopen", offline)
    with pytest.raises(upgrade.UpgradeError, match="release"):
        upgrade.upgrade(repo)
    assert pin.read_bytes() == before


def test_upgrade_preserves_bytes_and_builds_new_pin(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = repo / "plugin" / "build.gradle"
    before = pin.read_bytes()
    built = []

    def build(root: Path) -> None:
        assert root == repo
        assert pin.read_bytes() == before.replace(b"1.13.1", b"1.13.2")
        built.append(root)

    monkeypatch.setattr(upgrade, "latest_release", lambda: "1.13.2")
    monkeypatch.setattr(upgrade, "validate_build", build)
    upgrade.upgrade(repo)
    assert built == [repo]
    assert pin.read_bytes() == before.replace(b"1.13.1", b"1.13.2")


@pytest.mark.parametrize("check,version", [(True, "1.13.2"), (False, "1.13.1")])
def test_check_and_already_current_do_not_write_or_build(
    repo: Path, monkeypatch: pytest.MonkeyPatch, check: bool, version: str
) -> None:
    pin = repo / "plugin" / "build.gradle"
    before = pin.stat().st_mtime_ns
    monkeypatch.setattr(upgrade, "validate_build", lambda root: pytest.fail("unexpected build"))
    upgrade.upgrade(repo, version=version, check=check)
    assert pin.stat().st_mtime_ns == before


@pytest.mark.parametrize("version", ["1.12.99", "1.14.0-SNAPSHOT", "x';evil", "1.14", ""])
def test_invalid_or_older_versions_do_not_edit(repo: Path, version: str) -> None:
    pin = repo / "plugin" / "build.gradle"
    before = pin.read_bytes()
    with pytest.raises(upgrade.UpgradeError):
        upgrade.upgrade(repo, version=version)
    assert pin.read_bytes() == before


@pytest.mark.parametrize("contents", [b"missing pin", b"def runeLiteVersion = '1.0.0'\n" * 2])
def test_missing_or_ambiguous_pin_is_rejected(repo: Path, contents: bytes) -> None:
    pin = repo / "plugin" / "build.gradle"
    pin.write_bytes(contents)
    with pytest.raises(upgrade.UpgradeError, match="exactly one"):
        upgrade.upgrade(repo, version="1.13.2")
    assert pin.read_bytes() == contents


@pytest.mark.parametrize(
    "failure", [OSError("no Java"), subprocess.CalledProcessError(1, "gradle"), KeyboardInterrupt()]
)
def test_failed_or_interrupted_build_restores_original(
    repo: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    pin = repo / "plugin" / "build.gradle"
    before = pin.read_bytes()

    def fail(root: Path) -> None:
        raise failure

    monkeypatch.setattr(upgrade, "validate_build", fail)
    with pytest.raises((upgrade.UpgradeError, KeyboardInterrupt)):
        upgrade.upgrade(repo, version="1.13.2")
    assert pin.read_bytes() == before


def test_rollback_preserves_concurrent_edit(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pin = repo / "plugin" / "build.gradle"

    def fail(root: Path) -> None:
        pin.write_bytes(b"someone else's edit")
        raise OSError("failed")

    monkeypatch.setattr(upgrade, "validate_build", fail)
    with pytest.raises(upgrade.UpgradeError, match="changed during"):
        upgrade.upgrade(repo, version="1.13.2")
    assert pin.read_bytes() == b"someone else's edit"


def test_release_lookup_preserves_concurrent_edit(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pin = repo / "plugin" / "build.gradle"

    def lookup() -> str:
        pin.write_bytes(b"someone else's edit")
        return "1.13.2"

    monkeypatch.setattr(upgrade, "latest_release", lookup)
    with pytest.raises(upgrade.UpgradeError, match="changed during"):
        upgrade.upgrade(repo)
    assert pin.read_bytes() == b"someone else's edit"


def test_gradle_invocation_redirects_fixture(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(args: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == repo / "plugin"
        assert check is True
        assert Path(args[0]).name in {"gradlew.bat", "gradlew"}
        assert args[1:3] == ["build", "--no-daemon"]
        init = Path(args[4]).read_text(encoding="utf-8")
        assert "tracker.fixture" in init
        assert "upgrade-fixtures/plugin_sample.json" in init

    monkeypatch.setattr(upgrade.subprocess, "run", run)
    upgrade.validate_build(repo)


def test_cli_reports_failure(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(upgrade, "REPO", repo)
    assert upgrade.main(["--version", "bad"]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_cli_check(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(upgrade, "REPO", repo)
    assert upgrade.main(["--version", "1.13.2", "--check"]) == 0
    assert "1.13.1 -> 1.13.2" in capsys.readouterr().out
