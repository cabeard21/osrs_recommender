"""Static-only React preview registration, independent of NiceGUI and GearService."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BUNDLE_DIR = Path(__file__).parent / "gear_static"
SPRITE_DIR = Path(__file__).parent / "assets" / "items"


def mount_gear_preview(app: FastAPI, *, bundle_dir: Path = BUNDLE_DIR) -> None:
    """Register before NiceGUI's root mount; a missing build never breaks the app."""
    app.mount("/gear-sprites", StaticFiles(directory=SPRITE_DIR), name="gear-sprites")

    @app.get("/gear-next", include_in_schema=False)
    def gear_preview_redirect() -> RedirectResponse:
        return RedirectResponse("/gear-next/", status_code=307)

    @app.get("/gear-next/", include_in_schema=False, response_model=None)
    def gear_preview() -> FileResponse | JSONResponse:
        index = bundle_dir / "index.html"
        if not index.is_file():
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "gear_frontend_unavailable",
                        "message": "Gear preview build unavailable. Run npm ci and npm run build "
                        "in frontend/gear; the existing Gear page remains at /gear.",
                    }
                },
            )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    # Serve only files inside the bundle, even when the build is absent at startup.
    @app.get("/gear-ui/{asset_path:path}", include_in_schema=False, response_model=None)
    async def gear_asset(asset_path: str) -> FileResponse | JSONResponse:
        candidate = (bundle_dir / asset_path).resolve()
        if not candidate.is_relative_to(bundle_dir.resolve()) or not candidate.is_file():
            return JSONResponse(status_code=404, content={"detail": "Gear asset not found"})
        return FileResponse(candidate)
