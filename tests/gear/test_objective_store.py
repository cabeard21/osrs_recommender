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


def test_restore_metadata_update_preserves_manifest_identity():
    with ObjectiveRunStore() as store:
        published = store.publish_result(result(2), metadata={}, player_id=1)
        store.update_metadata(
            published["run_id"], player_id=1, metadata={"response": {"frozen": True}}
        )
        manifest = store.metadata(published["run_id"], player_id=1)
        assert manifest["response"] == {"frozen": True}
        assert manifest["groups"]


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
