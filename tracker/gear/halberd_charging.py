"""Reviewed crystal halberd replenishment; current remaining charges stay unknown.

Source: https://oldschool.runescape.wiki/w/Crystal_halberd
One charge per attack, 2,500 charges per coin recharge; 100 per crystal shard.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CrystalChargingPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Literal["auto", "coins", "shards"] = "auto"
    coin_recharge_cost_gp: Literal[750000, 600000, 450000, 300000, 150000] = 750000
    shard_value_gp: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)


def charge_cost(policy: CrystalChargingPolicy) -> float | None:
    routes = []
    if policy.method != "shards":
        routes.append(policy.coin_recharge_cost_gp / 2500)
    if policy.method != "coins" and policy.shard_value_gp is not None:
        routes.append(policy.shard_value_gp / 100)
    return min(routes) if routes else None


def cost_context(request: object, role_or_id: object) -> dict[str, Any]:
    """Cost settings use the same role window as outgoing status damage."""
    roles = getattr(request, "roles", ())
    role = next((r for r in roles if r.id == role_or_id), role_or_id)
    return {
        "fight_duration_seconds": getattr(role, "fight_duration_seconds", 60),
        "crystal_halberd_charging": getattr(request, "crystal_halberd_charging", None),
    }
