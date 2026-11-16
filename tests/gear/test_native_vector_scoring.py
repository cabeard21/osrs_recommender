"""Concrete native options retain every requested objective without scalar ranking."""

from types import SimpleNamespace

import pytest

from tests.gear.test_native_scoring import context
from tracker.gear.combat_options import CombatOption
from tracker.gear.optimizer import CombatOptionFilters


def vector_context():
    search = context()
    role = search.request.roles[0].model_copy(
        update={
            "combat_options": CombatOptionFilters(
                attack_types=("slash",), stances=("accurate", "defensive"), spells=()
            )
        }
    )
    search.request.roles = (role,)
    search.request.objectives = (
        SimpleNamespace(
            kind="defence_roll", styles=("stab", "magic"), aggregation="minimum", id="weakest"
        ),
        SimpleNamespace(
            kind="defence_roll", styles=("slash", "ranged"), aggregation="mean", id="average"
        ),
        SimpleNamespace(kind="accuracy", styles=(), aggregation=None, id="accuracy"),
        SimpleNamespace(kind="prayer_bonus", styles=(), aggregation=None, id="prayer"),
    )
    search.configured_options = lambda role, weapon: tuple(
        (
            role.model_copy(update={"stance": stance}),
            CombatOption(attack_type="slash", stance=stance),
        )
        for stance in ("accurate", "defensive")
    )
    return search


def test_native_vectors_retain_concrete_options_and_project_each_objective():
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = vector_context()
    scoring = native.ScoringContext(search)
    rows = scoring.score_variants({"weapon": 1, "head": 2}, 0)
    assert len(rows) == 2
    assert {scoring.option_records[row["option_index"]][1].stance for row in rows} == {
        "accurate",
        "defensive",
    }
    for row in rows:
        values, rolls = row["objective_values"], row["player_defence_rolls"]
        assert values["weakest"] == min(rolls["stab"], rolls["magic"])
        assert values["average"] == (rolls["slash"] + rolls["ranged"]) / 2
        assert values["accuracy"] == row["accuracy"]
        assert values["prayer"] == 0
    assert rows[0]["objective_values"]["weakest"] != rows[1]["objective_values"]["weakest"]


def test_native_vectors_require_every_selected_defensive_component():
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = vector_context()
    search.levels = {key: value for key, value in search.levels.items() if key != "magic"}
    with pytest.raises(ValueError, match="unavailable"):
        native.ScoringContext(search).score_variants({"weapon": 1}, 0)


def test_native_vectors_reject_invalid_role_and_equipment():
    native = pytest.importorskip("tracker.gear.native._scoring")
    scoring = native.ScoringContext(vector_context())
    with pytest.raises(ValueError, match="role"):
        scoring.score_variants({"weapon": 1}, -1)
    with pytest.raises(ValueError, match="equipment"):
        scoring.score_variants({"weapon": 999999}, 0)


@pytest.mark.parametrize("equipment", [{"weapon": 1, "head": 2}, {"weapon": 1}, {}, {"head": 1}])
def test_native_projection_matches_all_concrete_component_maxima(equipment):
    native = pytest.importorskip("tracker.gear.native._scoring")
    search = vector_context()
    scoring = native.ScoringContext(search)
    rows = scoring.score_variants(equipment, 0)
    actual = scoring.score_projection(equipment, 0)
    expected = (
        None
        if not rows
        else (
            max(row["dps"] for row in rows),
            *(
                max(row["objective_values"][objective.id] for row in rows)
                for objective in search.request.objectives
            ),
        )
    )
    assert actual == expected


