"""Static preview isolation and missing-build behavior; no Gear endpoints are added."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tracker.ui.gear_preview import mount_gear_preview


def test_preview_build_missing_does_not_break_other_routes(tmp_path: Path) -> None:
    app = FastAPI()
    mount_gear_preview(app, bundle_dir=tmp_path / "absent")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get("/gear")
        assert response.status_code == 503
        assert "/gear-legacy" in response.text
        assert client.get("/healthz").status_code == 200
        assert client.get("/gear-ui/assets/missing.js").status_code == 404
        assert client.get("/gear-sprites/4151.png").headers["content-type"] == "image/png"


def test_preview_uses_stable_assets_and_precedes_root_mount(tmp_path: Path) -> None:
    bundle = tmp_path / "build"
    bundle.mkdir()
    (bundle / "index.html").write_text('<script src="/gear-ui/assets/app.js"></script>')
    (bundle / "assets").mkdir()
    (bundle / "assets/app.js").write_text("console.log('fixture')")
    (tmp_path / "secret.txt").write_text("outside bundle")
    app = FastAPI()
    mount_gear_preview(app, bundle_dir=bundle)
    root = FastAPI()

    @root.get("/gear-legacy")
    def old_gear() -> dict[str, str]:
        return {"gear": "retained"}

    app.mount("/", root)
    with TestClient(app) as client:
        for alias in ("/gear/", "/gear-next", "/gear-next/"):
            response = client.get(alias + "?mode=fixture", follow_redirects=False)
            assert response.status_code == 307
            assert response.headers["location"] == "/gear?mode=fixture"
        assert client.get("/gear").headers["cache-control"] == "no-cache"
        assert "/gear-ui/assets/app.js" in client.get("/gear/results/example").text
        assert "/gear-ui/assets/app.js" in client.get("/gear-next/").text
        assert client.get("/gear-ui/assets/app.js").status_code == 200
        assert client.get("/gear-ui/%2e%2e/secret.txt").status_code == 404
        assert client.get("/gear-legacy").json() == {"gear": "retained"}
