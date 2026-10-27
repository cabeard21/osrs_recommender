"""Reproducible public synthetic inputs for joint-search timing."""

import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tools import benchmark_gear_joint
from tools.benchmark_gear_joint import create_database, joint_request, summarize
from tracker.accounts.service import AccountService
from tracker.content.loader import Content
from tracker.db.gear_prices import DatabaseGearPrices
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def test_joint_scenarios_cover_repeated_disciplines_and_role_targets():
    request = OptimizationRequest.model_validate(joint_request(4, 4))
    assert len(request.roles) == 4
    assert request.roles[0].style == request.roles[3].style == "slash"
    assert request.roles[0].target != request.roles[3].target
    assert request.max_swaps == 4
    assert request.reserved_supply_slots == 12
    with pytest.raises(ValueError):
        joint_request(5, 4)


def test_synthetic_database_has_frozen_observations_and_cached_prices(tmp_path):
    catalog = SimpleNamespace(
        items={
            1333: EquipmentDefinition(id=1333, name="Rune", slot="weapon", tradeable=True),
            6585: EquipmentDefinition(id=6585, name="Fury", slot="neck", tradeable=True),
        }
    )
    database = tmp_path / "joint.sqlite"
    create_database(database, Content(), catalog, NOW)
    engine = create_engine(f"sqlite:///{database}")
    sessions = sessionmaker(bind=engine)
    snapshot = AccountService(sessions).get_snapshot(1)
    assert snapshot.username == "synthetic-joint-benchmark"
    assert snapshot.skills["magic"].level == 99
    assert snapshot.last_sync_at == NOW
    assert {fact.item_id for fact in snapshot.observed_items.values()} == {1333}
    prices = DatabaseGearPrices(sessions).get_prices()
    assert prices[6585].high_trade_at == NOW
    assert prices[6585].provider == "synthetic-benchmark"
    engine.dispose()
    with pytest.raises(FileExistsError):
        create_database(database, Content(), catalog, NOW)


def test_summary_keeps_optimizer_time_separate_and_diagnostics_exact():
    request = joint_request(2, 8)
    report = {
        "median_seconds": {"optimization_total": 3.5, "nicegui_result_construction": 0.4},
        "runs": [
            {"seconds": {"optimization_total": 3.0}},
            {"seconds": {"optimization_total": 4.0}},
        ],
        "response": {
            "catalog_summary": {"total_items": 5435, "eligible_items": 100},
            "search": {"candidate_truncation": True, "termination_reason": "node_limit"},
            "selected_solution": {"score": 2.1, "maximum_actions": 5},
        },
    }
    result = summarize(request, report)
    assert result["role_count"] == 2
    assert result["optimizer_median_seconds"] == 3.5
    assert result["optimizer_seconds"] == [3.0, 4.0]
    assert result["catalog"] == report["response"]["catalog_summary"]
    assert result["search"] == report["response"]["search"]
    assert result["maximum_actions"] == 5


def test_cli_records_each_requested_case_and_environment(tmp_path, monkeypatch):
    catalog = SimpleNamespace(items={}, revision="synthetic-test")
    monkeypatch.setattr(benchmark_gear_joint, "load_content", Content)
    monkeypatch.setattr(
        benchmark_gear_joint,
        "GearService",
        lambda _: SimpleNamespace(equipment_catalog=lambda: catalog),
    )
    requests = []

    def measured(database, request_path, at, repeats):
        assert database.is_file()
        assert at == benchmark_gear_joint.FROZEN_AT
        assert repeats == 1
        requests.append(json.loads(request_path.read_text()))
        return {
            "runs": [{"seconds": {"optimization_total": 1.0}}],
            "median_seconds": {"optimization_total": 1.0},
            "response": {"selected_solution": None, "catalog_summary": {}, "search": {}},
        }

    monkeypatch.setattr(benchmark_gear_joint, "benchmark", measured)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--directory",
            str(tmp_path),
            "--roles",
            "2",
            "4",
            "--actions",
            "0",
            "8",
            "--repeats",
            "1",
        ],
    )
    benchmark_gear_joint.main()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert len(summary["cases"]) == len(requests) == 4
    assert summary["environment"]["python"]
    assert summary["catalog_version"] == "synthetic-test"
    assert summary["cases"][0]["selected_score"] is None
    assert summary["cases"][0]["maximum_actions"] is None
    assert len(list(tmp_path.glob("*-report.json"))) == 4


def test_cli_rejects_invalid_repeat_count_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark", "--directory", str(tmp_path), "--repeats", "0"])
    with pytest.raises(SystemExit):
        benchmark_gear_joint.main()
    assert not list(tmp_path.iterdir())
