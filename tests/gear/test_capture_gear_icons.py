"""Offline icon capture rejects bad responses and preserves existing artwork."""

import hashlib
import json
import shutil
from pathlib import Path

import httpx
import pytest

from tools.capture_gear_icons import MIRROR, capture, download


@pytest.fixture
def icon_root(tmp_path):
    shutil.copytree("content", tmp_path / "content")
    folder = tmp_path / "tracker/ui/assets/items"
    folder.mkdir(parents=True)
    shutil.copy("tracker/ui/assets/items/source.json", folder / "source.json")
    return tmp_path, folder


def mock_client(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(
        "tools.capture_gear_icons.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_default_capture_includes_community_equipment(icon_root, monkeypatch):
    from tracker.content.loader import load_content
    from tracker.gear.catalog import load_catalog

    root, folder = icon_root
    catalog = load_catalog(load_content(root / "content"), root / "content/equipment")
    assert 30895 in catalog.community_items
    assert not catalog.items[30895].content_ids
    selected = {item.id for item in catalog.items.values() if item.content_ids}
    selected.update(catalog.community_items)
    for item_id in selected - {30895}:
        (folder / f"{item_id}.png").write_bytes(b"existing artwork")
    payload = Path("tracker/ui/assets/items/7462.png").read_bytes()
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=payload)

    mock_client(monkeypatch, respond)
    assert capture(root, []) == 0
    assert calls == ["https://static.runelite.net/cache/item/icon/30895.png"]
    assert (folder / "30895.png").read_bytes() == payload


def test_capture_skips_existing_and_records_exact_bytes(icon_root, monkeypatch):
    root, folder = icon_root
    payload = Path("tracker/ui/assets/items/7462.png").read_bytes()
    existing = folder / "7459.png"
    existing.write_bytes(b"existing artwork")
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=payload)

    mock_client(monkeypatch, respond)
    assert capture(root, [7460, 7459, 7460]) == 0
    assert calls == ["https://static.runelite.net/cache/item/icon/7460.png"]
    assert existing.read_bytes() == b"existing artwork"
    assert (folder / "7460.png").read_bytes() == payload
    source = json.loads((folder / "source.json").read_text())
    assert source["additional_captures"]["7460"]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_bad_response_does_not_create_sprite_or_change_provenance(icon_root, monkeypatch):
    root, folder = icon_root
    original = (folder / "source.json").read_bytes()
    mock_client(monkeypatch, lambda request: httpx.Response(200, content=b"<html>Error</html>"))
    assert capture(root, [7460]) == 1
    assert not (folder / "7460.png").exists()
    assert (folder / "source.json").read_bytes() == original


def test_preview_and_unknown_ids_do_not_fetch(icon_root, monkeypatch):
    root, folder = icon_root

    def unexpected(**kwargs):
        pytest.fail("No network expected")

    monkeypatch.setattr("tools.capture_gear_icons.httpx.Client", unexpected)
    assert capture(root, [7460], dry_run=True) == 0
    assert not (folder / "7460.png").exists()
    with pytest.raises(ValueError, match="absent from physical equipment catalog"):
        capture(root, [99999999])


def test_primary_failure_uses_runelite_repository_and_records_actual_source(icon_root, monkeypatch):
    root, folder = icon_root
    payload = Path("tracker/ui/assets/items/7462.png").read_bytes()

    def respond(request):
        if request.url.host == "static.runelite.net":
            raise httpx.ConnectError("Host unavailable", request=request)
        return httpx.Response(200, content=payload)

    mock_client(monkeypatch, respond)
    assert capture(root, [7460]) == 0
    source = json.loads((folder / "source.json").read_text())
    assert source["additional_captures"]["7460"]["source"] == MIRROR.format(item_id=7460)


def test_transient_connection_failure_retries_same_source():
    payload = Path("tracker/ui/assets/items/7462.png").read_bytes()
    calls = []

    def respond(request):
        calls.append(request.url)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("Transient failure", request=request)
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert download(client, MIRROR.format(item_id=7460)) == payload
    assert len(calls) == 2 and calls[0] == calls[1]
