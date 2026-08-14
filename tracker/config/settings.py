"""Application configuration (§7.5, §11.1).

Settings are layered, highest priority first:

    1. explicit keyword arguments to ``Settings(...)``
    2. environment variables, prefixed ``TRACKER_`` (nested via ``__``)
    3. ``config.yaml`` — path overridable with ``TRACKER_CONFIG_FILE``

``config.yaml`` is gitignored because it carries the bearer token shared with the
RuneLite plugin (§11.2).

Two fields are deliberately hostile to defaults:

* ``bind_address`` has **no default** and rejects unspecified addresses. §11.1 makes
  the bind address explicit configuration precisely because "no public exposure" is a
  deployment property, not an access control — a convenient default is how a tracker
  ends up listening on every interface.
* ``api_token`` is required. There is no unauthenticated mode to fall back to.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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
    base_url: str = "https://prices.runescape.wiki/api/v1/osrs"
    user_agent: str = "osrs-pvp-progression-tracker/0.1 (private local progression app)"
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
    user_agent: str = "osrs-pvp-progression-tracker/0.1 (private local progression app)"


class AdvisorSettings(BaseModel):
    """§22's general advisor. Off by default **even when** ``llm.enabled`` is true.

    Two switches rather than one, and the second is not redundant: enabling §21's task guidance
    is not consent to a chat surface with a different cost profile. A guidance note is one model
    call; an advisor turn is one call per tool round trip plus the answer, so the same button
    press costs several times as much. Someone who turned guidance on should not discover the
    advisor by finding it on their bill.

    Nothing here can reach a ranking — D14 and D15 both hold regardless of these values.
    """

    enabled: bool = False

    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(default=8000, gt=0)
    """Caps reasoning *and* answer together, as ``LlmSettings.max_tokens`` does."""

    timeout_seconds: float = Field(default=180.0, gt=0)
    """Higher than guidance's 120: a tool-using turn is several sequential round trips."""

    max_model_iterations: int = Field(default=6, ge=1)
    """Model calls per turn (§22.4). Exhausting this returns whatever text exists."""

    max_tool_calls: int = Field(default=10, ge=0)
    """Tool calls per turn, across all iterations. Exceeding it yields error results telling
    the model to answer with what it has — cheaper than a truncated turn, and honest."""

    max_history_turns: int = Field(default=12, ge=1)
    """Question/answer pairs replayed. The prefix is cached; the history is not, so this is
    the term that actually grows a long conversation's cost."""

    min_interval_seconds: int = Field(default=10, ge=0)
    """Lower than §21.6's 30 because conversation is inherently interactive (§22.7)."""

    max_calls_per_day: int = Field(default=60, ge=0)
    """The advisor's **own** ceiling, counted from its own stored answers. Deliberately not
    shared with guidance: a shared ceiling would let one conversation silently consume the
    day's guidance budget, which the user would experience as guidance mysteriously refusing."""

    keep_conversations: int = Field(default=20, ge=1)
    keep_messages_per_conversation: int = Field(default=60, ge=2)
    """Pruned on write in pairs, so a thread never begins with an orphaned answer (§22.6)."""


class LlmSettings(BaseModel):
    """Task guidance provider configuration (§21.4).

    Disabled by default, and the default is load-bearing rather than polite: D14 makes
    guidance a terminal output, so an install that has never been given a key must start,
    sync, rank and render exactly as one that has. Nothing here can reach a ranking.

    ``provider`` is the vendor seam. The application talks to a narrow protocol
    (``tracker.integrations.llm.types.GuidanceProvider``); this field selects which
    implementation satisfies it. Widening the ``Literal`` and adding a branch to
    ``build_provider`` is the whole cost of a second vendor.
    """

    enabled: bool = False

    provider: Literal["anthropic"] = "anthropic"

    model: str = "claude-opus-5"
    base_url: str | None = None
    """Override the provider's own default endpoint. ``None`` uses the SDK default."""

    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    """How hard the model works. Not every provider has this knob; those that don't ignore it."""

    max_tokens: int = Field(default=8000, gt=0)
    """Caps reasoning *and* answer together, which is why this is thousands, not hundreds."""

    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    """Retries are the provider SDK's job. §7.5's schedule is deliberately **not** layered
    on top — doubling the two would turn one button press into nine requests."""

    api_key: SecretStr | None = None
    """Read from ``config.yaml``, which already holds ``api_token`` (§11.2) and is gitignored.
    ``SecretStr`` so a stray repr or log line cannot print it. Unset falls back to
    ``api_key_env_var``; unset *and* unset in the environment leaves the provider unbuilt."""

    api_key_env_var: str = "ANTHROPIC_API_KEY"

    guidance_ttl_hours: int = Field(default=168, gt=0)
    """Backstop only. §21.5: the context hash is the real invalidator — advice goes wrong when
    the account moves, not when a clock says so. This catches the case the hash cannot see,
    where the corpus or the instruction block changed but the rendered context did not."""

    min_interval_seconds: int = Field(default=30, ge=0)
    """Mirrors ``PricesSettings.manual_refresh_min_interval_seconds`` (§21.6)."""

    max_calls_per_day: int = Field(default=50, ge=0)
    """Counted from the stored notes themselves, so a restart does not reset the ceiling."""

    keep_notes_per_candidate: int = Field(default=3, ge=1)
    """Retention per task, pruned on write — §6.10's snapshot-retention shape, no background job."""

    advisor: AdvisorSettings = Field(default_factory=AdvisorSettings)
    """§22. Shares ``model``, ``provider``, ``base_url``, the credentials and ``max_retries``
    with guidance above; everything cost-shaped is its own (§22.7)."""


class IntegrationsSettings(BaseModel):
    prices: PricesSettings = Field(default_factory=PricesSettings)
    wise_old_man: WiseOldManSettings = Field(default_factory=WiseOldManSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)


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
        return loaded


class Settings(BaseSettings):
    """Root application settings."""

    model_config = SettingsConfigDict(
        env_prefix="TRACKER_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    bind_address: str
    """Loopback or the Tailscale interface address. No default — see §11.1."""

    port: int = Field(default=8502, gt=0, lt=65536)
    api_token: str = Field(min_length=1)
    """Bearer token shared with the RuneLite plugin (§11.2). Env: ``TRACKER_API_TOKEN``."""

    database_url: str = "sqlite:///./tracker.db"
    integrations: IntegrationsSettings = Field(default_factory=IntegrationsSettings)
    content_dir: Path = Path("content")
    scoring_profile_path: Path = Path("content/scoring/profile.yaml")

    @field_validator("bind_address")
    @classmethod
    def _reject_unspecified_bind_address(cls, value: str) -> str:
        candidate = value.strip()
        if candidate in _UNSPECIFIED_ADDRESSES:
            raise ValueError(
                f"bind_address {value!r} binds every interface, which §11.1 forbids: any device "
                "that can route to this host could POST to /api/sync. Use the loopback address "
                "(127.0.0.1) or this machine's Tailscale interface address."
            )
        if not candidate:
            raise ValueError("bind_address must not be empty")
        try:
            parsed = ipaddress.ip_address(candidate)
        except ValueError:
            # Hostnames are permitted — a Tailscale MagicDNS name is a legitimate bind target.
            return candidate
        if parsed.is_unspecified:
            raise ValueError(
                f"bind_address {value!r} is an unspecified address and binds every interface "
                "(§11.1)"
            )
        return candidate

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
