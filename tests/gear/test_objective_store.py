"""Session results preserve the full archive independently of chart sampling."""

import pytest

from tracker.gear.objective_store import (
    ObjectiveRunStore,
    RunUnavailable,
    close_result_archives,
)


def result(count=150):
    return {
        "objective_definitions": [{"id": "prayer_bonus", "kind": "prayer_bonus"}],
        "selected_solution": {"score": 1, "objective_values": {"prayer_bonus": 0}},
        "objective_frontiers": [
            {
                "swap_limit": 0,
                "baseline_dps": 150,
                "points": [
                    {
                        "id": f"point-{i}",
                        "solution": {
                            "score": count - i,
                            "objective_values": {"prayer_bonus": i},
                            "purchase_cost_gp": i,
                            "maximum_actions": 0,
                            "loadouts": {"a": {"equipment": {"weapon": i + 1}}},
                        },
                    }
                    for i in range(count)
                ],
            }
        ],
    }


def test_publication_samples_only_chart_and_paginates_every_point():
    with ObjectiveRunStore(memory_budget_bytes=1) as store:
        original = result()
        published = store.publish_result(original, metadata={"snapshot_id": "frozen"}, player_id=1)
        group = published["objective_frontiers"][0]
        assert len(group["points"]) == 128
        assert group["total_count"] == 150
        assert len(original["objective_frontiers"][0]["points"]) == 150
        run_id = published["run_id"]
        page = store.page(run_id, group["id"], player_id=1, sort="prayer_bonus", direction="desc")
        assert page["total"] == 150
        assert page["points"][0]["objective_values"]["prayer_bonus"] == 149
        seen = [row["id"] for row in page["points"]]
        while page["next_cursor"]:
            page = store.page(
                run_id,
                group["id"],
                player_id=1,
                sort="prayer_bonus",
                direction="desc",
                cursor=page["next_cursor"],
            )
            seen.extend(row["id"] for row in page["points"])
        assert len(set(seen)) == 150
        detail = store.solution(run_id, seen[0], player_id=1)
        assert detail["solution"]["objective_values"]["prayer_bonus"] == 149
        assert store.metadata(run_id, player_id=1)["snapshot_id"] == "frozen"
        with pytest.raises(RunUnavailable):
            store.metadata(run_id, player_id=2)


def test_cancelled_publication_is_not_visible_and_closing_expires_runs():
    store = ObjectiveRunStore()
    with pytest.raises(ValueError, match="cancelled"):
        store.publish_result(result(), metadata={}, player_id=1, cancelled=lambda: True)
    published = store.publish_result(result(2), metadata={}, player_id=1)
    directory = store.directory
    store.close()
    assert not directory.exists()
    with pytest.raises(RunUnavailable):
        store.metadata(published["run_id"], player_id=1)


def test_cursor_and_sort_validation_and_detached_solution_data():
    with ObjectiveRunStore() as store:
        published = store.publish_result(result(2), metadata={}, player_id=1)
        run_id, group = published["run_id"], published["objective_frontiers"][0]["id"]
        with pytest.raises(ValueError):
            store.page(run_id, group, player_id=1, sort="bad SQL")
        with pytest.raises(ValueError):
            store.page(run_id, group, player_id=1, cursor="broken")
        page = store.page(run_id, group, player_id=1)
        solution_id = page["points"][0]["id"]
        data = store.solution(run_id, solution_id, player_id=1)
        data["solution"]["score"] = 999
        assert store.solution(run_id, solution_id, player_id=1)["solution"]["score"] != 999


def test_frozen_context_is_owner_checked_and_session_scoped():
    with ObjectiveRunStore() as store:
        value = object()
        published = store.publish_result(
            result(2), metadata={}, player_id=1, context={"frozen": value}
        )
        assert store.get_context(published["run_id"], player_id=1)["frozen"] is value
        with pytest.raises(TypeError):
            store.get_context(published["run_id"], player_id=1)["frozen"] = object()
        with pytest.raises(RunUnavailable):
            store.get_context(published["run_id"], player_id=2)


