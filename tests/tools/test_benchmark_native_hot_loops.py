import json
import shutil
from pathlib import Path

import pytest
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


@pytest.mark.skipif(
    not shutil.which("node") or not Path("frontend/gear/node_modules/vite").is_dir(),
    reason="Browser draft capture uses installed Gear frontend dependencies",
)
def test_draft_capture_uses_browser_options_and_starting_snapshot():
    from tools.benchmark_native_hot_loops import draft_request

    draft = {
        "roles": [
            {
                "id": "lead",
                "name": "Lead",
                "style": "melee",
                "attackType": "slash",
                "stance": "accurate",
                "weight": "1",
                "locks": {},
                "autoDiscipline": True,
                "allowedDisciplines": ["melee", "magic"],
            }
        ],
        "baseRole": "lead",
        "target": "Dummy",
        "defence": "1",
        "budget": "1m",
        "mode": "usable",
        "supplies": "12",
        "maxActions": "8",
        "topology": "base",
        "assumptions": {"attack": "", "quest": False, "acquired": ""},
        "exclusions": [],
        "objectives": [{"kind": "prayer_bonus"}],
    }
    capabilities = {
        "attack_types": [
            {"id": "slash", "category": "melee", "available": True},
            {"id": "magic", "category": "magic", "available": True},
        ],
        "stances": [{"id": "accurate", "category": "magic", "available": True}],
        "spells": [
            {"id": "fire_strike", "available": True},
            {"id": "ice_barrage", "available": False},
        ],
    }
    scenario = draft_request(
        draft,
        {
            "snapshotId": "frozen",
            "live": {"capabilities": {"combat_options": capabilities}, "account": {"skills": {}}},
        },
    )
    assert scenario["expected_snapshot_id"] == "frozen"
    assert scenario["budget_gp"] == 1_000_000
    assert scenario["roles"][0]["combat_options"]["spells"] == ["fire_strike"]


def test_failed_attempt_replay_prefers_submitted_options_over_prior_result_and_edited_draft():
    from tools.benchmark_native_hot_loops import attempt_request

    previous = {"live": {"scenario": {"budget_gp": 1}}}
    captured = {"budget_gp": 42, "expected_snapshot_id": "old", "roles": [{"spells": ["a"]}]}
    data = {
        "result": previous,
        "draft": {"budget": "100m"},
        "attempt": {"status": "failed", "request": captured},
    }
    request, original = attempt_request(data, "new")
    assert request == {**captured, "expected_snapshot_id": "new"}
    assert original == "old" and captured["expected_snapshot_id"] == "old"
    assert (
        attempt_request({**data, "attempt": {"status": "succeeded", "request": captured}}, "new")
        is None
    )


def test_joint_acceptance_uses_service_latency_parity_and_both_native_kernels():
    common = {
        "inputs_sha256": "same",
        "workers": 6,
        "published": {},
        "full_archive": {"groups": {}},
        "native": {
            "fallback_requests": 0,
            "native_requests": 40,
            "events": [
                {"event": "completed_candidate_admission", "screened": 9},
                {"event": "transition_solver", "solves": 3},
            ],
        },
        "memory": None,
    }
    reference = {**common, "seconds": {"optimizer": 100, "service": 120, "merge": 1}}
    candidate = {**common, "seconds": {"optimizer": 60, "service": 60, "merge": 1}}
    raw = {"inputs_sha256": "same", "raw": {}}
    kwargs = {"raw_reference": raw, "raw_candidate": raw, "joint": True}
    qualified = compare_observations([reference] * 3, [candidate] * 3, **kwargs)
    assert qualified["qualified"]
    assert qualified["native_kernel_counts"][0] == {
        "transition_solves": 3,
        "priced_screened": 9,
        "unpriced_screened": 0,
    }
    unpriced = {
        **candidate,
        "native": {
            **common["native"],
            "events": [
                {"event": "completed_candidate_admission", "unpriced_screened": 17},
                {"event": "transition_solver", "solves": 3},
            ],
        },
    }
    report = compare_observations([reference] * 3, [unpriced] * 3, **kwargs)
    assert report["qualified"]
    assert report["native_kernel_counts"][0]["priced_screened"] == 0
    assert report["native_kernel_counts"][0]["unpriced_screened"] == 17
    missing = {**candidate, "native": {**common["native"], "events": []}}
    assert not compare_observations([reference] * 3, [missing] * 3, **kwargs)["qualified"]
    assert not compare_observations(
        [reference] * 3, [{**candidate, "full_archive": {}}] * 3, **kwargs
    )["qualified"]
    assert not compare_observations(
        [reference] * 3, [{**candidate, "seconds": {"service": 61}}] * 3, **kwargs
    )["qualified"]


def test_joint_lane_observations_keep_discipline_assignment_and_potion_pair():
    from tools.benchmark_joint_gear import lane_observations

    inner = {"timings_seconds": {"gear_search": 5}, "objective_frontier": {"option_attempts": 17}}
    profiles = [
        {"discipline": None, "selected_ids": ids, "search": inner} for ids in ([], ["p"], [])
    ]
    search = {
        "potion_selection": {"profiles": profiles},
        "discipline_assignment_selection": {
            "branches": {
                "a=melee/b=magic": {"potion_selection": {"branch_count": 2}},
                "a=ranged/b=magic": {"potion_selection": {"branch_count": 1}},
            }
        },
    }
    rows = lane_observations(search, ["a=melee/b=magic", "a=ranged/b=magic"])
    assert [(r["lane"], r["assignment"], r["selected_ids"]) for r in rows] == [
        (0, "a=melee/b=magic", []),
        (1, "a=melee/b=magic", ["p"]),
        (2, "a=ranged/b=magic", []),
    ]
    assert (
        rows[0]["seconds"] == {"gear_search": 5}
        and rows[0]["objective_frontier"]["option_attempts"] == 17
    )


