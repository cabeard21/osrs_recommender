import json

from pydantic import TypeAdapter

from tests.gear.test_objective_orchestration import branch, solution
from tests.gear.test_objective_store import result
from tools.benchmark_native_hot_loops import (
    capture_merge,
    compare_observations,
    complete_digest,
    frontier_digest,
    historical_prices,
    price_revision,
    replay_merge,
)
from tracker.db.gear_prices import CachedPriceRecord
from tracker.gear.objective_store import ObjectiveRunStore
from tracker.gear.optimizer import OptimizationRequest
from tracker.gear.potion_search import merge_objective_frontiers


def test_complete_digest_covers_unsampled_members_and_ignores_run_uuid():
    with ObjectiveRunStore() as store:
        original = result()
        first = store.publish_result(original, metadata={}, player_id=1)
        second = store.publish_result(original, metadata={}, player_id=1)
        complete = complete_digest(store, first["run_id"])
        assert complete == complete_digest(store, second["run_id"])
        group_id = first["objective_frontiers"][0]["id"]
        assert complete["groups"][group_id]["count"] == 150

        sample = {row["solution"]["score"] for row in first["objective_frontiers"][0]["points"]}
        points = original["objective_frontiers"][0]["points"]
        hidden = next(row for row in points if row["solution"]["score"] not in sample)
        hidden["solution"]["purchase_cost_gp"] += 100
        changed = store.publish_result(original, metadata={}, player_id=1)
        assert complete != complete_digest(store, changed["run_id"])


def test_ordered_digest_checks_point_ids_and_ignores_observational_timings():
    payload = result(2)
    payload["search"] = {"explored_nodes": 3, "timings_seconds": {"total": 1}}
    original = frontier_digest(payload)
    payload["search"]["timings_seconds"] = {"total": 2}
    assert original == frontier_digest(payload)
    payload["objective_frontiers"][0]["points"].reverse()
    assert original != frontier_digest(payload)


def test_compare_requires_matching_inputs_and_full_parity():
    common = {
        "inputs_sha256": "same",
        "workers": 6,
        "memory": None,
        "published": {},
        "full_archive": {"groups": "ordered"},
        "native": {"fallback_requests": 0},
    }
    reference = {**common, "seconds": {"optimizer": 100, "service": 120, "merge": 50}}
    candidate = {**common, "seconds": {"optimizer": 40, "service": 45, "merge": 8}}
    raw = {"inputs_sha256": "same", "raw": {"points": "exact"}}
    strict = {"raw_reference": raw, "raw_candidate": raw}
    assert compare_observations([reference] * 3, [candidate] * 3, **strict)["qualified"]
    assert not compare_observations([reference], [candidate], **strict)["qualified"]
    assert not compare_observations([reference] * 3, [candidate] * 3)["qualified"]
    changed = {**candidate, "full_archive": {}}
    assert not compare_observations([reference] * 3, [changed] * 3, **strict)["qualified"]


def test_historical_price_recovery_requires_full_browser_revision():
    reported = {
        "high_price_gp": "7",
        "low_price_gp": "None",
        "fetched_at": "2026-11-19 11:32:00+00:00",
        "high_trade_at": "2026-11-19 11:15:00+00:00",
        "low_trade_at": "None",
        "source": "cached",
    }
    adapter = TypeAdapter(CachedPriceRecord)
    expected = adapter.validate_json(
        json.dumps(
            {
                **reported,
                "item_id": 42,
                "provider": "osrs_wiki",
                "low_price_gp": None,
                "low_trade_at": None,
            }
        )
    )
    current = {42: expected}
    assert historical_prices({"42": reported}, current, price_revision(current)) == current
    assert historical_prices({"42": reported}, {}, price_revision(current)) is None


def test_complete_merge_fixture_round_trips_source_rows(tmp_path):
    request = OptimizationRequest.model_validate(
        {
            "roles": [
                {
                    "id": "a",
                    "style": "slash",
                    "allowed_disciplines": ["melee", "magic"],
                    "combat_options": {
                        "attack_types": ["slash", "magic"],
                        "stances": ["accurate"],
                        "spells": ["fire_strike"],
                    },
                }
            ],
            "max_swaps": 1,
            "max_dps_loss_pct": 100,
            "objectives": [{"kind": "prayer_bonus"}, {"kind": "magic_damage_bonus"}],
        }
    )
    melee = solution(request, 1, 10, (2, 1))
    magic = solution(request, 2, 12, (1, 1))
    sources = [branch(row, row, [row]) for row in (melee, magic)]
    views = ("melee", "magic")
    result = {
        **merge_objective_frontiers(request, sources),
        "discipline_results": [
            {"discipline": view, **merge_objective_frontiers(request, [source])}
            for view, source in zip(views, sources, strict=True)
        ],
    }
    counts = {
        view: {"objective_frontier": {"archive_counts": {"0": 1, "1": 1, "None": 1}}}
        for view in views
    }
    frozen, output = tmp_path / "merge.json.gz", tmp_path / "result.json"
    with ObjectiveRunStore() as store:
        published = store.publish_result(result, metadata={}, player_id=1)
        capture_merge(
            store.directory / "results.sqlite",
            published["run_id"],
            request.model_dump(mode="json"),
            counts,
            frozen,
        )
    replay_merge(frozen, output, native=False)
    assert json.loads(output.read_bytes())["parity"] is True
