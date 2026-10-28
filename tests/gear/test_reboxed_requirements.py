import hashlib
import json

import pytest

from tools.import_reboxed_requirements import build_import
from tracker.gear.catalog import load_catalog
from tracker.gear.requirements_source import requirement_from_levels, requirement_state


@pytest.mark.parametrize(
    ("row", "state"),
    [
        (None, "unmatched"),
        ([], "invalid_record"),
        ({}, "no_equipment"),
        ({"equipment": {}}, "missing"),
        ({"equipment": {"requirements": None}}, "null"),
        ({"equipment": {"requirements": {}}}, "empty"),
        ({"equipment": {"requirements": {"attack": 40}}}, "populated"),
    ],
)
def test_requirement_states_remain_distinct(row, state):
    assert requirement_state(row) == state


@pytest.mark.parametrize(
    "levels",
    [{}, {"attack": True}, {"attack": 100}, {"attack": "40"}, {"sailing": 99}, {"combat": 2}],
)
def test_invalid_maps_fail_closed(levels):
    with pytest.raises(ValueError):
        requirement_from_levels(levels, {"attack"})


def test_combat_is_a_combat_gate_not_a_skill():
    requirement = requirement_from_levels({"attack": 40, "combat": 70}, {"attack"})
    assert requirement.to_yaml() == {"all_of": [{"skill": {"attack": 40}}, {"combat_level": 70}]}


def test_import_exact_ids_validates_and_does_not_mutate(make_content):
    rows = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]
    source = {
        "1": {"id": 1, "equipment": {"requirements": {"attack": 40}}},
        "2": {"id": 2, "equipment": {"requirements": None}},
        "3": {"id": 3, "equipment": {"requirements": {}}},
        "4": {"id": 4, "equipment": {"requirements": {"sailing": 99}}},
        "5": {"id": 6, "equipment": {"requirements": {"attack": 40}}},
        "99": {"id": 99, "equipment": {"requirements": {"attack": 40}}},
    }
    before = json.dumps(source)
    imported, exceptions = build_import(source, rows, make_content().skills)
    assert imported == {"1": {"attack": 40}}
    assert exceptions == {
        "2": "null",
        "3": "empty",
        "4": "invalid_requirements",
        "5": "identity_mismatch",
    }
    assert json.dumps(source) == before


def test_loader_preserves_approved_gates_ungated_effects_and_physics(
    tmp_path, make_content, make_item
):
    rows = [
        {
            "id": i,
            "name": str(i),
            "slot": "head",
            "bonuses": {"melee_strength": 7},
            "unsupported_effects": ["Unreviewed effect"],
        }
        for i in range(1, 5)
    ]
    payload = json.dumps(rows).encode()
    (tmp_path / "catalog.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"catalog_sha256": hashlib.sha256(payload).hexdigest()})
    )
    content = make_content(
        items=[
            make_item("approved", numeric_id=1, requires={"skill": {"attack": 60}}),
            make_item("ungated", numeric_id=2),
            make_item("unknown", numeric_id=3, gate_unknown=True),
        ]
    )
    before = load_catalog(content, tmp_path)
    sidecar = {
        "source": {"commit": "a" * 40, "sha256": "b" * 64},
        "items": {str(i): {"attack": 40} for i in range(1, 5)},
    }
    (tmp_path / "requirements.json").write_text(json.dumps(sidecar))
    after = load_catalog(content, tmp_path)
    for i in range(1, 4):
        assert before.items[i] == after.items[i]
    assert after.items[4].requires.to_yaml() == {"skill": {"attack": 40}}
    assert not after.items[4].requirements_complete
    assert after.items[4].unsupported_effects == before.items[4].unsupported_effects
    assert after.items[4].bonuses == before.items[4].bonuses
    assert after.revision != before.revision


def test_loader_rejects_invalid_sidecar(tmp_path, make_content):
    payload = b"[]"
    (tmp_path / "catalog.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"catalog_sha256": hashlib.sha256(payload).hexdigest()})
    )
    (tmp_path / "requirements.json").write_text(json.dumps({"items": {"1": {"attack": True}}}))
    with pytest.raises(ValueError):
        load_catalog(make_content(), tmp_path)


def test_reduced_registry_can_load_bundled_partial_source(make_content):
    catalog = load_catalog(make_content(skills=("attack",)))
    assert not catalog.items[4587].requirements_complete
    assert catalog.items[4587].requires.to_yaml() == {"skill": {"attack": 60}}
    # Reject a whole map needing an unregistered skill, rather than drop that gate.
    assert catalog.items[1127].requires is None


