"""Read-only account-aware facts about the authored gear progression corpus.

Ladder order is editorial progression, not measured combat strength. This service
does not choose a setup, infer current equipment slots, or validate joint loadouts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from tracker.accounts.requirements import evaluate_requirement
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.content.schema import Item
from tracker.domain.types import Container, Tri
from tracker.estimation.prices import PriceRecord, resolve_price
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.execution_profile import ExecutionProfile, validate_profile
from tracker.gear.facts import equipment_fact
from tracker.gear.ladders import build_ladders
from tracker.gear.optimizer import OptimizationRequest
from tracker.gear.progress_tracker import RunProgress, TimingModel
from tracker.gear.running_frontier import needs_running_cost_frontier
from tracker.gear.support import SupportPolicy, project_catalog

if TYPE_CHECKING:
    from tracker.gear.parallel import AutoProcessPool

_STYLES = frozenset({"melee", "ranged", "magic"})
_OWNERSHIP = frozenset({"owned", "unowned", "unknown"})
_WEAR = frozenset({status.value for status in Tri})
_ACQUISITION = frozenset({"tradeable", "untradeable", "unknown"})
_LIMITATIONS = (
    "Joint loadout validity is not evaluated, including two-handed/offhand and "
    "ammunition compatibility.",
    "Exact replaced items and combat stat or DPS deltas are unavailable from current "
    "observations and catalog.",
)


def _has_frontiers(request: OptimizationRequest, catalog: Any = None) -> bool:
    """Whether any lane runs the secondary or running-cost frontier stage."""
    return request.secondary_priority != "default" or needs_running_cost_frontier(request, catalog)


def _timing_key(
    request: OptimizationRequest,
    thorough: bool,
    parallel: bool,
    profile: ExecutionProfile = "baseline",
    fixed_reporting: bool = False,
    factored_evaluation: bool = False,
    compact_states: bool = False,
    native_search: bool = False,
) -> tuple[Any, ...]:
    """Request shape whose per-lane stage durations are comparable between runs."""
    return (
        profile,
        fixed_reporting,
        factored_evaluation,
        compact_states,
        native_search,
        thorough,
        parallel,
        request.mode,
        request.secondary_priority,
        request.potions.mode,
        tuple(role.style for role in request.roles),
        tuple(tuple(role.allowed_disciplines or ()) for role in request.roles),
        request.max_swaps,
        request.budget_gp > 0,
    )


class GearService:
    """Pure gear projection over one immutable snapshot and injected price rows."""

    def __init__(
        self,
        content: Content,
        *,
        equipment_root: Path | None = None,
        auto_pool: AutoProcessPool | None = None,
        optimization_profile: ExecutionProfile = "baseline",
        fixed_reporting: bool = False,
        factored_evaluation: bool = False,
        compact_states: bool = False,
        native_search: bool = False,
    ) -> None:
        self.optimization_profile = validate_profile(optimization_profile)
        if not isinstance(fixed_reporting, bool):
            raise ValueError("Invalid fixed reporting option")
        self.fixed_reporting = fixed_reporting and self.optimization_profile == "combined"
        if not isinstance(factored_evaluation, bool):
            raise ValueError("Invalid factored evaluation option")
        self.factored_evaluation = factored_evaluation and self.optimization_profile == "combined"
        if not isinstance(compact_states, bool):
            raise ValueError("Invalid compact states option")
        self.compact_states = compact_states and self.factored_evaluation
        if not isinstance(native_search, bool):
            raise ValueError("Invalid native search option")
        self.native_search = native_search
        self.native_diagnostics: dict[str, Any] = {
            "native_requests": 0,
            "fallback_requests": 0,
            "events": [],
        }
        self.content = content
        self._ladders = build_ladders(content)
        self._item_ids_by_key = {key: item.owned_item_ids for key, item in content.items.items()}
        self._equipment_root = equipment_root
        self._equipment: EquipmentCatalog | None = None
        self._optimization_lock = Lock()
        self.auto_pool = auto_pool
        self._progress_record: tuple[str, RunProgress] | None = None
        self._timings = TimingModel()

    def optimization_progress(self, identity: str) -> dict[str, Any] | None:
        """Read the latest request-local progress without exposing another request."""
        record = self._progress_record
        if record is None or record[0] != identity:
            return None
        return record[1].snapshot()

    def equipment_catalog(self) -> EquipmentCatalog:
        """Load bundled metadata once; no network, database session or refresh."""
        if self._equipment is None:
            self._equipment = load_catalog(self.content, self._equipment_root)
        return self._equipment

    def supported_catalog(
        self, support_policy: SupportPolicy = "verified_only"
    ) -> EquipmentCatalog:
        return cast(EquipmentCatalog, project_catalog(self.equipment_catalog(), support_policy))

    def optimize(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest | Mapping[str, Any],
        *,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
        cancelled: Callable[[], bool] | None = None,
        local_refinement: bool = False,
        progress_identity: str | None = None,
        progress_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Shared complete-loadout optimizer, separate from legacy factual change tools."""
        from tracker.gear.npcs import resolve_request
        from tracker.gear.optimizer import optimize

        request = resolve_request(request)

        if not self._optimization_lock.acquire(blocking=False):
            raise ValueError("optimizer_busy: another equipment search is running")
        tracker: RunProgress | None = None
        try:
            runner: Callable[..., dict[str, Any]] = optimize
            execution: dict[str, Any] = {}
            if self.optimization_profile != "baseline":
                execution["_execution_profile"] = self.optimization_profile
            if self.fixed_reporting:
                execution["_fixed_reporting"] = True
            if self.factored_evaluation:
                execution["_factored_evaluation"] = True
            if self.compact_states:
                execution["_compact_states"] = True
            if self.native_search:
                execution["_native_search"] = True
            pool = self.auto_pool
            parallel = False
            if request.potions.mode == "optimize":
                if pool is not None:
                    execution["potion_branch_runner"] = pool.run_potions
                    parallel = True
            elif pool is not None and any(
                len(role.allowed_disciplines or ()) > 1 for role in request.roles
            ):
                from tracker.gear.auto import optimize_auto

                runner = optimize_auto
                execution["branch_runner"] = pool.run
                parallel = True
            if progress_identity is not None:
                tracker = RunProgress(
                    has_frontiers=_has_frontiers(request, self.equipment_catalog()),
                    parallelism=getattr(pool, "workers", 1) if parallel else 1,
                    timing_key=_timing_key(
                        request,
                        local_refinement,
                        parallel,
                        self.optimization_profile,
                        self.fixed_reporting,
                        self.factored_evaluation,
                        self.compact_states,
                        self.native_search,
                    ),
                    model=self._timings,
                    fingerprint=progress_fingerprint,
                )
                self._progress_record = (progress_identity, tracker)
                execution["progress"] = tracker.handle
            from tracker.gear.native import capture, merge

            with capture() if self.native_search else nullcontext(None) as native_evidence:
                try:
                    result = runner(
                        snapshot,
                        request,
                        self.equipment_catalog(),
                        self.content,
                        dict(price_records or {}),
                        now or datetime.now(UTC),
                        cancelled=cancelled,
                        **({"local_refinement": True} if local_refinement else {}),
                        **execution,
                    )
                finally:
                    if native_evidence is not None:
                        self.native_diagnostics = native_evidence.snapshot()
            if self.native_search:
                merge(self.native_diagnostics)
            if tracker is not None:
                tracker.finish(succeeded=True)
            return result
        except BaseException:
            if tracker is not None:
                tracker.finish(succeeded=False)
            raise
        finally:
            self._optimization_lock.release()

    def evaluate(
        self,
        snapshot: AccountSnapshot,
        request: OptimizationRequest | Mapping[str, Any],
        baseline: Mapping[str, int],
        proposed: Mapping[str, int],
        *,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
        cancelled: Callable[[], bool] | None = None,
        baseline_combat_option: Mapping[str, Any] | None = None,
        proposed_combat_option: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate two fixed single-role loadouts without running candidate search."""
        from tracker.gear.evaluation import evaluate_configurations

        normalized = (
            request
            if isinstance(request, OptimizationRequest)
            else OptimizationRequest.model_validate(request)
        )
        from tracker.gear.npcs import resolve_request

        normalized = resolve_request(normalized)
        if len(normalized.roles) != 1 or normalized.roles[0].style == "special":
            raise ValueError("Exact evaluation supports one ordinary-attack role")
        if not self._optimization_lock.acquire(blocking=False):
            raise ValueError("optimizer_busy: another equipment calculation is running")
        try:
            if cancelled and cancelled():
                raise ValueError("evaluation_cancelled")
            result = evaluate_configurations(
                snapshot,
                normalized,
                baseline,
                proposed,
                self.equipment_catalog(),
                self.content,
                dict(price_records or {}),
                now or datetime.now(UTC),
                baseline_combat_option=baseline_combat_option,
                proposed_combat_option=proposed_combat_option,
            )
            if cancelled and cancelled():
                raise ValueError("evaluation_cancelled")
            return result
        finally:
            self._optimization_lock.release()

    def optimizer_catalog(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str | None = None,
        query: str = "",
        slot: str | None = None,
        ownership: str | None = None,
        wear_status: str | None = None,
        acquisition: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
        support_policy: SupportPolicy = "verified_only",
    ) -> dict[str, Any]:
        """Inspectable physical equipment, including locked and unsupported upgrades."""
        for label, value, choices in (
            ("ownership", ownership, _OWNERSHIP),
            ("wear_status", wear_status, _WEAR),
            ("acquisition", acquisition, _ACQUISITION),
        ):
            if value is not None and value not in choices:
                raise ValueError(f"invalid {label}: {value!r}")
        if offset < 0 or (limit is not None and not 1 <= limit <= 1000):
            raise ValueError("invalid catalog pagination")
        if style is not None and style not in _STYLES:
            raise ValueError("invalid catalog style")
        catalog = self.supported_catalog(support_policy)
        if slot is not None and slot not in {item.slot for item in catalog.items.values()}:
            raise ValueError("unknown equipment slot")
        evaluated_at = now or datetime.now(UTC)
        facts = []
        for item in sorted(catalog.items.values(), key=lambda row: (row.name, row.id)):
            if query.strip().casefold() not in item.name.casefold() and query.strip() != str(
                item.id
            ):
                continue
            if slot is not None and item.slot != slot:
                continue
            if style is not None and item.slot == "weapon":
                attacks = {"stab", "slash", "crush"} if style == "melee" else {style}
                if style != "magic" and not attacks.intersection(item.attack_styles):
                    continue
            fact = equipment_fact(
                snapshot,
                item,
                self.content,
                price_records or {},
                evaluated_at,
                support_assumptions=getattr(catalog, "community_assumptions", {}).get(item.id, ()),
            )
            if (
                (ownership is not None and ownership != fact["ownership"]["status"])
                or (wear_status is not None and wear_status != fact["wear"]["status"])
                or (acquisition is not None and acquisition != fact["acquisition"])
            ):
                continue
            facts.append(
                {**fact, "numeric_item_id": item.id, "equipment": item.model_dump(mode="json")}
            )
        end = offset + limit if limit is not None else len(facts)
        return {
            **self._metadata(snapshot),
            "items": facts[offset:end],
            "total": len(facts),
            "offset": offset,
            "limit": limit,
            "catalog_version": catalog.revision,
            "next_offset": end if end < len(facts) else None,
        }

    def physical_item(
        self,
        snapshot: AccountSnapshot | None,
        item_id: int,
        *,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
        support_policy: SupportPolicy = "verified_only",
    ) -> dict[str, Any]:
        """Concrete physical identity; never resolve through curated ownership aliases."""
        catalog = self.supported_catalog(support_policy)
        item = catalog.items[item_id]
        records = price_records or {}
        evaluated_at = now or datetime.now(UTC)
        fact = equipment_fact(
            snapshot or AccountSnapshot(0, ""),
            item,
            self.content,
            records,
            evaluated_at,
            support_assumptions=getattr(catalog, "community_assumptions", {}).get(item.id, ()),
        )
        market_id = (fact.get("preparation") or {}).get("market_item_id", item_id)
        authored = [entry for entry in self.content.items.values() if entry.item_id == market_id]
        record = records.get(market_id)
        quote = resolve_price(authored[0] if authored else None, record, now=evaluated_at)
        price = {
            **fact["price"],
            "confidence": quote.confidence.name.lower()
            if fact["acquisition"] == "tradeable"
            else None,
            "policy": quote.policy.value if fact["acquisition"] == "tradeable" else None,
            "source": record.source if record else None,
            "provider": getattr(record, "provider", None),
            "fetched_at": record.fetched_at.isoformat() if record else None,
            "high_price_gp": record.high_price_gp if record else None,
            "low_price_gp": record.low_price_gp if record else None,
            "high_trade_at": record.high_trade_at.isoformat()
            if record and record.high_trade_at
            else None,
            "low_trade_at": record.low_trade_at.isoformat()
            if record and record.low_trade_at
            else None,
        }
        if item.tradeable is None:
            price.update(layer="unknown", selection_reason="Tradeability unknown")
        return {
            **fact,
            "numeric_item_id": item.id,
            "equipment": item.model_dump(mode="json"),
            "price": price,
            "catalog_version": catalog.revision,
            "acquisition_descriptions": [
                entry.acquired_from for entry in authored if entry.acquired_from
            ],
        }

    def progression(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        slot: str | None = None,
        offset: int = 0,
        limit: int = 50,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """An authored ladder page, with no selected or recommended rung."""
        self._validate_style_slot(style, slot)
        self._validate_page(offset, limit)
        entries = self._entries(style, slot)
        return self._page(
            snapshot,
            entries,
            offset,
            limit,
            price_records or {},
            now or datetime.now(UTC),
            style=style,
            slot=slot,
        )

    def candidates(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        slot: str | None = None,
        ownership: str | None = None,
        wear_status: str | None = None,
        acquisition: str | None = None,
        offset: int = 0,
        limit: int = 50,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Filter only on facts; do not rank items by utility or price."""
        self._validate_style_slot(style, slot)
        self._validate_page(offset, limit)
        for label, value, choices in (
            ("ownership", ownership, _OWNERSHIP),
            ("wear_status", wear_status, _WEAR),
            ("acquisition", acquisition, _ACQUISITION),
        ):
            if value is not None and value not in choices:
                raise ValueError(f"invalid {label}: {value!r}")
        records = price_records or {}
        evaluated_at = now or datetime.now(UTC)
        items = [
            self._item_fact(snapshot, item, records, evaluated_at)
            for item in self._entries(style, slot)
        ]
        filtered = [
            item
            for item in items
            if (ownership is None or item["ownership"]["status"] == ownership)
            and (wear_status is None or item["wear"]["status"] == wear_status)
            and (acquisition is None or item["acquisition"] == acquisition)
        ]
        return self._slice(snapshot, filtered, offset, limit, style=style, slot=slot)

    def item_details(
        self,
        snapshot: AccountSnapshot,
        *,
        content_id: str | None = None,
        numeric_item_id: int | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if (content_id is None) == (numeric_item_id is None):
            raise ValueError("provide exactly one of content_id or numeric_item_id")
        if content_id is not None:
            item = self.content.items.get(content_id)
            if item is None:
                raise ValueError(f"unknown content_id: {content_id}")
            matches = [item]
        else:
            if (
                isinstance(numeric_item_id, bool)
                or not isinstance(numeric_item_id, int)
                or numeric_item_id <= 0
            ):
                raise ValueError("numeric_item_id must be a positive integer")
            matches = [
                item
                for item in self.content.items.values()
                if numeric_item_id in item.owned_item_ids
            ]
            if not matches:
                physical = self.equipment_catalog().items.get(numeric_item_id)
                if physical is None:
                    raise ValueError(f"unknown numeric_item_id: {numeric_item_id}")
                fact = equipment_fact(
                    snapshot, physical, self.content, price_records or {}, now or datetime.now(UTC)
                )
                return {
                    **self._metadata(snapshot),
                    "query": {"content_id": None, "numeric_item_id": numeric_item_id},
                    "ambiguous": False,
                    "items": [
                        {
                            **fact,
                            "numeric_item_id": physical.id,
                            "equipment": physical.model_dump(mode="json"),
                        }
                    ],
                    "catalog_version": self.equipment_catalog().revision,
                }
        ordered = sorted(
            matches, key=lambda item: (item.style or "", item.slot or "", item.tier or 0, item.id)
        )
        records = price_records or {}
        evaluated_at = now or datetime.now(UTC)
        return {
            **self._metadata(snapshot),
            "query": {"content_id": content_id, "numeric_item_id": numeric_item_id},
            "ambiguous": len(ordered) > 1,
            "items": [self._item_fact(snapshot, item, records, evaluated_at) for item in ordered],
        }

    def evaluate_change(
        self,
        snapshot: AccountSnapshot,
        *,
        style: str,
        changes: Sequence[Mapping[str, str]],
        expected_snapshot_id: str | None = None,
        price_records: Mapping[int, PriceRecord] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._validate_style_slot(style, None)
        if expected_snapshot_id is not None and expected_snapshot_id != snapshot.fingerprint:
            raise ValueError("snapshot_changed: retrieve current gear progression and candidates")
        if (
            isinstance(changes, str | bytes)
            or not isinstance(changes, Sequence)
            or not 1 <= len(changes) <= 5
        ):
            raise ValueError("changes must contain 1 to 5 items")
        items: list[Item] = []
        used_slots: set[str] = set()
        used_ids: set[int] = set()
        for change in changes:
            if not isinstance(change, Mapping):
                raise ValueError("each change requires string slot and content_id")
            slot, content_id = change.get("slot"), change.get("content_id")
            if not isinstance(slot, str) or not isinstance(content_id, str):
                raise ValueError("each change requires string slot and content_id")
            item = self.content.items.get(content_id)
            if item is None or item.style != style or item.slot != slot or item.tier is None:
                raise ValueError(f"item {content_id!r} is not an authored {style}/{slot} rung")
            if slot in used_slots:
                raise ValueError(f"duplicate slot: {slot}")
            if used_ids.intersection(item.owned_item_ids):
                raise ValueError(f"duplicate physical item: {content_id}")
            used_slots.add(str(slot))
            used_ids.update(item.owned_item_ids)
            items.append(item)

        records = price_records or {}
        evaluated_at = now or datetime.now(UTC)
        facts = [self._item_fact(snapshot, item, records, evaluated_at) for item in items]
        subtotal = 0
        reasons: set[str] = set()
        proposal_facts = []
        for fact in facts:
            held = fact["ownership"]["status"]
            if held == "owned":
                proposal_facts.append({**fact, "purchase_status": "unnecessary"})
                continue
            if held == "unknown":
                reasons.add("unknown_ownership")
                proposal_facts.append({**fact, "purchase_status": "unknown"})
                continue
            if fact["acquisition"] == "untradeable":
                reasons.add("unowned_untradeable")
                proposal_facts.append({**fact, "purchase_status": "not_applicable"})
            elif fact["acquisition"] == "unknown":
                reasons.add("unknown_acquisition")
                proposal_facts.append({**fact, "purchase_status": "unknown"})
            else:
                proposal_facts.append({**fact, "purchase_status": "necessary"})
                if fact["price"]["amount_gp"] is None:
                    reasons.add("unknown_price")
                else:
                    subtotal += fact["price"]["amount_gp"]
        return {
            **self._metadata(snapshot),
            "style": style,
            "items": proposal_facts,
            "purchase_subtotal_gp": subtotal if not reasons else None,
            "subtotal_unknown_reasons": sorted(reasons),
            "joint_loadout_validity": "not_evaluated",
            "limitations": list(_LIMITATIONS),
        }

    def _entries(self, style: str, slot: str | None) -> list[Item]:
        return [
            item
            for ladder in self._ladders
            if ladder.style == style and (slot is None or ladder.slot == slot)
            for item in ladder.rungs
        ]

    def _page(
        self,
        snapshot: AccountSnapshot,
        entries: list[Item],
        offset: int,
        limit: int,
        records: Mapping[int, PriceRecord],
        now: datetime,
        *,
        style: str,
        slot: str | None,
    ) -> dict[str, Any]:
        page = [
            self._item_fact(snapshot, item, records, now)
            for item in entries[offset : offset + limit]
        ]
        return {
            **self._metadata(snapshot),
            "style": style,
            "slot": slot,
            "items": page,
            "total": len(entries),
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if offset + limit < len(entries) else None,
        }

    def _slice(
        self,
        snapshot: AccountSnapshot,
        items: list[dict[str, Any]],
        offset: int,
        limit: int,
        *,
        style: str,
        slot: str | None,
    ) -> dict[str, Any]:
        return {
            **self._metadata(snapshot),
            "style": style,
            "slot": slot,
            "items": items[offset : offset + limit],
            "total": len(items),
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if offset + limit < len(items) else None,
        }

    def _item_fact(
        self,
        snapshot: AccountSnapshot,
        item: Item,
        records: Mapping[int, PriceRecord],
        now: datetime,
    ) -> dict[str, Any]:
        if item.gate_unknown:
            known_requirements = (
                evaluate_requirement(snapshot, item.requires, item_ids_by_key=self._item_ids_by_key)
                if item.requires is not None
                else None
            )
            wear = {
                "status": "unknown",
                "gate_unknown": True,
                "requirements": known_requirements.model_dump(mode="json")
                if known_requirements
                else None,
                "unmet": [leaf.model_dump(mode="json") for leaf in known_requirements.unmet()]
                if known_requirements
                else [],
            }
        elif item.requires is None:
            wear = {
                "status": "satisfied",
                "gate_unknown": False,
                "requirements": None,
                "unmet": [],
            }
        else:
            result = evaluate_requirement(
                snapshot, item.requires, item_ids_by_key=self._item_ids_by_key
            )
            wear = {
                "status": result.status.value,
                "gate_unknown": False,
                "requirements": result.model_dump(mode="json"),
                "unmet": [leaf.model_dump(mode="json") for leaf in result.unmet()],
            }
        ownership = self._ownership(snapshot, item)
        record = (
            records.get(item.item_id)
            if item.acquisition == "tradeable" and item.item_id is not None
            else None
        )
        price = resolve_price(item, record, now=now) if item.acquisition == "tradeable" else None
        return {
            "content_id": item.id,
            "name": item.name,
            "numeric_item_id": item.item_id,
            "variant_item_ids": list(item.variant_item_ids),
            "curated_progression_member": (
                item.style is not None and item.slot is not None and item.tier is not None
            ),
            "style": item.style,
            "slot": item.slot,
            "tier": item.tier,
            "ownership": ownership,
            "wear": wear,
            "acquisition": item.acquisition or "unknown",
            "acquired_from": item.acquired_from,
            "price": {
                "amount_gp": price.gp if price else None,
                "layer": price.layer.value if price else "not_tradeable",
                "selection_reason": price.selection_reason if price else "not a GE purchase",
                "confidence": price.confidence.value if price else None,
                "policy": price.policy.value if price else None,
                "selected_trade_at": price.trade_at.isoformat()
                if price and price.trade_at
                else None,
                "fetched_at": record.fetched_at.isoformat() if record else None,
                "provider": getattr(record, "provider", None) if record else None,
            },
        }

    @staticmethod
    def _ownership(snapshot: AccountSnapshot, item: Item) -> dict[str, Any]:
        scans = {
            container.value: (
                {"scanned_at": scan.scanned_at.isoformat(), "source": scan.source}
                if (scan := snapshot.container_scans.get(container)) is not None
                else None
            )
            for container in Container
        }
        # A newer accepted full scan supersedes earlier sightings in the same container.
        sightings = [
            fact
            for (item_id, container), fact in snapshot.observed_items.items()
            if item_id in item.owned_item_ids
            and fact.quantity > 0
            and (
                (scan := snapshot.container_scans.get(container)) is None
                or fact.observed_at >= scan.scanned_at
            )
        ]
        status = (
            "owned"
            if sightings
            else ("unowned" if all(value is not None for value in scans.values()) else "unknown")
        )
        return {
            "status": status,
            "meaning": "not observed in the latest accepted scans"
            if status == "unowned"
            else "observed item sighting"
            if status == "owned"
            else "incomplete container scan coverage",
            "observed_containers": sorted({fact.container.value for fact in sightings}),
            "sightings": [
                {
                    "numeric_item_id": fact.item_id,
                    "container": fact.container.value,
                    "quantity": fact.quantity,
                    "source": fact.source,
                    "observed_at": fact.observed_at.isoformat(),
                }
                for fact in sorted(sightings, key=lambda f: (f.container.value, f.item_id))
            ],
            "container_scans": scans,
        }

    @staticmethod
    def _metadata(snapshot: AccountSnapshot) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot.fingerprint,
            "last_sync_at": snapshot.last_sync_at.isoformat() if snapshot.last_sync_at else None,
            "container_scans": {
                container.value: (
                    {"scanned_at": scan.scanned_at.isoformat(), "source": scan.source}
                    if (scan := snapshot.container_scans.get(container)) is not None
                    else None
                )
                for container in Container
            },
        }

    def _validate_style_slot(self, style: str, slot: str | None) -> None:
        if style not in _STYLES:
            raise ValueError(f"invalid style: {style!r}")
        if slot is not None and not any(
            ladder.style == style and ladder.slot == slot for ladder in self._ladders
        ):
            raise ValueError(f"unknown authored slot for {style}: {slot!r}")

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
