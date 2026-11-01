"""Loopback-only Gear execution using authoritative Pi facts, without a local DB."""

import os
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tracker.config.settings import _YamlSettingsSource


class _DesktopYamlSource(_YamlSettingsSource):
    def __call__(self):
        import yaml

        path = Path(os.environ.get("TRACKER_CONFIG_FILE", "config.gear-desktop.yaml"))
        if not path.is_file():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class DesktopSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRACKER_DESKTOP_", extra="forbid", hide_input_in_errors=True
    )
    bind_address: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8502, gt=0, lt=65536)
    content_dir: Path = Path("content")
    pi_url: str
    player_id: int = Field(gt=0)
    read_token: SecretStr

    @field_validator("read_token")
    @classmethod
    def valid_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip() or value.get_secret_value() == "CHANGE_ME":
            raise ValueError("Configure the Pi read-only token")
        return value

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return init_settings, env_settings, _DesktopYamlSource(settings_cls), file_secret_settings


def create_app(settings: DesktopSettings) -> FastAPI:
    from tracker.api.gear_evaluations import router as evaluations
    from tracker.api.gear_optimizations import router as optimizations
    from tracker.api.gear_ui import router as gear_ui
    from tracker.content.loader import load_content
    from tracker.gear.data_source import RemoteGearDataSource
    from tracker.gear.service import GearService
    from tracker.ui.gear_preview import mount_gear_preview

    app = FastAPI(title="Desktop Gear")
    content = load_content(settings.content_dir)
    app.state.gear_service = GearService(content, equipment_root=settings.content_dir / "equipment")
    app.state.gear_data_source = RemoteGearDataSource(
        settings.pi_url, settings.player_id, settings.read_token.get_secret_value()
    )
    app.include_router(gear_ui)
    app.include_router(optimizations)
    app.include_router(evaluations)
    mount_gear_preview(app)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def home():
        return RedirectResponse("/gear")

    return app


def load_desktop_settings() -> DesktopSettings:
    return DesktopSettings()


def main() -> None:
    settings = load_desktop_settings()
    uvicorn.run(create_app(settings), host=settings.bind_address, port=settings.port)


if __name__ == "__main__":
    main()
