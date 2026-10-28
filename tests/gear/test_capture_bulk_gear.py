"""Maintenance capture binds exact Wiki identities to pinned upstream bytes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools.capture_bulk_gear import capture, main

FAMILY_PATH = Path("content/equipment/reviews/families/metal_chainbodies.json")


class Response:
    def __init__(self, payload, content=None):
        self.payload = payload
        self.content = json.dumps(payload).encode() if content is None else content
        self.checked = False

    def raise_for_status(self):
        self.checked = True

    def json(self):
        return self.payload


@pytest.fixture
def setup_capture(tmp_path, monkeypatch):
    family = json.loads(FAMILY_PATH.read_text(encoding="utf-8"))
    sources = json.loads(Path(family["source_file"]).read_text(encoding="utf-8"))
    provenance = json.loads(Path("content/equipment/manifest.json").read_text(encoding="utf-8"))
    physical = json.loads(Path("content/equipment/catalog.json").read_text(encoding="utf-8"))
    exports = Response(sources["equipment_rows"])
    provenance["capture_sha256"] = hashlib.sha256(exports.content).hexdigest()
    folder = tmp_path / "content/equipment"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(provenance), encoding="utf-8")
    (folder / "catalog.json").write_text(json.dumps(physical), encoding="utf-8")
    wiki = Response(
        {
            "query": {
                "pages": [
                    {
                        "title": page["title"],
                        "revisions": [
                            {
                                "revid": page["revision"],
                                "timestamp": page["timestamp"],
                                "slots": {"main": {"content": page["wikitext"]}},
                            }
                        ],
                    }
                    for page in sources["pages"].values()
                ]
            }
        }
    )
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 30
            assert kwargs["follow_redirects"]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return exports if "raw.githubusercontent.com" in url else wiki

    monkeypatch.setattr("tools.capture_bulk_gear.httpx.Client", Client)
    return tmp_path, family, sources, provenance, exports, wiki, calls


def test_capture_binds_pinned_rows_and_permanent_exact_id_pages(setup_capture):
    root, family, sources, provenance, exports, wiki, calls = setup_capture
    result = capture(root, family)
    assert result["schema_version"] == 1
    assert result["equipment_source"]["capture_sha256"] == provenance["capture_sha256"]
    assert result["equipment_rows"] == sources["equipment_rows"]
    assert result["pages"] == sources["pages"]
    assert exports.checked and wiki.checked
    assert provenance["revision"] in calls[0][0]
    assert calls[1][1]["params"]["rvprop"] == "ids|timestamp|content"
    assert "approved_effect_clearance" not in result


def test_capture_rejects_changed_pinned_export(setup_capture):
    root, family, _, _, exports, _, _ = setup_capture
    exports.content += b"\n"
    with pytest.raises(ValueError, match="checksum"):
        capture(root, family)


def test_capture_requires_existing_pinned_revision(setup_capture):
    root, family, _, provenance, _, _, calls = setup_capture
    provenance["revision"] = None
    (root / "content/equipment/manifest.json").write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError, match="pinned equipment revision"):
        capture(root, family)
    assert not calls


@pytest.mark.parametrize("mismatch", ("missing", "ambiguous", "multi_form", "title", "unknown_id"))
def test_missing_ambiguous_and_mismatched_pages_are_not_identity_evidence(setup_capture, mismatch):
    root, family, _, _, _, wiki, _ = setup_capture
    page = wiki.payload["query"]["pages"][0]
    wiki.payload["query"]["pages"] = [page]
    if mismatch == "missing":
        page.pop("revisions")
    elif mismatch == "title":
        page["title"] = "Unrelated physical form"
    else:
        text = page["revisions"][0]["slots"]["main"]
        text["content"] = {
            "ambiguous": "|id = 1113\n|id = 1101\n",
            "multi_form": "|id = 1113, 1101\n",
            "unknown_id": "|id = 999999999\n",
        }[mismatch]
    assert capture(root, family)["pages"] == {}


def test_cli_capture_writes_only_evidence(setup_capture, monkeypatch, capsys):
    root, family, _, _, _, _, _ = setup_capture
    family_path = root / "family.json"
    family_path.write_text(json.dumps(family), encoding="utf-8")
    output = root / "evidence/sources.json"
    before = {path: path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "capture_bulk_gear",
            "--root",
            str(root),
            "--family",
            str(family_path),
            "--output",
            str(output),
        ],
    )
    main()
    assert "no approvals changed" in capsys.readouterr().out
    assert len(json.loads(output.read_text(encoding="utf-8"))["pages"]) == 7
    assert before == {
        path: path.read_bytes() for path in (root / "content").rglob("*") if path.is_file()
    }
