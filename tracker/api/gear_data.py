"""Read-only Pi transport with a credential independent of RuneLite writes."""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from tracker.api.deps import get_session_factory, get_settings
from tracker.gear.data_source import LocalGearDataSource, SnapshotEnvelope


def require_read_token(request: Request) -> None:
    token = get_settings(request).gear_data_token
    if token is None:
        raise HTTPException(404, "Gear data endpoint disabled")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {token.get_secret_value()}"
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Invalid Gear read credential")


router = APIRouter(prefix="/api/gear-data/v1", dependencies=[Depends(require_read_token)])


@router.get("/players/{player_id}/snapshot", response_model=SnapshotEnvelope)
def snapshot(player_id: int, request: Request, response: Response) -> SnapshotEnvelope:
    response.headers["Cache-Control"] = "no-store"
    if player_id < 1:
        raise HTTPException(422, "Invalid player ID")
    try:
        account, prices = LocalGearDataSource(get_session_factory(request), player_id).load()
    except LookupError as exc:
        raise HTTPException(404, "Player not found") from exc
    if account is None:
        raise HTTPException(404, "Player not found")
    return SnapshotEnvelope.from_facts(account, prices)
