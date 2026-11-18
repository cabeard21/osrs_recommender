"""Vector search retains complete tradeoffs before bounded beam selection."""

import pytest

from tests.gear.test_optimizer import run, weapon
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig


def test_vector_frontier_keeps_joint_interior_and_equal_vector_resource_representative():
    heads = [
        EquipmentDefinition(
            id=item_id,
            name=str(item_id),
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(defence_stab=stab, defence_magic=magic),
        )
        for item_id, stab, magic in [(2, 1, 9), (3, 9, 1), (4, 6, 6), (5, 6, 6)]
    ]
    result = run(
        [weapon(1, "slash"), *heads],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        objectives=[
            {"kind": "defence_roll", "styles": ["stab"]},
            {"kind": "defence_roll", "styles": ["magic"]},
        ],
    )
    points = result["objective_frontiers"][0]["points"]
    assert len(points) == 3
    assert {point["solution"]["loadouts"]["a"]["equipment"]["head"] for point in points} >= {2, 3}
    assert any(set(point["solution"]["objective_values"].values()) == {78 * 70} for point in points)


def test_vector_options_preserve_defensive_stance_tradeoff():
    result = run(
        [weapon(1, "ranged", 40, attack_profiles=(("ranged", "rapid"), ("ranged", "longrange")))],
        (
            RoleConfig(
                id="a",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("light",),
                    stances=("rapid", "longrange"),
                    spells=(),
                ),
            ),
        ),
        max_swaps=0,
        max_dps_loss_pct=100,
        objectives=[{"kind": "defence_roll", "styles": ["stab"]}],
    )
    points = result["objective_frontiers"][0]["points"]
    stances = {point["solution"]["loadouts"]["a"]["combat_option"]["stance"] for point in points}
    assert stances == {"rapid", "longrange"}
    assert result["selected_solution"]["objective_values"]


def test_empty_objectives_is_explicit_vector_dps_only():
    result = run(
        [weapon(1, "slash")], (RoleConfig(id="a", style="slash"),), max_swaps=0, objectives=[]
    )
    assert result["objective_definitions"] == []
    assert len(result["objective_frontiers"][0]["points"]) == 1
    assert result["selected_solution"]["objective_values"] == {}
    assert result["search"]["objective_frontier"]["expansion_limit"] == 0
    assert result["search"]["objective_frontier"]["explored_nodes"] == 0


def test_exhausted_option_products_resume_in_later_reserved_phase(monkeypatch):
    from tracker.gear.vector_search import VectorSearch

    def explore(engine, seeds):
        seed = next(row for row in seeds if row is not None)
        assignment = {key: row["equipment"] for key, row in seed["loadouts"].items()}
        engine.phase_limit = 1
        engine.capture(assignment)
        row = engine.seen.execute(
            "SELECT cursor,complete FROM seen_assignments WHERE identity=?",
            (engine.identity(assignment),),
        ).fetchone()
        assert row == (1, 0)
        engine.phase_limit = 100
        engine.capture(assignment)
        assert (
            engine.seen.execute(
                "SELECT complete FROM seen_assignments WHERE identity=?",
                (engine.identity(assignment),),
            ).fetchone()[0]
            == 1
        )
        return engine.publish()

    monkeypatch.setattr(VectorSearch, "explore", explore)
    result = run(
        [weapon(1, "ranged", 40, attack_profiles=(("ranged", "rapid"), ("ranged", "longrange")))],
        (
            RoleConfig(
                id="a",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("light",),
                    stances=("rapid", "longrange"),
                    spells=(),
                ),
            ),
        ),
        max_swaps=0,
        max_dps_loss_pct=100,
        objectives=[{"kind": "defence_roll", "styles": ["stab"]}],
    )
    assert len(result["objective_frontiers"][0]["points"]) == 2


def test_cancelled_search_removes_all_owned_temporary_archives(monkeypatch, tmp_path):
    import tracker.gear.vector_archive as archive_module
    from tracker.gear.vector_search import VectorSearch

    original = archive_module.tempfile.mkstemp

    def temporary_archive(*args, **kwargs):
        return original(*args, **{**kwargs, "dir": tmp_path})

    def cancel(*args, **kwargs):
        raise ValueError("optimization_cancelled")

    monkeypatch.setattr(archive_module.tempfile, "mkstemp", temporary_archive)
    monkeypatch.setattr(VectorSearch, "explore", cancel)
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(
            [weapon(1, "slash")],
            (RoleConfig(id="a", style="slash"),),
            max_swaps=0,
            objectives=[{"kind": "prayer_bonus"}],
        )
    assert not list(tmp_path.glob("gear-vector-*.sqlite3"))