def test_lazy_discipline_groups_are_fully_stored_and_sampled():
    data = result(140)
    child = {**result(140), "discipline": "ranged"}
    child["objective_frontiers"][0]["points"] = iter(child["objective_frontiers"][0]["points"])
    data["discipline_results"] = [child]
    with ObjectiveRunStore() as store:
        published = store.publish_result(data, metadata={}, player_id=1)
        group = published["discipline_results"][0]["objective_frontiers"][0]
        assert group["view"] == "discipline-ranged"
        assert group["sampled"]
        assert len(group["points"]) == 128
        page = store.page(published["run_id"], group["id"], player_id=1)
        assert page["total"] == 140
        values = [
            point["solution"]["objective_values"]["prayer_bonus"] for point in group["points"]
        ]
        assert min(values) == 0
        assert max(values) == 139


def test_session_cleanup_preserves_another_active_store_and_bounds_read_gate():
    with ObjectiveRunStore() as first, ObjectiveRunStore() as second:
        assert first.directory.exists()
        assert second.directory.exists()
        assert all(first.allow_read("reader") for _ in range(120))
        assert not first.allow_read("reader")
        assert first.allow_read("another reader")


def test_shared_archive_reuses_membership_with_distinct_cap_outputs(monkeypatch):
    from tracker.gear.vector_archive import VectorArchive
    from tracker.gear.vector_publish import FrontierPoints

    data = result(3)
    group = data["objective_frontiers"][0]
    archive = VectorArchive(("prayer_bonus",))
    for point in group["points"]:
        archive.add(point["solution"])
    data["objective_frontiers"] = [
        {
            **group,
            "swap_limit": cap,
            "baseline_dps": 3 + cap,
            "points": FrontierPoints(archive, cap),
        }
        for cap in (0, 1)
    ]
    with ObjectiveRunStore() as store:
        original = store._put_solution
        calls = []

        def put(run_id, solution):
            calls.append(solution)
            return original(run_id, solution)

        monkeypatch.setattr(store, "_put_solution", put)
        published = store.publish_result(data, metadata={}, player_id=1)
        first, second = published["objective_frontiers"]
        assert len(calls) == 4  # Three members and the selected solution.
        assert first["total_count"] == second["total_count"] == 3
        assert first["points"][0]["id"] != second["points"][0]["id"]
        assert first["points"][0]["dps_loss"] + 1 == second["points"][0]["dps_loss"]
        assert store.page(published["run_id"], second["id"], player_id=1)["total"] == 3


def test_restore_metadata_update_preserves_manifest_identity():
    with ObjectiveRunStore() as store:
        published = store.publish_result(result(2), metadata={}, player_id=1)
        store.update_metadata(
            published["run_id"], player_id=1, metadata={"response": {"frozen": True}}
        )
        manifest = store.metadata(published["run_id"], player_id=1)
        assert manifest["response"] == {"frozen": True}
        assert manifest["groups"]


def test_every_displayed_configuration_has_a_stored_reference_without_frontier_membership():
    reports = [
        {
            "score": index + 1,
            "objective_values": {"prayer_bonus": index},
            "loadouts": {"a": {"equipment": {"weapon": index + 1}}},
        }
        for index in range(4)
    ]
    data = {
        "selected_solution": reports[0],
        "curve": [{"swap_limit": 0, "solution": reports[1]}, {"swap_limit": 1, "solution": None}],
        "unrestricted": reports[2],
        "objective_frontiers": [],
        "discipline_results": [
            {"discipline": "melee", "selected_solution": reports[3], "objective_frontiers": []},
            {"discipline": "magic", "selected_solution": None, "objective_frontiers": []},
        ],
    }
    with ObjectiveRunStore() as store:
        published = store.publish_result(data, metadata={}, player_id=1)
        run_id = published["run_id"]
        references = published["objective_run"]["solution_references"]
        assert set(references) == {
            "best-found",
            "curve-0",
            "unrestricted",
            "discipline-melee-best-found",
        }
        assert references["best-found"] == published["objective_run"]["selected_solution_id"]
        for alias, report in zip(references, reports, strict=True):
            assert store.solution(run_id, references[alias], player_id=1)["solution"] == report
            with pytest.raises(RunUnavailable):
                store.solution(run_id, references[alias], player_id=2)
        assert store.metadata(run_id, player_id=1)["solution_references"] == references


