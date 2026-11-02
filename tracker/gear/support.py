"""Request-local ordinary-equipment assumptions; verified metadata stays immutable."""

from __future__ import annotations

from typing import Any, Literal

from tracker.gear.catalog import EquipmentCatalog

SupportPolicy = Literal["verified_only", "community_best_effort"]
GENERIC_UNREVIEWED = "Offensive effects have not been validated."
COMMUNITY_ASSUMPTIONS = (
    "Community ordinary-equipment classification; not individually verified.",
    "Known wear requirements apply; unresolved quest/unlock gates are assumed absent.",
    "Ordinary attacks only; conditional mechanics are excluded by the community policy.",
)


def project_catalog(catalog: Any, policy: SupportPolicy) -> Any:
    """Clear only the generic marker for positively classified exact physical IDs."""
    catalog = getattr(catalog, "verified_catalog", None) or catalog
    if policy == "verified_only":
        return catalog
    if policy != "community_best_effort":
        raise ValueError("invalid equipment support policy")
    items = dict(catalog.items)
    assumptions = {}
    for item_id, evidence in getattr(catalog, "community_items", {}).items():
        item = items.get(item_id)
        if (
            item is None
            or not isinstance(evidence, dict)
            or evidence.get("classification") != "ordinary"
            or type(evidence.get("tradeable")) is not bool
            or (
                item.requires is None
                and not (
                    evidence.get("requirements_assumed_absent") is True
                    and evidence.get("tradeable") is True
                )
            )
            or (item.content_ids and not item.requirements_complete)
            or any(effect != GENERIC_UNREVIEWED for effect in item.unsupported_effects)
            or (item.requirements_complete and not item.unsupported_effects)
        ):
            continue
        assumptions[item_id] = COMMUNITY_ASSUMPTIONS + (
            ("No equip requirement data; tradeable item is assumed ungated.",)
            if item.requires is None
            else ()
        )
        items[item_id] = item.model_copy(
            update={
                "unsupported_effects": (),
                "tradeable": item.tradeable
                if item.tradeable is not None
                else evidence.get("tradeable"),
            }
        )
    return EquipmentCatalog(
        items,
        getattr(catalog, "revision", "unknown"),
        community_items=getattr(catalog, "community_items", {}),
        community_provenance=getattr(catalog, "community_provenance", ""),
        community_assumptions=assumptions,
        verified_catalog=catalog,
    )


def support_context(catalog: Any, policy: SupportPolicy) -> dict[str, str]:
    """Policy and exact sidecar bytes are part of result assumption identity."""
    return {
        "support_policy": policy,
        "support_provenance": getattr(catalog, "community_provenance", "")
        if policy == "community_best_effort"
        else "",
    }
