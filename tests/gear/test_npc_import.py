"""Refreshing stats must not discard known NPC mechanic restrictions."""

import json
import sys

import pytest

from tools.import_npcs import main


def invoke(monkeypatch, tmp_path, manifest):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([{"id": 1, "name": "Example", "skills": {}, "defensive": {}}]),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()
    if manifest is not None:
        (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_npcs", "--source", str(source), "--revision", "a" * 40, "--output", str(output)],
    )
    return output


def test_import_preserves_exception_rules_and_provenance(monkeypatch, tmp_path):
    exceptions = {
        "11778": {
            "reasons": ["Raid scaling is unsupported."],
            "source_url": "https://example.com/pinned-rules",
        }
    }
    output = invoke(
        monkeypatch,
        tmp_path,
        {"mechanic_exceptions": exceptions, "reviewed_profiles": {"1": {"name": "Old"}}},
    )
    main()
    refreshed = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert refreshed["mechanic_exceptions"] == exceptions
    assert refreshed["source_revision"] == "a" * 40
    assert refreshed["reviewed_profiles"] == {}


@pytest.mark.parametrize("manifest", [None, {}, {"mechanic_exceptions": {}}])
def test_import_refuses_missing_exception_policy_before_writes(monkeypatch, tmp_path, manifest):
    output = invoke(monkeypatch, tmp_path, manifest)
    original = (output / "manifest.json").read_bytes() if manifest is not None else None
    with pytest.raises(SystemExit, match="2"):
        main()
    assert not (output / "monsters.json").exists()
    if original is not None:
        assert (output / "manifest.json").read_bytes() == original