def test_joint_api_benchmark_captures_timed_response_and_orders_raw_archive_after_publication(
    tmp_path,
):
    from dataclasses import replace

    from tools.benchmark_joint_gear import observe
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.optimizer import SLOTS
    from tracker.gear.service import GearService

    case = load_case("melee_1m")
    case = replace(
        case,
        request=case.request.model_copy(
            update={
                "expected_snapshot_id": case.snapshot.fingerprint,
                "objectives": (),
                "max_swaps": 0,
                "locks": dict.fromkeys(SLOTS),
            }
        ),
    )
    service = GearService(case.content)
    service._equipment = case.catalog
    try:
        observe(
            case,
            {"optimization_mode": "fast", "inputs_sha256": "input"},
            service,
            "build",
            1,
            tmp_path / "result.json",
            tmp_path / "raw.json",
        )
        measured = json.loads((tmp_path / "result.json").read_bytes())
        raw = json.loads((tmp_path / "raw.json").read_bytes())
        assert measured["seconds"]["service"] >= measured["seconds"]["optimizer"]
        assert measured["full_archive"]["groups"] and raw["raw"]["global"]
        assert raw["inputs_sha256"] == measured["inputs_sha256"]
    finally:
        service.close_objective_store()


@pytest.mark.parametrize("status", [None, "failed", "running"])
def test_freeze_then_reload_uses_latest_attempt_or_browser_draft(tmp_path, monkeypatch, status):
    from types import SimpleNamespace

    from tools import benchmark_native_hot_loops as benchmark
    from tools.benchmark_gear_desktop import load_frozen_case
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.data_source import RemoteGearDataSource
    from tracker.gear.service import GearService

    case = load_case("melee_1m")
    settings = SimpleNamespace(
        pi_url="http://localhost",
        player_id=1,
        content_dir=Path("content"),
        read_token=SimpleNamespace(get_secret_value=lambda: "unused"),
    )
    monkeypatch.setattr("tracker.gear_desktop.DesktopSettings", lambda: settings)
    monkeypatch.setattr("tracker.content.loader.load_content", lambda _: case.content)
    monkeypatch.setattr(GearService, "equipment_catalog", lambda _: case.catalog)
    monkeypatch.setattr(RemoteGearDataSource, "load", lambda _: (case.snapshot, case.prices))
    submitted = case.request.model_dump(mode="json")
    submitted["roles"][0]["combat_options"] = {
        "attack_types": ["slash"],
        "stances": ["accurate"],
        "spells": ["fire_strike"],
    }
    submitted["expected_snapshot_id"] = "original"
    submitted["optimization_mode"] = "thorough"
    if status:
        handoff = {
            "result": {"live": {"scenario": {"budget_gp": 1}}},
            "attempt": {"status": status, "request": submitted},
            "draft": {"budget": "edited"},
        }
        monkeypatch.setattr(
            benchmark, "draft_request", lambda *_: pytest.fail("Rebuilt submitted request")
        )
    else:
        handoff = {"result": None, "draft": {"budget": "1m"}}

        def browser_normalization(draft, context):
            assert draft == handoff["draft"]
            assert context["live"]["capabilities"]["combat_options"]["stances"]
            return {**submitted, "expected_snapshot_id": context["snapshotId"]}

        monkeypatch.setattr(benchmark, "draft_request", browser_normalization)
    source, frozen = tmp_path / "handoff.json", tmp_path / "frozen.json"
    source.write_text(json.dumps(handoff))
    benchmark.freeze(source, frozen)
    replay, provenance = load_frozen_case(frozen)
    assert replay.request.roles[0].combat_options.attack_types == ("slash",)
    assert replay.request.roles[0].combat_options.spells == ("fire_strike",)
    assert (
        replay.request.expected_snapshot_id
        == replay.snapshot.fingerprint
        == case.snapshot.fingerprint
    )
    assert (
        replay.request.budget_gp == case.request.budget_gp
        and provenance["optimization_mode"] == "thorough"
    )
    assert provenance["account_input"] == ("fresh_for_attempt" if status else "fresh_for_draft")
    assert provenance.get("original_snapshot_id") == ("original" if status else None)
    assert provenance["price_input"] == "fresh"


def test_joint_benchmark_cli_reuses_pool_and_captures_raw_once(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import Mock

    from tools import benchmark_joint_gear as runner

    service = Mock()

    @contextmanager
    def desktop(case, workers):
        assert case == "case" and workers == 6
        yield service, {"verified": True}

    monkeypatch.setattr(runner, "desktop_service", desktop)
    monkeypatch.setattr(runner, "load_frozen_case", lambda _: ("case", {}))
    measured = Mock()
    monkeypatch.setattr(runner, "observe", measured)
    monkeypatch.setattr(
        "sys.argv", ["bench", "case.json", str(tmp_path), "--observations", "2", "--save-raw"]
    )
    runner.main()
    assert [(call.args[-2], call.args[-1]) for call in measured.call_args_list] == [
        (tmp_path / "0.json", tmp_path / "raw.json"),
        (tmp_path / "1.json", None),
    ]
    service.close_objective_store.assert_called_once()
    (tmp_path / "raw.json").touch()
    with pytest.raises(SystemExit):
        runner.main()