def test_native_projection_preserves_negative_components_and_unknown_level_errors():
    from tracker.gear.models import EquipmentBonuses

    native = pytest.importorskip("tracker.gear.native._scoring")
    search = vector_context()
    search.items[2] = search.items[2].model_copy(update={"bonuses": EquipmentBonuses(prayer=-5)})
    scoring = native.ScoringContext(search)
    assert scoring.score_projection({"weapon": 1, "head": 2}, 0)[-1] == -5
    search.levels = {key: value for key, value in search.levels.items() if key != "magic"}
    with pytest.raises(ValueError, match="unavailable"):
        native.ScoringContext(search).score_projection({"weapon": 1}, 0)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_all_62_native_objectives_match_python_per_concrete_option(style):
    from itertools import combinations

    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.objectives import ObjectiveDescriptor, canonical_objectives, objective_values
    from tracker.gear.scoring import prepare_equipment

    native = pytest.importorskip("tracker.gear.native._scoring")
    search = context(style)
    styles = ("stab", "slash", "crush", "ranged", "magic")
    search.request.objectives = canonical_objectives(
        [
            *[
                ObjectiveDescriptor(kind="defence_roll", styles=subset, aggregation=aggregation)
                for count in range(1, 6)
                for subset in combinations(styles, count)
                for aggregation in ("minimum", "mean")
            ],
            *[
                ObjectiveDescriptor(kind=kind)
                for kind in (
                    "prayer_bonus",
                    "melee_strength_bonus",
                    "ranged_strength_bonus",
                    "magic_damage_bonus",
                    "accuracy",
                )
            ],
        ]
    )
    assert len(search.request.objectives) == 62
    search.items[2] = search.items[2].model_copy(
        update={
            "bonuses": EquipmentBonuses(
                magic_damage=3.7,
                melee_strength=-2,
                ranged_strength=9,
                prayer=4,
                defence_stab=-100,
                defence_slash=10,
                defence_crush=50,
                defence_ranged=-63,
                defence_magic=11,
            )
        }
    )
    role = search.request.roles[0].model_copy(
        update={"spell": "fire_wave"} if style == "magic" else {}
    )
    search.request.roles = (role,)
    equipment = {"weapon": 1, "head": 2}
    scoring = native.ScoringContext(search)
    rows = scoring.score_variants(equipment, 0)
    assert rows
    assert scoring.score_projection(equipment, 0) == (
        max(row["dps"] for row in rows),
        *(
            max(row["objective_values"][objective.id] for row in rows)
            for objective in search.request.objectives
        ),
    )
    for row in rows:
        configured, _ = scoring.option_records[row["option_index"]]
        expected = evaluate_prepared_score(
            prepare_equipment([search.items[i] for i in equipment.values()]),
            configured,
            search.levels,
            include_defence=True,
        )
        assert row["dps"] == expected.dps
        assert row["objective_values"] == objective_values(
            search.request.objectives,
            {
                "supported": expected.supported,
                "accuracy": expected.accuracy,
                "bonuses": expected.bonuses.model_dump(),
                "player_defence_rolls": expected.player_defence_rolls,
            },
        )


def test_native_stream_exposes_candidates_before_beam_retention():
    from tests.gear.test_native_stages import ScoringContext, StageContext, stage_search

    with stage_search() as search:
        stage = StageContext(ScoringContext(search), search).begin(
            kind="loadout",
            states=[{"weapon": 2}],
            choices=[201, 202, 203],
            slot="head",
            roles=("z",),
        )
        while not stage.done:
            stage.advance(1024)
        rows = list(stage.complete_candidates())
        assert len(rows) == 3
        retained = stage.finish(1)
        assert len(retained) == 1
        assert retained[0] in rows
        with pytest.raises(ValueError, match="finalized"):
            list(stage.complete_candidates())


def test_adapter_captures_all_final_assignments_before_retention():
    from unittest.mock import Mock

    from tests.gear.test_native_stages import ScoringContext, stage_search
    from tracker.gear.native.adapter import expand

    with stage_search() as search:
        search.native_context = ScoringContext(search)
        search.native_limit = 1000
        search.vector_search = Mock()
        states = [{"weapon": 2, "head": item} for item in (201, 202, 203)]
        retained = expand(
            search, "loadout", states, [None], slot="ring", roles=search.request.roles, limit=1
        )
        assert len(retained) == 1
        assert search.vector_search.capture_base.call_count == 3
        assert [call.args[0] for call in search.vector_search.capture_base.call_args_list] == [
            {"z": row} for row in states
        ]
        assert all(call.kwargs == {} for call in search.vector_search.capture_base.call_args_list)
