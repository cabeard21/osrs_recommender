"""Reviewed vampyre variants for ordinary attacks from the pinned NPC catalog.

Access, retreat and poison/venom resistance are reviewed against the
corresponding OSRS Wiki monster infobox and article, including Kroy, Venator,
Blood-starved venator, Ancient feral vyre, and Vyrewatch Sentinel.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType
from typing import Literal

from tracker.domain.types import QuestStatus

TIER_NOTES = MappingProxyType(
    {
        "vampyre1": "Tier 1 vampyre. All ordinary attack styles can deal damage.",
        "vampyre2": "Tier 2 vampyre. Use silver weaponry or equip Efaritay's aid.",
        "vampyre3": (
            "Tier 3 vampyre. Use an Ivandis, blisterwood or Hallowed flail, a plain "
            "blisterwood sickle, Sunspear, or ranged blisterwood stakes."
        ),
    }
)


@dataclass(frozen=True)
class QuestGate:
    id: str
    name: str
    started: bool = False

    @property
    def description(self) -> str:
        return f"{'starting' if self.started else 'completion of'} {self.name}"


@dataclass(frozen=True)
class TargetReview:
    trait: str
    susceptibility: Literal["immune", "susceptible"]
    note: str
    quest: QuestGate | None = None
    slayer: int | None = None
    task_eligible: bool = True

    def limitations(self) -> list[str]:
        notes = [TIER_NOTES[self.trait], self.note]
        if self.quest:
            access = f"{self.slayer} Slayer and " if self.slayer else ""
            notes.append(f"Access requires {access}{self.quest.description}.")
        return notes


_TREKKING = QuestGate("in_aid_of_the_myreque", "In Aid of the Myreque")
_MEIYERDITCH = QuestGate("darkness_of_hallowvale", "Darkness of Hallowvale", started=True)
_DARKMEYER = QuestGate("sins_of_the_father", "Sins of the Father", started=True)
_VAMPYRIUM = QuestGate("the_blood_moon_rises", "The Blood Moon Rises")
_FERAL = TargetReview(
    "vampyre1", "susceptible", "Ordinary attack DPS excludes bite healing and stat drains."
)
_JUVENILE = TargetReview(
    "vampyre1",
    "immune",
    "DPS covers attacks before retreat into mist. Defeating this target requires Guthix balance.",
)
_JUVINATE = replace(_JUVENILE, trait="vampyre2")
_VYREWATCH = TargetReview(
    "vampyre3", "immune", "DPS covers active combat after engaging the Vyrewatch."
)
_SENTINEL = replace(_VYREWATCH, quest=replace(_DARKMEYER, started=False))
_VENATOR = TargetReview(
    "vampyre3",
    "immune",
    "An off-task kill costs 30 Stymphike feathers. DPS covers active attacks and excludes "
    "movement and the venator's healing.",
    quest=_VAMPYRIUM,
    slayer=74,
)
_SUPERIOR = replace(
    _VENATOR,
    note="Spawning this superior requires Bigger and Badder and a regular venator kill. "
    "DPS covers the active target after it spawns.",
)
_ANCIENT = TargetReview(
    "vampyre3",
    "susceptible",
    "DPS covers the active post-quest target. Other ancient feral vyres can switch places "
    "and heal. These vyres do not qualify for Vampyres Slayer tasks.",
    quest=_VAMPYRIUM,
    task_eligible=False,
)

# Each entry binds the upstream ID, name, variant and expected tier. The numbered
# Sentinel variants are cosmetic and their IDs are not in ascending order.
_GROUPS = (
    (
        "Feral Vampyre",
        _FERAL,
        (
            (3237, "Level 61"),
            (4431, "Level 64 (Burgh de Rott/Crombwick Manor)"),
            (3234, "Level 72 (Spider)"),
            (3137, "Level 77 (God Wars Dungeon)"),
        ),
    ),
    ("Feral Vampyre", replace(_FERAL, quest=_MEIYERDITCH), ((3707, "Level 64 (Meiyerditch)"),)),
    (
        "Feral Vampyre",
        replace(_FERAL, quest=_TREKKING),
        (
            (5640, "Level 70 (Temple Trekking)"),
            (5641, "Level 100 (Temple Trekking)"),
            (5642, "Level 130 (Temple Trekking)"),
        ),
    ),
    ("Vampyre Juvenile", _JUVENILE, ((4436, "Burgh de Rott and Crombwick Manor"),)),
    ("Vampyre Juvenile", replace(_JUVENILE, quest=_MEIYERDITCH), ((3692, "Meiyerditch"),)),
    ("Vampyre Juvenile", replace(_JUVENILE, quest=_DARKMEYER), ((9731, "Darkmeyer"),)),
    (
        "Kroy",
        TargetReview(
            "vampyre1",
            "immune",
            "DPS uses Kroy's base combat stats and excludes scripted encounter mechanics.",
        ),
        ((9560, ""),),
    ),
    ("Vampyre Juvinate", _JUVINATE, ((4427, "Level 54 (Burgh de Rott)"),)),
    (
        "Vampyre Juvinate",
        replace(_JUVINATE, quest=_MEIYERDITCH),
        ((3694, "Level 54 (Meiyerditch)"),),
    ),
    ("Vampyre Juvinate", replace(_JUVINATE, quest=_DARKMEYER), ((9727, "Level 54 (Darkmeyer)"),)),
    (
        "Vampyre Juvinate",
        replace(_JUVINATE, quest=_TREKKING),
        (
            (5634, "Level 59 (Temple Trekking)"),
            (5635, "Level 90 (Temple Trekking)"),
            (5636, "Level 119 (Temple Trekking)"),
        ),
    ),
    (
        "Vyrewatch",
        _VYREWATCH,
        (
            (3709, "Level 105"),
            (3710, "Level 110"),
            (3711, "Level 120"),
            (3712, "Level 125"),
        ),
    ),
    (
        "Vyrewatch Sentinel",
        _SENTINEL,
        (
            (9756, "1"),
            (9757, "2"),
            (9760, "3"),
            (9762, "4"),
            (9763, "5"),
            (9759, "6"),
            (9758, "7"),
            (9761, "8"),
        ),
    ),
    ("Venator", _VENATOR, ((15765, "1"), (15766, "2"), (15767, "3"), (15768, "4"), (15769, "5"))),
    ("Blood-starved venator", _SUPERIOR, ((15770, ""),)),
    ("Ancient feral vyre", _ANCIENT, ((15760, "1"), (16230, "2"), (16231, "3"), (16232, "4"))),
)
PROFILES = MappingProxyType(
    {(i, name, version): review for name, review, ids in _GROUPS for i, version in ids}
)
REVISION = json.dumps(
    [dict(TIER_NOTES), [(key, asdict(review)) for key, review in PROFILES.items()]],
    sort_keys=True,
).encode()


def unsupported_reason(name: str, variant: str, npc_id: int) -> str:
    if "Nightmare Zone" in name:
        return f"{name} requires a review of its Nightmare Zone combat profile."
    if name == "Count Draynor":
        return "Count Draynor requires a review of his quest fight and stake finisher."
    if name in {"Vanstrom Klause", "Ranis Drakan", "Lowerniel Drakan"}:
        return f"{name} requires a review of the boss phases and their attack restrictions."
    if npc_id in {8252, 4442, 4443, 9561, 9614, 16212} or name in {
        "Dessous",
        "Venator (The Blood Moon Rises)",
    }:
        return f"{name} is a scripted quest fight requiring a separate combat review."
    return f"{name} ({variant or npc_id}) has no reviewed ordinary vampyre profile."


def validate_access(
    review: TargetReview,
    name: str,
    levels: Mapping[str, int],
    quests: Mapping[str, QuestStatus],
    overrides: Mapping[str, str],
    on_task: bool,
) -> None:
    if on_task and not review.task_eligible:
        raise ValueError(f"{name} does not qualify for a Vampyres Slayer task. Turn off on-task.")
    if review.slayer is not None and levels.get("slayer", 0) < review.slayer:
        raise ValueError(f"{name} requires {review.slayer} Slayer. The level is unknown or unmet.")
    if gate := review.quest:
        status = QuestStatus(overrides[gate.id]) if gate.id in overrides else quests.get(gate.id)
        if status is not QuestStatus.COMPLETE and not (
            gate.started and status is QuestStatus.IN_PROGRESS
        ):
            raise ValueError(
                f"{name} requires {gate.description}. Quest progress is unknown or unmet."
            )
