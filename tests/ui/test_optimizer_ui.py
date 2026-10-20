"""Optimizer request semantics and stale-result protection."""

from __future__ import annotations

import pytest

from tracker.ui.gear import OptimizationRun, _assignments, _whole, request_values


def test_solution_labels_melee_and_ranged_strength_separately(monkeypatch):
    from nicegui import ui
    from nicegui.client import Client
    from nicegui.page import page

    from tracker.ui.gear import _solution

    labels = []
    original_label = ui.label

    def record_label(text):
        labels.append(text)
        return original_label(text)

    monkeypatch.setattr(ui, "label", record_label)
    client = Client(page("/bonus-label-test"))
    try:
        with client:
            _solution(
                {
                    "loadouts": {
                        "melee": {
                            "equipment": {},
                            "performance": {
                                "bonuses": {"melee_strength": 65, "ranged_strength": 10}
                            },
                        }
                    }
                },
                {},
            )
        assert "Melee strength bonus: +65" in labels
        assert "Ranged strength bonus: +10" in labels
    finally:
        client.delete()


def test_base_transitions_and_empty_lock() -> None:
    request = request_values(
        roles=[{"id": "melee", "style": "slash"}, {"id": "magic", "style": "magic"}],
        base_role="melee",
        transition_mode="base",
        locks={"shield": "empty"},
    )
    assert request["transitions"] == [("melee", "magic"), ("magic", "melee")]
    assert request["locks"] == {"shield": None}
    assert request["reserved_supply_slots"] == 12


def test_ordered_roles_do_not_invent_pairwise_transitions() -> None:
    request = request_values(
        roles=[
            {"id": "a", "style": "slash"},
            {"id": "b", "style": "ranged"},
            {"id": "c", "style": "magic"},
        ],
        base_role="a",
        transition_mode="ordered",
        loop=True,
    )
    assert request["ordered_roles"] == ["a", "b", "c"]
    assert request["transitions"] == []
    assert request["loop"] is True


def test_ordered_roles_support_explicit_repeated_phases() -> None:
    request = request_values(
        roles=[{"id": "melee", "style": "slash"}, {"id": "magic", "style": "magic"}],
        transition_mode="ordered",
        phase_text="melee > magic > melee",
    )
    assert request["ordered_roles"] == ["melee", "magic", "melee"]
    assert "phase_text" not in request
    with pytest.raises(ValueError, match="phase"):
        request_values(
            roles=[{"id": "melee", "style": "slash"}],
            transition_mode="ordered",
            phase_text="melee > missing",
        )


def test_request_rejects_fractional_budget_and_invalid_transition() -> None:
    with pytest.raises(ValueError, match="whole"):
        request_values(roles=[{"id": "a", "style": "slash"}], budget_gp=0.5)
    with pytest.raises(ValueError, match="transition"):
        request_values(
            roles=[{"id": "a", "style": "slash"}],
            transition_mode="custom",
            transition_text="a > missing",
        )


def test_new_request_and_snapshot_prevent_stale_publish() -> None:
    state = OptimizationRun()
    first = state.begin("snapshot-one")
    second = state.begin("snapshot-one")
    assert not state.accepts(first, "snapshot-one")
    assert state.accepts(second, "snapshot-one")
    assert not state.accepts(second, "snapshot-two")
    state.cancel()
    assert not state.accepts(second, "snapshot-one")


def test_fractional_inventory_and_target_levels_are_not_silently_truncated() -> None:
    assert _whole(12.0, "Supply reservation") == 12
    with pytest.raises(ValueError, match="whole"):
        _whole(12.5, "Supply reservation")


def test_future_assignment_parser_preserves_explicit_facts() -> None:
    assert _assignments("\nattack=60\n magic = 70 ", numeric=True) == {"attack": 60, "magic": 70}
    assert _assignments("monkey_madness_i=complete") == {"monkey_madness_i": "complete"}
    with pytest.raises(ValueError, match="name=value"):
        _assignments("attack 60")


def test_equipment_icons_are_local_and_unknown_ids_have_a_readable_fallback():
    from tracker.ui.gear_presentation import icon_path, item_name

    assert icon_path(1333).is_file()
    assert icon_path(99999999) is None
    assert item_name(1333, {1333: {"name": "Rune scimitar"}}) == "Rune scimitar"
    assert item_name(None, {}) == "Empty"


def test_eligibility_explanation_preserves_uncertain_ownership_and_requirements():
    from tracker.ui.gear_presentation import eligibility_text

    explanation = eligibility_text(
        {
            "wear": {"status": "unknown"},
            "ownership": {"status": "unknown"},
            "acquisition": "tradeable",
        }
    )
    assert "unknown" in explanation.lower()
    assert "owned" not in explanation.lower().replace("ownership", "")
    assert "requirements" in explanation.lower()