def test_shared_solutions_have_distinct_cap_and_view_point_ids():
    data = result(2)
    first = data["objective_frontiers"][0]
    data["objective_frontiers"] = [first, {**first, "swap_limit": 1}]
    data["discipline_results"] = [{"discipline": "ranged", **result(2)}]
    with ObjectiveRunStore() as store:
        published = store.publish_result(data, metadata={}, player_id=1)
        run_id = published["run_id"]
        first_point = published["objective_frontiers"][0]["points"][0]
        second_point = published["objective_frontiers"][1]["points"][0]
        discipline_point = published["discipline_results"][0]["objective_frontiers"][0]["points"][0]
        assert len({first_point["id"], second_point["id"], discipline_point["id"]}) == 3
        assert (
            first_point["solution_id"]
            == second_point["solution_id"]
            == discipline_point["solution_id"]
        )
        for point in (first_point, second_point, discipline_point):
            detail = store.solution(run_id, point["id"], player_id=1)
            assert detail["solution"] == point["solution"]
        page = store.page(run_id, published["objective_frontiers"][1]["id"], player_id=1)
        assert page["points"][0]["id"].startswith("frontier-global-1-")
        assert page["points"][0]["solution_id"].startswith("objective-")


def test_abandoned_raw_envelope_releases_disk_archives_idempotently():
    from pathlib import Path

    from tracker.gear.vector_archive import VectorArchive
    from tracker.gear.vector_publish import FrontierPoints

    archive = VectorArchive(("prayer_bonus",))
    archive.add(result(1)["objective_frontiers"][0]["points"][0]["solution"])
    path = Path(archive.path)
    envelope = {"result": {"objective_frontiers": [{"points": FrontierPoints(archive, 0)}]}}
    close_result_archives(envelope)
    assert not path.exists()
    close_result_archives(envelope)


def test_cost_frontier_keeps_unpriced_baseline_out_of_page_but_retrievable():
    baseline = {"score": 12.0, "objective_values": {}, "running_cost": {"gp_per_damage": None}}
    priced = [
        {"score": 10.0, "objective_values": {"gp_per_damage": 2.5}},
        {"score": 8.0, "objective_values": {"gp_per_damage": 0.0}},
    ]
    source = {
        "objective_definitions": [{"id": "gp_per_damage", "direction": "minimize"}],
        "objective_frontiers": [
            {
                "swap_limit": 0,
                "baseline_dps": 12.0,
                "baseline_solution": baseline,
                "points": [{"solution": row} for row in priced],
            }
        ],
    }
    with ObjectiveRunStore() as store:
        result = store.publish_result(source, metadata={}, player_id=1)
        run_id = result["run_id"]
        group = result["objective_frontiers"][0]
        assert group["baseline_solution_id"].startswith(group["id"] + "-objective-")
        page = store.page(run_id, group["id"], player_id=1, sort="gp_per_damage")
        assert [p["objective_values"]["gp_per_damage"] for p in page["points"]] == [0.0, 2.5]
        assert (
            store.solution(run_id, group["baseline_solution_id"], player_id=1)["solution"]
            == baseline
        )
        assert (
            result["objective_run"]["groups"][0]["baseline_solution_id"]
            == group["baseline_solution_id"]
        )


def test_chart_sampling_preserves_extremes_of_all_65_dimensions():
    data = result(131)
    keys = [f"dimension_{index}" for index in range(64)]
    data["objective_definitions"] = [{"id": key} for key in keys]
    for i, row in enumerate(data["objective_frontiers"][0]["points"]):
        solution = row["solution"]
        solution["score"] = {128: 0, 129: 2}.get(i, 1)
        solution["objective_values"] = {
            key: 0 if i == 2 * j else 2 if i == 2 * j + 1 else 1 for j, key in enumerate(keys)
        }
    with ObjectiveRunStore() as store:
        group = store.publish_result(data, metadata={}, player_id=1)["objective_frontiers"][0]
    assert group["total_count"] == 131
    assert {row["solution"]["purchase_cost_gp"] for row in group["points"]} == set(range(130))
