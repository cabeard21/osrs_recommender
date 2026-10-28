"""Frozen redacted account case loader for search regression and benchmarks."""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from tools.gear_retention_oracle import Case
from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, QuestStatus, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest
from tracker.integrations.prices.client import PriceDTO, PriceSource


@lru_cache
def fixture_data(fixture_name="gear_search_quality_account.json"):
    return json.loads((Path(__file__).parents[1] / "tests/fixtures" / fixture_name).read_text())


def load_case(name, *, fixture_name="gear_search_quality_account.json"):
    data = fixture_data(fixture_name)
    at = datetime.fromisoformat(data["provenance"]["at"])
    snapshot = AccountSnapshot(
        1,
        "redacted-search-regression",
        skills={k: SkillState(v, None, Source.MANUAL, at) for k, v in data["skills"].items()},
        quests={k: QuestStatus(v) for k, v in data["quests"].items()},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "fixture", at)
            for i in data["owned_ids"]
        },
        container_scans={c: ContainerScanFact(c, at, "fixture") for c in Container},
        quest_points=data["quest_points"],
        combat_level=data["combat_level"],
        members=data["members"],
    )
    prices = {}
    for key, row in data["prices"].items():
        converted = {
            k: datetime.fromisoformat(v) if k.endswith("_at") and v else v for k, v in row.items()
        }
        prices[int(key)] = PriceDTO(**{**converted, "source": PriceSource(row["source"])})
    return Case(
        name,
        snapshot,
        OptimizationRequest.model_validate(data["requests"][name]),
        EquipmentCatalog(
            {row["id"]: EquipmentDefinition.model_validate(row) for row in data["equipment"]}
        ),
        Content(),
        prices,
        at,
    )
