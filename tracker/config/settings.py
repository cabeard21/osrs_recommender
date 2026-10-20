"""Application configuration (§7.5, §11.1).

Settings are layered, highest priority first:

    1. explicit keyword arguments to ``Settings(...)``
    2. environment variables, prefixed ``TRACKER_`` (nested via ``__``)
    3. ``config.yaml`` — path overridable with ``TRACKER_CONFIG_FILE``

``config.yaml`` is gitignored because it carries the bearer token shared with the
RuneLite plugin (§11.2).

Two fields are deliberately hostile to defaults:

* ``bind_address`` has **no default** and rejects unspecified addresses unless the
  separate ``allow_all_interfaces`` container-network opt-in is true. §11.1 makes the
  bind address explicit configuration precisely because "no public exposure" is a
  deployment property, not an access control.
* ``api_token`` is required. There is no unauthenticated mode to fall back to.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from tracker.mcp.settings import MCPSettings

DEFAULT_CONFIG_FILE = "config.yaml"
CONFIG_FILE_ENV_VAR = "TRACKER_CONFIG_FILE"

#: Addresses that bind to every interface. §11.1: "Never ``0.0.0.0``."
_UNSPECIFIED_ADDRESSES = frozenset({"0.0.0.0", "::", "0:0:0:0:0:0:0:0", "*"})


class PricesSettings(BaseModel):
    """OSRS Wiki real-time prices client configuration (§7.5).

    The provider asks automated clients for a descriptive ``User-Agent`` and may block
    generic identifiers (``python-requests``, bare ``curl``, Java defaults). It is
    configurable so no contact information is published without intent.
    """

    provider: str = "osrs_wiki"
    base_url: str = "https://prices.runescape.wiki/api/v2/osrs"
    user_agent: str = "osrs-account-companion/0.1 (private local account companion)"
    ttl_hours: int = Field(default=12, gt=0)
    manual_refresh_min_interval_seconds: int = Field(default=60, ge=0)

    @field_validator("user_agent")
    @classmethod
    def _reject_generic_user_agent(cls, value: str) -> str:
        generic = ("python-requests", "python-urllib", "apache-httpclient", "curl/", "httpx/")
        lowered = value.lower()
        if any(lowered.startswith(prefix) for prefix in generic):
            raise ValueError(
                f"user_agent {value!r} is a generic identifier; §7.5 requires a descriptive "
                "agent naming the application, version and purpose"
            )
        return value


class WiseOldManSettings(BaseModel):
    """Wise Old Man client configuration (§7.3)."""

    base_url: str = "https://api.wiseoldman.net/v2"
    user_agent: str = "osrs-account-companion/0.1 (private local account companion)"


class IntegrationsSettings(BaseModel):
    prices: PricesSettings = Field(default_factory=PricesSettings)
    wise_old_man: WiseOldManSettings = Field(default_factory=WiseOldManSettings)


class _YamlSettingsSource(PydanticBaseSettingsSource):
    """Read settings from a YAML file, resolved at call time.

    The path is read from the environment on each instantiation rather than baked into
    ``model_config``, so tests can point at a temporary file without reloading modules.
    """

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        raise NotImplementedError  # pragma: no cover — __call__ supplies everything

    def __call__(self) -> dict[str, Any]:
        path = Path(os.environ.get(CONFIG_FILE_ENV_VAR, DEFAULT_CONFIG_FILE))
        if not path.is_file():
            return {}
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: expected a YAML mapping at the top level")
        # Existing private installs may retain these M2 keys in gitignored config.yaml.
        # They no longer configure a runtime feature, but should not prevent account sync
        # from starting during the M3 transition. Other unknown keys remain errors.
        loaded = {key: value for key, value in loaded.items() if key != "scoring_profile_path"}
        integrations = loaded.get("integrations")
        if isinstance(integrations, dict):
            loaded["integrations"] = {
                key: value for key, value in integrations.items() if key != "llm"
            }
        return loaded


class Settings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    bind_address: str
    """Loopback, Tailscale address, or an explicitly opted-in container bind address."""

    allow_all_interfaces: bool = False
    """Explicit container-network opt-in for an unspecified bind address."""

    port: int = Field(default=8502, gt=0, lt=65536)
    api_token: str = Field(min_length=1)
    """Bearer token shared with the RuneLite plugin (§11.2). Env: ``TRACKER_API_TOKEN``."""

    database_url: str = "sqlite:///./tracker.db"
    integrations: IntegrationsSettings = Field(default_factory=IntegrationsSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    content_dir: Path = Path("content")

    @field_validator("bind_address")
    @classmethod
    def _reject_unspecified_bind_address(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("bind_address must not be empty")
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            # Hostnames are permitted — a Tailscale MagicDNS name is a legitimate bind target.
            return candidate
        if parsed.is_unspecified and candidate not in _UNSPECIFIED_ADDRESSES:
            raise ValueError(
                f"bind_address {value!r} is an unspecified address and binds every interface "
                "(§11.1)"
            )
        return candidate

    @model_validator(mode="after")
    def _require_explicit_all_interfaces_opt_in(self) -> Settings:
        if self.bind_address in _UNSPECIFIED_ADDRESSES and not self.allow_all_interfaces:
            raise ValueError(
                f"bind_address {self.bind_address!r} binds every interface, which §11.1 "
                "forbids unless allow_all_interfaces is explicitly enabled for an isolated "
                "container network"
            )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings(config_file: Path | str | None = None) -> Settings:
    """Load settings, optionally from an explicit ``config.yaml`` path."""
    if config_file is None:
        return Settings()
    previous = os.environ.get(CONFIG_FILE_ENV_VAR)
    os.environ[CONFIG_FILE_ENV_VAR] = str(config_file)
    try:
        return Settings()
    finally:
        if previous is None:
            del os.environ[CONFIG_FILE_ENV_VAR]
        else:
            os.environ[CONFIG_FILE_ENV_VAR] = previous
