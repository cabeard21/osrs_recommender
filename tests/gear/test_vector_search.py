"""Vector search retains complete tradeoffs before bounded beam selection."""

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
    import pytest

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