def test_transition_actions_show_names_and_automatic_displacements():
    from tracker.ui.gear_presentation import action_text

    text = action_text(
        {
            "operation": "equip",
            "slot": "weapon",
            "item_id": 1303,
            "automatically_removed": [1187],
            "gear_inventory_slots": 3,
        },
        {1303: {"name": "Rune 2h sword"}, 1187: {"name": "Dragon sq shield"}},
    )
    assert "Equip Rune 2h sword" in text
    assert "Dragon sq shield" in text
    assert "3" in text


def test_curve_alternatives_only_apply_to_the_service_selected_loadout():
    from tracker.ui.gear_presentation import alternatives_for

    selected = {"loadouts": {"melee": {"equipment": {"weapon": 1333}}}}
    alternatives = {"weapon": [{"item_id": 1323, "score_delta": -1}]}
    answer = {"selected_solution": selected, "alternatives": alternatives}
    assert alternatives_for(answer, selected) == alternatives
    assert alternatives_for(answer, {"loadouts": {"melee": {"equipment": {"weapon": 1323}}}}) == {}
    assert alternatives_for(answer, {"loadouts": {"melee": {}, "ranged": {}}}) == {}


def test_result_eligibility_uses_fresh_projected_facts_without_mutating_catalog():
    from tracker.ui.gear_presentation import result_definitions

    observed = {1333: {"name": "Rune scimitar", "wear": {"status": "unsatisfied"}}}
    answer = {
        "items": [{"item_id": 1333, "name": "Rune scimitar", "wear": {"status": "satisfied"}}]
    }
    rendered = result_definitions(observed, answer)
    assert rendered[1333]["wear"]["status"] == "satisfied"
    assert observed[1333]["wear"]["status"] == "unsatisfied"


def test_result_renders_local_paperdoll_and_named_inventory_with_collapsed_diagnostics(monkeypatch):
    from nicegui import ui
    from nicegui.client import Client
    from nicegui.page import page

    from tracker.ui.gear import _optimizer_results

    labels = []
    original_label = ui.label

    def record_label(text):
        labels.append(str(text))
        return original_label(text)

    monkeypatch.setattr(ui, "label", record_label)
    definitions = {
        1333: {"name": "Rune scimitar", "wear": {"status": "unsatisfied"}},
        1323: {"name": "Iron scimitar", "wear": {"status": "satisfied"}},
    }
    solution = {
        "score": 3.2,
        "purchase_cost_gp": 100,
        "reserved_supply_slots": 12,
        "remaining_inventory_slots": 15,
        "carried_item_ids": [1333, 1323],
        "purchases": [{"item_id": 1333, "cost_gp": 100, "conditional": True}],
        "loadouts": {
            "melee": {
                "equipment": {"weapon": 1333},
                "performance": {
                    "dps": 3.2,
                    "accuracy": 0.8,
                    "attack_interval": 2.4,
                    "max_hit": 12,
                    "bonuses": {"melee_strength": 44},
                },
            }
        },
        "transitions": [
            {
                "from_role": "melee",
                "to_role": "ranged",
                "action_count": 1,
                "actions": [
                    {
                        "operation": "equip",
                        "slot": "weapon",
                        "item_id": 1323,
                        "gear_inventory_slots": 1,
                    }
                ],
            }
        ],
    }
    answer = {
        "selected_solution": solution,
        "curve": [{"swap_limit": 0, "relative_performance": 1.0, "solution": solution}],
        "alternatives": {"weapon": [{"item_id": 1323, "score_delta": -1.0, "purchase_cost_gp": 0}]},
        "search": {"termination_reason": "bounded_search_complete"},
        "assumptions": {"mode": "future"},
        "limitations": ["No special attacks"],
        "items": [
            {
                "item_id": 1333,
                "name": "Rune scimitar",
                "wear": {"status": "satisfied"},
                "ownership": {"status": "unknown"},
            }
        ],
    }
    client = Client(page("/gear-presentation-test"))
    try:
        with client:
            _optimizer_results(answer, definitions, on_alternative=lambda *_: None)
        elements = list(client.elements.values())
        slots = [
            e
            for e in elements
            if str(e._props.get("data-testid", "")).startswith("gear-melee-slot-")
            and e._props.get("data-testid") != "gear-melee-slot-detail"
        ]
        assert len(slots) == 11
        images = [e for e in elements if "gear-sprite" in e._classes]
        assert images
        assert all("https://" not in str(e._props.get("src", "")) for e in images)
        assert any("Requirements: satisfied" in label for label in labels)
        assert any("Equip Iron scimitar" in label for label in labels)
        assert any("conditional: ownership unknown" in label for label in labels)
        diagnostics = next(e for e in elements if e._props.get("data-testid") == "gear-diagnostics")
        assert diagnostics.value is False
        assert "Selected action limit: 0 · relative performance 100.0%" in labels
    finally:
        client.delete()
