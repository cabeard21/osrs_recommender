"""Private, single-owner MCP listener settings. No sync or OAuth credentials."""

from __future__ import annotations

import ipaddress
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "fc00::/7",
    )
)


class MCPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    player_id: int | None = Field(default=None, gt=0)
    bind_address: str = "127.0.0.1"
    allow_all_interfaces: bool = False
    allowed_hostnames: list[str] = Field(default_factory=list)
    port: int = Field(default=8503, gt=0, lt=65536)

    @field_validator("player_id", mode="before")
    @classmethod
    def reject_boolean_id(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("player_id must be an integer identifier")
        return value

    @field_validator("bind_address")
    @classmethod
    def private_address(cls, value: str) -> str:
        address = ipaddress.ip_address(value)
        if (
            not address.is_unspecified
            and not address.is_loopback
            and not any(address in network for network in _PRIVATE_NETWORKS)
        ):
            raise ValueError("MCP must bind to a loopback, RFC1918, ULA, or Tailscale IP address")
        return str(address)

    @field_validator("allowed_hostnames")
    @classmethod
    def exact_hostnames(cls, values: list[str]) -> list[str]:
        label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        for value in values:
            if len(value) > 253 or not re.fullmatch(rf"{label}(?:\.{label})*", value):
                raise ValueError("allowed_hostnames must contain exact DNS names without ports")
        return [value.lower() for value in values]

    @model_validator(mode="after")
    def selected_account(self) -> MCPSettings:
        if ipaddress.ip_address(self.bind_address).is_unspecified and not self.allow_all_interfaces:
            raise ValueError("Wildcard MCP binding requires mcp.allow_all_interfaces=true")
        if self.enabled and self.player_id is None:
            raise ValueError("Enabled MCP requires the existing OSRS player_id")
        return self