def test_real_catalog_only_adds_partial_trees():
    from tracker.content.loader import load_content

    content = load_content()
    before = load_catalog(content, use_requirements_source=False)
    after = load_catalog(content)
    assert set(before.items) == set(after.items)
    added = 0
    for key, original in before.items.items():
        imported = after.items[key]
        if original.content_ids:
            assert imported == original
        else:
            assert imported.model_dump(exclude={"requires"}) == original.model_dump(
                exclude={"requires"}
            )
            added += original.requires is None and imported.requires is not None
    assert added == 1719


def test_cli_import_report_and_repeatability(tmp_path, capsys):
    from tools.import_reboxed_requirements import main
    from tracker.content.loader import load_content

    root = tmp_path / "content"
    equipment = root / "equipment"
    equipment.mkdir(parents=True)
    (root / "skills").mkdir()
    (root / "skills" / "skills.yaml").write_text("- {id: attack, name: Attack}\n")
    rows = [{"id": 1, "name": "One", "slot": "head"}]
    physical = json.dumps(rows).encode()
    (equipment / "catalog.json").write_bytes(physical)
    manifest = json.dumps({"catalog_sha256": hashlib.sha256(physical).hexdigest()})
    (equipment / "manifest.json").write_text(manifest)
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"1": {"id": 1, "equipment": {"requirements": {"attack": 40}}}}))
    output, report_path = equipment / "requirements.json", tmp_path / "report.json"
    args = [
        "--source",
        str(source),
        "--commit",
        "a" * 40,
        "--content",
        str(root),
        "--output",
        str(output),
        "--report",
        str(report_path),
    ]
    main(args)
    first = output.read_bytes(), report_path.read_bytes()
    main(args)
    assert first == (output.read_bytes(), report_path.read_bytes())
    report = json.loads(report_path.read_text())
    assert report["new_partial_requirement_ids"] == [1]
    assert report["after"]["complete_gates"] == 0
    assert report["after"]["with_requirement_tree"] == 1
    assert not load_catalog(load_content(root), equipment).items[1].requirements_complete
    assert (equipment / "catalog.json").read_bytes() == physical
    assert (equipment / "manifest.json").read_text() == manifest
    assert capsys.readouterr().out
    for invalid in [
        ["--commit", "master"],
        ["--output", str(source)],
        ["--report", str(equipment / "catalog.json")],
        ["--report", str(output)],
        ["--output", str(root / "items" / "approved.yaml")],
    ]:
        with pytest.raises(SystemExit):
            main(args + invalid)


def test_report_skill_agreement_and_gate_exceptions(make_content, make_item):
    from tools.import_reboxed_requirements import coverage_report
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.models import EquipmentDefinition

    content = make_content(
        items=[
            make_item(
                "one",
                numeric_id=1,
                requires={
                    "all_of": [
                        {"skill": {"attack": 40}},
                        {"skill": {"attack": 30}},
                        {"quest": "test"},
                    ]
                },
            ),
            make_item("two", numeric_id=2, requires={"skill": {"attack": 60}}),
            make_item(
                "three",
                numeric_id=3,
                requires={"any_of": [{"skill": {"attack": 40}}, {"skill": {"magic": 40}}]},
            ),
        ]
    )
    catalog = EquipmentCatalog(
        {
            i: EquipmentDefinition(
                id=i,
                name=str(i),
                slot="head",
                requires=item.requires,
                requirements_complete=True,
                content_ids=(item.id,),
            )
            for i, item in enumerate(content.items.values(), 1)
        }
    )
    items = {"1": {"attack": 40}, "2": {"attack": 40}, "3": {"attack": 40}}
    source = {key: {"equipment": {"requirements": value}} for key, value in items.items()}
    report = coverage_report(source, catalog, items, {})
    assert report["reviewed_comparison"] == {"agree": 1, "disagree": 1, "not_comparable": 1}
    assert report["disagreements"][0]["id"] == 2


def test_import_rejects_malformed_and_incomplete_records(make_content):
    source = {
        "1": "bad",
        "2": {"id": 2, "incomplete": True, "equipment": {"requirements": {"attack": 40}}},
    }
    imported, exceptions = build_import(source, [{"id": 1}, {"id": 2}], make_content().skills)
    assert imported == {}
    assert exceptions == {"1": "invalid_record", "2": "source_incomplete"}
    with pytest.raises(ValueError):
        build_import([], [], make_content().skills)