def test_group_metric_leader_survives_crowded_component_specialists(monkeypatch):
    from tracker.gear.vector_search import VectorSearch

    heads = [
        EquipmentDefinition(
            id=index + 10,
            name=str(index),
            slot="head",
            requirements_complete=True,
            bonuses=EquipmentBonuses(
                defence_stab=100 if index < 30 else 0, defence_magic=0 if index < 30 else 100
            ),
        )
        for index in range(60)
    ]
    balanced = EquipmentDefinition(
        id=1000,
        name="Balanced",
        slot="head",
        requirements_complete=True,
        bonuses=EquipmentBonuses(defence_stab=60, defence_magic=60),
    )
    original = VectorSearch.candidate_pools

    def pools(engine):
        result = original(engine)
        assert 1000 in result["head"]
        return result

    monkeypatch.setattr(VectorSearch, "candidate_pools", pools)
    result = run(
        [weapon(1, "slash"), *heads, balanced],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        objectives=[{"kind": "defence_roll", "styles": ["stab", "magic"]}],
    )
    points = result["objective_frontiers"][0]["points"]
    assert len(points) == 1
    assert points[0]["solution"]["loadouts"]["a"]["equipment"]["head"] == 1000


@pytest.mark.parametrize(
    ("style", "locked", "ranged_strength", "expected_ammunition", "expected_prayer"),
    [
        ("slash", False, False, 20226, 1),
        ("slash", True, False, 882, 0),
        ("ranged", False, False, 882, 0),
        ("slash", False, True, 882, 0),
    ],
)
def test_vector_frontier_checks_prayer_ammunition_beyond_refinement_seeds(
    monkeypatch, style, locked, ranged_strength, expected_ammunition, expected_prayer
):
    from tracker.gear.vector_search import VectorSearch

    original_explore = VectorSearch.explore
    equipment = {"weapon": 1, "ammunition": 882}

    def explore(engine, _seeds):
        return original_explore(engine, ())

    def bounded_equipment(engine, *_args, **_kwargs):
        engine.capture({"a": equipment})
        return [equipment]

    # Isolate a frontier member whose alternate ammo assignment was missed.
    monkeypatch.setattr(VectorSearch, "capture_base", lambda *_args: None)
    monkeypatch.setattr(VectorSearch, "explore", explore)
    monkeypatch.setattr(VectorSearch, "equipment", bounded_equipment)
    monkeypatch.setattr("tracker.gear.vector_refinement._seeds", lambda *_args: [])
    monkeypatch.setattr("tracker.gear.optimizer.needs_running_cost_frontier", lambda *_args: False)

    items = [
        weapon(1, style, 30, ammo_for=("arrow:882",) if style == "ranged" else ()),
        EquipmentDefinition(
            id=882,
            name="Bronze arrow",
            slot="ammunition",
            ammo_type="arrow:882",
            bonuses=EquipmentBonuses(ranged_strength=7),
            requirements_complete=True,
        ),
        EquipmentDefinition(
            id=20226,
            name="Peaceful blessing",
            slot="ammunition",
            ammo_type="bolt:20226",
            bonuses=EquipmentBonuses(prayer=1),
            requirements_complete=True,
        ),
    ]
    role = RoleConfig(id="a", style=style, locks={"ammunition": 882} if locked else {})
    objectives = [{"kind": "defence_roll", "styles": ["slash"]}, {"kind": "prayer_bonus"}]
    if ranged_strength:
        objectives.append({"kind": "ranged_strength_bonus"})
    original = run(items[:-1], (role,), max_swaps=0, objectives=objectives)
    expected = original["objective_frontiers"][0]["points"][0]["solution"]
    result = run(items, (role,), max_swaps=0, objectives=objectives)
    (point,) = result["objective_frontiers"][0]["points"]
    solution = point["solution"]
    assert solution["loadouts"]["a"]["equipment"]["ammunition"] == expected_ammunition
    assert solution["objective_values"]["prayer_bonus"] == expected_prayer
    assert solution["purchase_cost_gp"] == 0
    assert solution["score"] == expected["score"]
    slash_defence = "defence_roll:minimum:slash"
    defence = solution["objective_values"][slash_defence]
    assert defence == expected["objective_values"][slash_defence]
    assert solution["loadouts"]["a"]["combat_option"] == expected["loadouts"]["a"]["combat_option"]
