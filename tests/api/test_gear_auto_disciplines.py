"""Single Auto request, result publication and exact evaluation contracts."""

import pytest

from tests.api.test_gear_optimizations import scenario


def auto_role(disciplines=None):
    return {
        "id": "single",
        "style": "slash",
        "stance": "accurate",
        "allowed_disciplines": disciplines or ["melee", "ranged", "magic"],
        "combat_options": {
            "attack_types": ["stab", "slash", "crush", "light", "standard", "heavy", "magic"],
            "stances": ["accurate", "aggressive", "controlled", "defensive", "rapid", "longrange"],
            "spells": ["fire_strike"],
        },
    }


def test_auto_results_and_exact_roundtrip(client, session_factory):
    body = {**scenario(client, session_factory), "roles": [auto_role()]}
    response = client.post("/ui-api/gear/optimizations", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert {r["discipline"] for r in result["discipline_comparison"]} == {
        "melee",
        "ranged",
        "magic",
    }
    selected = result["selected_solution"]["loadouts"]["single"]
    assert [r["discipline"] for r in result["discipline_results"]] == ["melee", "ranged", "magic"]
    assert result["discipline_results"][0]["selected_solution"] == result["selected_solution"]
    assert all("search" in r and "alternatives" in r for r in result["discipline_results"])
    assert selected["discipline"] == "melee"
    assert response.json()["work_budget_policy"]["discipline_count"] == 3
    assert response.json()["baseline"]["status"] == "available"
    exact = client.post(
        "/ui-api/gear/evaluations",
        json={
            "scenario": body,
            "baseline_loadouts": {"single": selected["equipment"]},
            "proposed_loadouts": {"single": selected["equipment"]},
            "proposed_combat_options": {"single": selected["combat_option"]},
        },
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["proposed"]["performance"] == selected["performance"]
    assert exact.json()["baseline"]["performance"] == selected["performance"]


@pytest.mark.parametrize("disciplines", [[], ["melee", "melee"], ["invented"]])
def test_auto_rejects_bad_allowlists(client, session_factory, disciplines):
    role = {**auto_role(), "allowed_disciplines": disciplines}
    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "roles": [role],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("auto_first", [False, True])
def test_auto_supports_multiple_roles(client, session_factory, auto_first):
    roles = [auto_role(["melee", "ranged"]), {"id": "second", "style": "slash"}]
    if not auto_first:
        roles.reverse()
    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "roles": roles,
            "max_swaps": 1,
        },
    )
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["work_budget_policy"]["budget_scope"] == "per_discipline_assignment"
    assert reply["work_budget_policy"]["discipline_assignment_count"] == 2
    assert reply["result"]["discipline_results"] == []
    assert reply["result"]["discipline_comparison"] == []
    assert reply["result"]["selected_solution"]["loadouts"]["single"]["discipline"] == "melee"
    assert reply["baseline"]["status"] == "unavailable"


def test_multi_auto_policy_counts_all_roles_and_fingerprints():
    from tracker.api.gear_optimizations import (
        BrowserOptimizationRequest,
        scenario_fingerprint,
        work_budget_policy,
    )

    roles = [{**auto_role(), "id": f"r{i}"} for i in range(4)]
    request = BrowserOptimizationRequest(expected_snapshot_id="frozen", roles=roles)
    policy = work_budget_policy(request)
    assert policy.budget_scope == "per_discipline_assignment"
    assert policy.discipline_assignment_count == 81
    changed = request.model_copy(
        update={
            "roles": (
                *request.roles[:3],
                request.roles[3].model_copy(update={"allowed_disciplines": ("melee",)}),
            )
        }
    )
    assert work_budget_policy(changed).discipline_assignment_count == 27
    assert scenario_fingerprint(request) != scenario_fingerprint(changed)


def test_multi_auto_rejects_utility_auto(client, session_factory):
    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "roles": [
                {"id": "parent", "style": "slash"},
                {
                    **auto_role(),
                    "style": "special",
                    "parent_role": "parent",
                    "locks": {"weapon": 4151},
                },
            ],
        },
    )
    assert response.status_code == 422


def test_auto_policy_and_fingerprint():
    from tracker.api.gear_optimizations import (
        BrowserOptimizationRequest,
        scenario_fingerprint,
        work_budget_policy,
    )

    common = {"expected_snapshot_id": "frozen", "optimization_mode": "thorough"}
    one = BrowserOptimizationRequest(**common, roles=[auto_role(["melee"])])
    three = BrowserOptimizationRequest(**common, roles=[auto_role()])
    assert work_budget_policy(one).complete_assignment_limit == 10000
    assert work_budget_policy(three).complete_assignment_limit == 10000
    assert work_budget_policy(three).budget_scope == "per_discipline"
    assert work_budget_policy(three).discipline_count == 3
    assert scenario_fingerprint(one) != scenario_fingerprint(three)


def test_auto_ignores_stale_manual_settings():
    from tracker.api.gear_optimizations import BrowserOptimizationRequest

    role = {**auto_role(), "style": "magic", "spell": "unused", "stance": "rapid"}
    assert BrowserOptimizationRequest(expected_snapshot_id="frozen", roles=[role])


def test_auto_empty_options_report_no_result(client, session_factory):
    role = {
        **auto_role(["melee"]),
        "combat_options": {"attack_types": [], "stances": [], "spells": []},
    }
    response = client.post(
        "/ui-api/gear/optimizations",
        json={
            **scenario(client, session_factory),
            "roles": [role],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["selected_solution"] is None
    assert body["baseline"]["status"] == "unavailable"
    assert body["baseline"]["reasons"]
    assert body["result"]["discipline_comparison"][0]["status"] == "no_feasible_solution_found"
