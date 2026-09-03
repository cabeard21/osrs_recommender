"""Settings layering and the §11.1 bind-address rule."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from tracker.config.settings import CONFIG_FILE_ENV_VAR, Settings, load_settings

VALID_CONFIG = """
bind_address: 127.0.0.1
api_token: test-token
integrations:
  prices:
    ttl_hours: 6
"""


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Neither the developer's config.yaml nor their exported TRACKER_* vars may leak in."""
    for key in list(os.environ):
        if key.startswith("TRACKER_"):
            monkeypatch.delenv(key, raising=False)
    # Point at a path that does not exist, so "no config file" is the default state.
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(tmp_path / "absent.yaml"))


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_from_yaml(tmp_path: Path) -> None:
    settings = load_settings(_write_config(tmp_path, VALID_CONFIG))

    assert settings.bind_address == "127.0.0.1"
    assert settings.api_token == "test-token"
    assert settings.port == 8502
    assert settings.database_url == "sqlite:///./tracker.db"
    assert settings.integrations.prices.ttl_hours == 6
    assert settings.integrations.prices.base_url == "https://prices.runescape.wiki/api/v1/osrs"
    assert settings.integrations.wise_old_man.base_url == "https://api.wiseoldman.net/v2"
    assert settings.content_dir == Path("content")
    assert settings.scoring_profile_path == Path("content/scoring/profile.yaml")


def test_example_config_is_loadable(tmp_path: Path) -> None:
    """config.example.yaml must stay a working starting point, not drift into prose."""
    example = Path(__file__).parent.parent / "config.example.yaml"
    settings = load_settings(example)

    assert settings.bind_address == "127.0.0.1"
    assert settings.integrations.prices.ttl_hours == 12
    assert settings.integrations.prices.manual_refresh_min_interval_seconds == 60


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "0:0:0:0:0:0:0:0", " 0.0.0.0 "])
def test_unspecified_bind_address_is_rejected(address: str) -> None:
    """§11.1 — binding every interface is forbidden outright, not merely discouraged."""
    with pytest.raises(ValidationError, match="every interface"):
        Settings(bind_address=address, api_token="t")


def test_container_bind_requires_an_explicit_opt_in() -> None:
    settings = Settings(
        bind_address="0.0.0.0",
        allow_all_interfaces=True,
        api_token="t",
    )

    assert settings.bind_address == "0.0.0.0"
    assert settings.allow_all_interfaces is True


def test_bind_address_has_no_default() -> None:
    with pytest.raises(ValidationError, match="bind_address"):
        Settings(api_token="t")  # type: ignore[call-arg]


def test_tailscale_address_and_hostname_are_accepted() -> None:
    assert Settings(bind_address="100.64.0.1", api_token="t").bind_address == "100.64.0.1"
    assert Settings(bind_address="host.tailnet.ts.net", api_token="t").bind_address == (
        "host.tailnet.ts.net"
    )


def test_api_token_is_required() -> None:
    with pytest.raises(ValidationError, match="api_token"):
        Settings(bind_address="127.0.0.1")  # type: ignore[call-arg]


def test_empty_api_token_is_rejected() -> None:
    with pytest.raises(ValidationError, match="api_token"):
        Settings(bind_address="127.0.0.1", api_token="")


def test_environment_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACKER_API_TOKEN", "from-env")
    monkeypatch.setenv("TRACKER_INTEGRATIONS__PRICES__TTL_HOURS", "1")

    settings = load_settings(_write_config(tmp_path, VALID_CONFIG))

    assert settings.api_token == "from-env"
    assert settings.integrations.prices.ttl_hours == 1
    assert settings.bind_address == "127.0.0.1"  # untouched keys still come from YAML


def test_container_runtime_paths_and_bind_opt_in_load_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRACKER_BIND_ADDRESS", "0.0.0.0")
    monkeypatch.setenv("TRACKER_ALLOW_ALL_INTERFACES", "true")
    monkeypatch.setenv("TRACKER_API_TOKEN", "container-token")
    monkeypatch.setenv("TRACKER_DATABASE_URL", "sqlite:////data/tracker.db")

    settings = Settings()

    assert settings.bind_address == "0.0.0.0"
    assert settings.allow_all_interfaces is True
    assert settings.database_url == "sqlite:////data/tracker.db"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """A typo in config.yaml must fail loudly rather than be silently ignored."""
    body = VALID_CONFIG + "\nbnid_address: 127.0.0.1\n"
    with pytest.raises(ValidationError, match="bnid_address"):
        load_settings(_write_config(tmp_path, body))


def test_generic_user_agent_is_rejected(tmp_path: Path) -> None:
    """§7.5 — the price provider may block generic identifiers."""
    body = VALID_CONFIG + "\n    user_agent: python-requests/2.31.0\n"
    with pytest.raises(ValidationError, match="generic identifier"):
        load_settings(_write_config(tmp_path, body))


def test_missing_config_file_is_not_an_error_when_env_supplies_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRACKER_BIND_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("TRACKER_API_TOKEN", "env-only")

    settings = Settings()

    assert settings.bind_address == "127.0.0.1"
    assert settings.api_token == "env-only"
