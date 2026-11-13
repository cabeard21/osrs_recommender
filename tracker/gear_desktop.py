"""Private Gear execution using authoritative Pi facts, without a local DB."""

import asyncio
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tracker.config.settings import _YamlSettingsSource
from tracker.gear.execution_profile import ExecutionProfile
from tracker.gear.native.readiness import require_native

logger = logging.getLogger(__name__)


def _process_pool(workers: int):
    from tracker.gear.parallel import AutoProcessPool

    return AutoProcessPool(workers)


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
    bind_address: str = "127.0.0.1"
    port: int = Field(default=8502, gt=0, lt=65536)
    content_dir: Path = Path("content")
    optimization_workers: int = Field(default=6, ge=1, le=6)
    optimization_profile: ExecutionProfile = "combined"
    optimization_engine: Literal["native", "python"] = "native"
    pi_url: str
    player_id: int = Field(gt=0)
    read_token: SecretStr

    @field_validator("optimization_workers", mode="before")
    @classmethod
    def worker_count(cls, value):
        if isinstance(value, bool):
            raise ValueError("optimization_workers must be an integer from 1 through 6")
        return value

    @field_validator("bind_address")
    @classmethod
    def private_bind(cls, value: str) -> str:
        address = ipaddress.ip_address(value.strip())
        network = ipaddress.ip_network(
            "100.64.0.0/10" if address.version == 4 else "fd7a:115c:a1e0::/48"
        )
        if not address.is_loopback and address not in network:
            raise ValueError("bind_address must be a loopback or Tailscale IP address")
        return str(address)

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

    native = (
        settings.optimization_engine == "native" and settings.optimization_profile == "combined"
    )
    content = load_content(settings.content_dir)
    gear = GearService(
        content,
        equipment_root=settings.content_dir / "equipment",
        optimization_profile=settings.optimization_profile,
        fixed_reporting=settings.optimization_profile == "combined",
        factored_evaluation=settings.optimization_profile == "combined",
        compact_states=settings.optimization_profile == "combined",
        native_search=native,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = None
        try:
            if native:
                require_native()
            logger.info("Desktop Gear optimization engine: %s", "native" if native else "python")
            if settings.optimization_engine == "native" and not native:
                logger.info("Desktop Gear rollback profile selects Python execution")
            logger.info("Desktop Gear optimization profile: %s", settings.optimization_profile)
            logger.info(
                "Desktop Gear fixed-option reporting: %s",
                "enabled" if gear.fixed_reporting else "disabled",
            )
            logger.info(
                "Desktop Gear factored evaluation: %s",
                "enabled" if gear.factored_evaluation else "disabled",
            )
            logger.info(
                "Desktop Gear compact states: %s",
                "enabled" if gear.compact_states else "disabled",
            )
            if settings.optimization_workers > 1:
                try:
                    pool = _process_pool(settings.optimization_workers)
                    if native:
                        await asyncio.to_thread(
                            pool.start, content, gear.equipment_catalog(), native_required=True
                        )
                    else:
                        await asyncio.to_thread(pool.start, content, gear.equipment_catalog())
                except Exception as exc:
                    if pool is not None:
                        await asyncio.to_thread(pool.close)
                        pool = None
                    if native:
                        raise
                    app.state.gear_execution = "serial_startup_fallback"
                    logger.warning(
                        "Desktop Gear process pool could not start (%s); using serial execution",
                        type(exc).__name__,
                    )
                else:
                    gear.auto_pool = pool
                    app.state.gear_execution = "processes"
                    logger.info(
                        "Desktop Gear ready with %d worker processes", settings.optimization_workers
                    )
            yield
        finally:
            if pool is not None:
                try:
                    await asyncio.to_thread(pool.close)
                finally:
                    gear.auto_pool = None

    app = FastAPI(title="Desktop Gear", lifespan=lifespan)
    app.state.gear_execution = "serial"
    app.state.gear_engine = "native" if native else "python"
    gear.auto_pool = None
    app.state.gear_service = gear
    app.state.gear_data_source = RemoteGearDataSource(
        settings.pi_url, settings.player_id, settings.read_token.get_secret_value()
    )
    app.include_router(gear_ui)
    app.include_router(optimizations)
    app.include_router(evaluations)
    from tracker.api.gear_ammo import router as ammo_router

    app.include_router(ammo_router)
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = load_desktop_settings()
    uvicorn.run(create_app(settings), host=settings.bind_address, port=settings.port)


if __name__ == "__main__":
    main()
