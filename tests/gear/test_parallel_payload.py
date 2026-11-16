"""Worker transport retains immutable account, catalog and price semantics."""

import pickle
from dataclasses import replace

import pytest

from tests.gear.test_auto_disciplines import context
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.parallel_payload import context_payload, decode_context, decode_job, job_payload


def inputs():
    snapshot, request, catalog, content, prices, now = context()
    verified = EquipmentCatalog(catalog.items, revision="verified")
    catalog = EquipmentCatalog(
        catalog.items,
        revision="community",
        community_items={1: {"reason": "reviewed"}},
        community_provenance="pinned",
        community_assumptions={1: ("ordinary attack",)},
        verified_catalog=verified,
    )
    return snapshot, request, catalog, content, prices, now


def test_typed_shared_objectives_round_trip_worker_payload_without_closures():
    from tracker.gear.optimizer import OptimizationRequest

    snapshot, request, _, _, prices, now = inputs()
    configured = OptimizationRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "objectives": [
                {"kind": "defence_roll", "styles": ["magic", "stab"], "aggregation": "mean"},
                {"kind": "prayer_bonus"},
            ],
        }
    )
    payload = pickle.loads(pickle.dumps(job_payload(snapshot, configured, prices, now, "context")))
    _, restored, _, _ = decode_job(payload, "context")
    assert restored.objectives == configured.objectives
    assert all(not callable(value) for value in payload["request"].values())


def test_context_and_job_round_trip_pickle_preserves_all_revisions():
    snapshot, request, catalog, content, prices, now = inputs()
    packed, identity = context_payload(content, catalog)
    restored_content, restored_catalog = decode_context(
        pickle.loads(pickle.dumps(packed)), identity
    )
    assert restored_content == content
    assert restored_catalog == catalog
    job = job_payload(snapshot, request, prices, now, identity)
    restored, configured, quotes, at = decode_job(pickle.loads(pickle.dumps(job)), identity)
    assert restored.fingerprint == snapshot.fingerprint
    assert configured == request
    assert quotes == prices
    assert at == now


def test_context_detects_same_revision_with_changed_equipment():
    _, _, catalog, content, _, _ = inputs()
    payload, identity = context_payload(content, catalog)
    modified = replace(catalog, community_provenance="changed")
    assert context_payload(content, modified)[1] != identity
    payload["catalog"]["community_provenance"] = "tampered"
    with pytest.raises(ValueError, match="context"):
        decode_context(payload, identity)


def test_job_rejects_wrong_context_or_account_fingerprint():
    snapshot, request, _, _, prices, now = inputs()
    job = job_payload(snapshot, request, prices, now, "expected")
    with pytest.raises(ValueError, match="context"):
        decode_job(job, "different")
    job["snapshot_id"] = "stale"
    with pytest.raises(ValueError, match="fingerprint"):
        decode_job(job, "expected")


def test_browser_envelope_fields_do_not_leak_into_worker_request():
    from tracker.api.gear_optimizations import BrowserOptimizationRequest

    snapshot, request, _, _, prices, now = inputs()
    browser = BrowserOptimizationRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "expected_snapshot_id": snapshot.fingerprint,
            "optimization_mode": "thorough",
        }
    )
    payload = job_payload(snapshot, browser, prices, now, "context")
    _, restored, _, _ = decode_job(payload, "context")
    assert "optimization_mode" not in restored.model_dump()


def test_full_authored_content_and_catalog_round_trip():
    from tracker.content.loader import load_content
    from tracker.gear.catalog import load_catalog

    content = load_content()
    catalog = load_catalog(content)
    payload, identity = context_payload(content, catalog)
    restored_content, restored_catalog = decode_context(payload, identity)
    assert restored_content == content
    assert restored_catalog == catalog


def test_price_facts_round_trip_and_reject_mismatched_keys():
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    snapshot, request, _, _, _, now = inputs()
    record = PriceDTO(1, 100, now, 90, now, "fixture", now, PriceSource.LIVE)
    payload = job_payload(snapshot, request, {1: record}, now, "context")
    _, _, quotes, _ = decode_job(pickle.loads(pickle.dumps(payload)), "context")
    for name in (
        "item_id",
        "high_price_gp",
        "high_trade_at",
        "low_price_gp",
        "low_trade_at",
        "fetched_at",
        "source",
        "provider",
    ):
        assert getattr(quotes[1], name) == getattr(record, name)
    payload["prices"][1]["item_id"] = 2
    with pytest.raises(ValueError, match="price_mismatch"):
        decode_job(payload, "context")
