from datetime import UTC, datetime

import httpx
import pytest
from fastapi import HTTPException

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.domain.types import Container
from tracker.gear.data_source import RemoteGearDataSource, SnapshotEnvelope


def test_roundtrip_and_fingerprint():
    now = datetime.now(UTC)
    snapshot = AccountSnapshot(
        1,
        "test",
        observed_items={
            (4151, Container.BANK): ObservedItemFact(4151, Container.BANK, 1, "runelite", now)
        },
        container_scans={Container.BANK: ContainerScanFact(Container.BANK, now, "runelite")},
    )
    wire = SnapshotEnvelope.from_facts(snapshot, {})
    restored, prices = SnapshotEnvelope.model_validate_json(wire.model_dump_json()).facts()
    assert restored.fingerprint == snapshot.fingerprint
    assert restored.members is None
    assert restored.observed_items[(4151, Container.BANK)].quantity == 1
    assert prices == {}
    with pytest.raises(ValueError, match="fingerprint"):
        wire.model_copy(update={"snapshot_id": "wrong"}).facts()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "http://user:secret@pi",
        "http://pi?a=b",
        "file:///db",
        "http://pi/path",
    ],
)
def test_remote_rejects_nonprivate_or_credentialed_origin(url):
    with pytest.raises(ValueError):
        RemoteGearDataSource(url, 1, "secret")


def test_remote_revalidates_every_load_and_sanitizes_errors(monkeypatch):
    wire = SnapshotEnvelope.from_facts(AccountSnapshot(1, "test"), {})
    calls = []
    real_client = httpx.Client

    def handle(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json=wire.model_dump(mode="json"))

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    source = RemoteGearDataSource("http://pi:8502", 1, "secret")
    assert source.load()[0].username == "test"
    assert source.load()[0].username == "test"
    assert len(calls) == 2
    wire = wire.model_copy(update={"snapshot_id": "bad"})
    with pytest.raises(HTTPException) as error:
        source.load()
    assert error.value.status_code == 503
    assert "secret" not in str(error.value.detail)


@pytest.mark.parametrize(
    "failure", ["timeout", "unauthorized", "redirect", "invalid", "version", "player"]
)
def test_remote_failure_modes(monkeypatch, failure):
    real_client = httpx.Client
    wire = SnapshotEnvelope.from_facts(AccountSnapshot(2, "other"), {}).model_dump(mode="json")

    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("failed", request=request)
        if failure == "unauthorized":
            return httpx.Response(401)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "http://other/"})
        if failure == "invalid":
            return httpx.Response(200, content="not JSON")
        if failure == "version":
            return httpx.Response(200, json=wire | {"api_version": "unsupported"})
        return httpx.Response(200, json=wire)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(HTTPException) as error:
        RemoteGearDataSource("http://pi", 1, "secret").load()
    assert error.value.status_code == 503


@pytest.mark.parametrize("token", ["", " ", "CHANGE_ME", "write-token"])
def test_read_token_configuration_rejects_invalid_credentials(token):
    from pydantic import ValidationError

    from tracker.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(bind_address="127.0.0.1", api_token="write-token", gear_data_token=token)
