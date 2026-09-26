"""Scenario YAML → ``PlayerState`` + ``RoadmapSelection`` (§16.1).

The retained calibration tool, ``tools/tune_weights.py``, uses these recorded scenarios
to search for weights. The old ranking-judgment pytest suite has been retired.
If those two read the corpus through different code, the search optimizes something the
suite does not check — so the loader lives here, in the corpus's own directory, and the
tuner imports it rather than reimplementing it.

Scenarios are written in **positives**, like ``tests/recommendations/conftest.py``: a
scenario says what the account has, never what it lacks. The difference between *"you do not
own a Voidwaker"* and *"nobody has looked"* is then carried by one field, ``scanned`` (§6.5,
§4.5) — which is what makes the ``unknown_bank`` scenario a single-line variation on a
scenario that otherwise reads identically, rather than a separate hand-built fixture.

**Milestone `class` and `kind` are read from the corpus, not from the scenario.** §6.6 makes
those properties of the milestone, not of the account; letting a scenario restate them would
let the corpus and the fixture disagree about whether a milestone can decay at all, and
every refresher judgment here turns on exactly that.

Judgments (§16.1)
-----------------

Only three shapes, all relative:

``must_rank_above``   an ordered pair — the first must outrank the second
``top_3_contains``    an id that must appear in the first three primary entries
``must_not_be_top``   an id that must not hold rank 1

No scenario may assert a full ordering. Two near-tied candidates flip on noise, and a test
that fails for that reason teaches nothing (§16.1).

``pending_review`` (§16.3 step 5)
---------------------------------

A judgment the shipped v1 weights **disagree with**, carrying the reviewer's note. §16.3
step 5 is explicitly a human decision — *"a disagreement is as likely to reveal a bad
judgment as a bad weight"* — and the two available ways to make the suite green without one
are both wrong: deleting the judgment silently adopts the engine's answer as the expert's,
and leaving it red makes the corpus unusable as a regression suite for everything else.

So a ``pending_review`` judgment is **recorded in full, counted in full by the tuner, and
xfailed strictly** by ``test_judgments.py``. Strictly, so that the moment a retune makes one
pass, the suite fails and says so: the marker is a claim about the current profile, not a
permanent exemption. Resolving the review means either deleting the marker (the weights were
wrong, and the retune fixed it) or deleting the judgment with a note in ``docs/TUNING.md``
(the judgment was wrong).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from tracker.content.loader import Content
from tracker.content.schema import ScoringProfile
from tracker.content.validate import load_and_validate
from tracker.domain.types import (
    Container,
    GpSensitivity,
    IncumbentRecommendation,
    ItemObservation,
    MilestoneState,
    PlayerState,
    QuestStatus,
    Recommendation,
    RoadmapSelection,
    SkillState,
    Source,
    Tri,
    UnlockState,
)
from tracker.recommendations.engine import recommend_run

SCENARIO_DIR = Path(__file__).parent / "scenarios"
#: Effectively no cap. §9.8's display cut is a policy about a page, not about the engine,
#: and the golden harness judges the engine — see :class:`Outcome`.
_NO_CAP = 10_000

CONTENT_ROOT = Path(__file__).parent.parent.parent / "content"

#: The corpus's fixed clock. §16.1 requires the engine to take ``now`` as an argument, so
#: no scenario's meaning depends on when the suite runs.
NOW = datetime(2026, 8, 4, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Judgment:
    """One recorded expert preference, with the reasoning that justifies it.

    ``because`` is not decoration. §16.3 step 5 says *"a disagreement is as likely to reveal
    a bad judgment as a bad weight"*, and a reviewer cannot make that call against a bare
    pair of ids.
    """

    kind: str
    subject: str
    over: str | None
    because: str
    pending_review: str | None = None
    """Set when the shipped weights disagree — see this module's docstring."""

    @property
    def label(self) -> str:
        if self.over is not None:
            return f"{self.subject} > {self.over}"
        return f"{self.kind}:{self.subject}"


@dataclass(frozen=True, slots=True)
class PriceOverride:
    """A pinned price, so a scenario's cost factor does not depend on the live market.

    Implements :class:`tracker.estimation.prices.PriceRecord` structurally — read-only
    properties, for the reason that protocol's own docstring gives.
    """

    _item_id: int
    _high: int | None
    _low: int | None
    _traded_at: datetime | None
    _fetched_at: datetime

    @property
    def item_id(self) -> int:
        return self._item_id

    @property
    def high_price_gp(self) -> int | None:
        return self._high

    @property
    def high_trade_at(self) -> datetime | None:
        return self._traded_at

    @property
    def low_price_gp(self) -> int | None:
        return self._low

    @property
    def low_trade_at(self) -> datetime | None:
        return self._traded_at

    @property
    def fetched_at(self) -> datetime:
        return self._fetched_at

    @property
    def source(self) -> str:
        return "live"

    def scaled(self, factor: float) -> PriceOverride:
        """The same record with both trade prices moved by ``factor`` (§16.2's 2% test)."""
        return PriceOverride(
            _item_id=self._item_id,
            _high=None if self._high is None else round(self._high * factor),
            _low=None if self._low is None else round(self._low * factor),
            _traded_at=self._traded_at,
            _fetched_at=self._fetched_at,
        )


@dataclass(frozen=True, slots=True)
class Scenario:
    """One fixture account, its roadmap selection, and the judgments recorded about it."""

    id: str
    title: str
    notes: str
    state: PlayerState
    selection: RoadmapSelection
    now: datetime
    prices: Mapping[int, PriceOverride] = field(default_factory=dict)
    incumbent: IncumbentRecommendation | None = None
    judgments: tuple[Judgment, ...] = ()

    @property
    def pairs(self) -> tuple[Judgment, ...]:
        """Only the ``must_rank_above`` judgments — §16.3's *"pairwise preferences"*.

        The tuner scores agreement over these alone. ``top_3_contains`` and
        ``must_not_be_top`` are absolute statements about a list position, and optimizing a
        rate that mixes the two would let a weight vector trade three genuine preference
        inversions for one candidate moving from rank 4 to rank 3.
        """
        return tuple(j for j in self.judgments if j.kind == "must_rank_above")


@dataclass(frozen=True, slots=True)
class Outcome:
    """One scenario's ranking, in the two forms the judgments are read against.

    ``ranked`` is every scored candidate, refreshers included, in score order. ``primary``
    is §9.8's displayed list, after the at-most-one-refresher policy has moved the rest to
    the Practice freshness view.

    **Pairwise judgments read ``ranked``; positional judgments read ``primary``.** §9.8's
    list policy is a display rule applied *after* scoring — ``enforce_list_policy`` runs on
    an already-ordered list — so asking "did the engine prefer A to B?" of the truncated list
    would report a second refresher as *unranked* when the engine had in fact ranked it
    second. ``top_3_contains`` and ``must_not_be_top``, by contrast, are statements about
    what the user is shown, and the user is shown ``primary``.

    ``max_primary_entries`` is a display rule of exactly that kind, and :func:`evaluate`
    opts out of it for the same reason. Once the corpus grew past a page of candidates the
    cut started removing the deliberately-worst entries — ``train_woodcutting`` above all,
    which §10.6 keeps in the corpus precisely so that *"advances nothing ⇒ ranks last"* is
    an assertable claim rather than an absence. Reading judgments off the capped list would
    have silently converted twenty recorded preferences into "could not be evaluated".
    """

    ranked: tuple[Recommendation, ...]
    primary: tuple[Recommendation, ...]
    blocked: tuple[Recommendation, ...]

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(entry.candidate_id for entry in self.ranked)

    @property
    def primary_order(self) -> tuple[str, ...]:
        return tuple(entry.candidate_id for entry in self.primary)

    def verdict(self, judgment: Judgment) -> bool | None:
        """Whether one judgment holds. ``None`` means it could not be evaluated.

        A pairwise judgment naming a candidate that did not rank — because it is complete,
        or blocked — is *vacuous*, not satisfied. Scoring it as agreement would let the
        tuner buy agreement by making candidates disappear, which is the one way to get a
        perfect rate without ever ordering anything correctly.
        """
        order = self.order
        if judgment.kind == "must_rank_above":
            if judgment.subject not in order or judgment.over not in order:
                return None
            return order.index(judgment.subject) < order.index(str(judgment.over))
        if judgment.kind == "top_3_contains":
            return judgment.subject in self.primary_order[:3]
        if judgment.kind == "must_not_be_top":
            if not self.primary_order:
                return None
            return self.primary_order[0] != judgment.subject
        raise ValueError(f"unknown judgment kind {judgment.kind!r}")


def evaluate(scenario: Scenario, content: Content, profile: ScoringProfile) -> Outcome:
    """Run the engine over one scenario. The single call site both consumers share.

    The run is made with the display cap lifted and the real cap re-applied here, so that
    ``ranked`` sees the whole ordering while ``primary`` stays exactly what the user is
    shown. Re-applying it here rather than raising the cap and forgetting it keeps the two
    kinds of judgment reading the two different lists they are each about.
    """
    uncapped = profile.model_copy(update={"max_primary_entries": _NO_CAP})
    run = recommend_run(
        scenario.state,
        scenario.selection,
        content,
        uncapped,
        scenario.incumbent,
        prices=scenario.prices,
        now=scenario.now,
    )
    ranked = sorted(
        [*run.primary, *run.deferred_refreshers],
        key=lambda entry: (-entry.score, entry.candidate_id),
    )
    return Outcome(
        ranked=tuple(ranked),
        primary=run.primary[: profile.max_primary_entries],
        blocked=run.blocked,
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def load_scenarios(content: Content, directory: Path = SCENARIO_DIR) -> tuple[Scenario, ...]:
    """Every scenario in ``directory``, in filename order."""
    return tuple(load_scenario(path, content) for path in sorted(directory.glob("*.yaml")))


@lru_cache(maxsize=1)
def corpus() -> tuple[Content, tuple[Scenario, ...]]:
    """The validated content and the parsed corpus, loaded once per process.

    Cached rather than offered as a session fixture because the judgment tests parametrize
    over the scenarios, and parametrization happens at collection time — before any fixture
    can run. The tuner wants the same pair and has no fixtures at all.
    """
    content = load_and_validate(CONTENT_ROOT)
    return content, load_scenarios(content)


def load_scenario(path: Path, content: Content) -> Scenario:
    """Parse one scenario file against the corpus it is written about."""
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: a scenario file must contain one mapping")

    now = _timestamp(raw.get("now"), NOW)
    scenario_id = str(raw.get("id") or path.stem)
    player = raw.get("player") or {}

    _reject_unknown(
        path,
        raw,
        {"id", "title", "notes", "now", "player", "roadmaps", "prices", "incumbent", "judgments"},
    )
    _reject_unknown(
        path,
        player,
        {
            "synced",
            "gp_sensitivity",
            "combat_level",
            "quest_points",
            "skills",
            "unlocks",
            "quests",
            "items",
            "scanned",
            "milestones",
        },
    )

    return Scenario(
        id=scenario_id,
        title=str(raw.get("title") or scenario_id),
        notes=str(raw.get("notes") or ""),
        state=_player_state(player, content, now),
        selection=RoadmapSelection(
            {str(k): float(v) for k, v in (raw.get("roadmaps") or {}).items()}
        ),
        now=now,
        prices=_prices(raw.get("prices") or {}, content, now),
        incumbent=(
            IncumbentRecommendation(candidate_id=str(raw["incumbent"]))
            if raw.get("incumbent")
            else None
        ),
        judgments=_judgments(path, raw.get("judgments") or {}, content),
    )


def _player_state(raw: Mapping[str, Any], content: Content, now: datetime) -> PlayerState:
    synced = bool(raw.get("synced", True))
    return PlayerState(
        player_id=1,
        skills=_skills(raw.get("skills") or {}, now),
        unlocks={str(k): UnlockState(v) for k, v in (raw.get("unlocks") or {}).items()},
        quests={str(k): QuestStatus(v) for k, v in (raw.get("quests") or {}).items()},
        observed_items=_items(raw.get("items") or [], content, now),
        container_scans=_scans(raw.get("scanned", "all"), now),
        milestones=_milestones(raw.get("milestones") or [], content, now),
        combat_level=raw.get("combat_level"),
        quest_points=raw.get("quest_points"),
        gp_sensitivity=GpSensitivity(raw.get("gp_sensitivity", "normal")),
        last_sync_at=now if synced else None,
    )


def _skills(raw: Mapping[str, Any], now: datetime) -> dict[str, SkillState]:
    """``name: level`` or ``name: {level, xp}``.

    ``xp`` stays ``None`` unless authored — G5's rule is that an absent number is ``NULL``,
    never ``0``, and §8.2 falls back to the level's own XP when it has nothing better.
    """
    skills: dict[str, SkillState] = {}
    for name, value in raw.items():
        if isinstance(value, Mapping):
            level, xp = int(value["level"]), value.get("xp")
        else:
            level, xp = int(value), None
        skills[str(name)] = SkillState(
            level=level,
            xp=None if xp is None else int(xp),
            source=Source.RUNELITE,
            observed_at=now,
        )
    return skills


def _items(raw: Sequence[Any], content: Content, now: datetime) -> dict[int, ItemObservation]:
    """Owned items, named by **content** id and keyed by the numeric id §10.5 declares."""
    observations: dict[int, ItemObservation] = {}
    for entry in raw:
        item = content.items.get(str(entry))
        if item is None or item.item_id is None:
            raise ValueError(f"unknown or unnumbered item {entry!r}; declare it in content/items/")
        observations[item.item_id] = ItemObservation(
            item_id=item.item_id,
            quantity=1,
            containers=frozenset({Container.BANK}),
            observed_at=now,
        )
    return observations


def _scans(raw: Any, now: datetime) -> dict[Container, datetime]:
    """``all`` / ``none`` / a list of container names, optionally ``{name: days_ago}``.

    This one field carries §6.5's whole distinction. With no scan, an ``item:`` leaf reads
    ``unknown`` rather than ``unsatisfied``, and the tri-state path the ``unknown_bank``
    scenario exists to exercise opens up.
    """
    if raw in ("all", True):
        return dict.fromkeys(Container, now)
    if raw in ("none", False, None):
        return {}
    if isinstance(raw, Mapping):
        return {Container(k): now - timedelta(days=float(v)) for k, v in raw.items()}
    return {Container(name): now for name in raw}


def _milestones(raw: Sequence[Any], content: Content, now: datetime) -> dict[str, MilestoneState]:
    states: dict[str, MilestoneState] = {}
    for entry in raw:
        key = str(entry["id"])
        declared = content.milestones.get(key)
        if declared is None:
            raise ValueError(f"unknown milestone {key!r}; declare it in content/milestones/")
        achieved = bool(entry.get("achieved", True))
        days = entry.get("practiced_days_ago", 0)
        attested = entry.get("attested")
        states[key] = MilestoneState(
            key=key,
            achieved=achieved,
            attested=(
                Tri(attested)
                if attested is not None
                else (Tri.SATISFIED if achieved else Tri.UNSATISFIED)
            ),
            kind=declared.kind,
            class_=declared.class_,
            value=entry.get("value"),
            last_practiced_at=None if days is None else now - timedelta(days=float(days)),
        )
    return states


def _prices(raw: Mapping[str, Any], content: Content, now: datetime) -> dict[int, PriceOverride]:
    """Pinned prices, by content item id. Anything unpriced falls through §8.3's cascade."""
    prices: dict[int, PriceOverride] = {}
    for name, entry in raw.items():
        item = content.items.get(str(name))
        if item is None or item.item_id is None:
            raise ValueError(f"unknown or unnumbered item {name!r} in prices")
        traded = now - timedelta(hours=float(entry.get("traded_hours_ago", 6)))
        prices[item.item_id] = PriceOverride(
            _item_id=item.item_id,
            _high=None if entry.get("high_gp") is None else int(entry["high_gp"]),
            _low=None if entry.get("low_gp") is None else int(entry["low_gp"]),
            _traded_at=traded,
            _fetched_at=now,
        )
    return prices


def _judgments(path: Path, raw: Mapping[str, Any], content: Content) -> tuple[Judgment, ...]:
    """The three judgment shapes, flattened into one list with their reasons attached."""
    _reject_unknown(path, raw, {"must_rank_above", "top_3_contains", "must_not_be_top"})
    judgments: list[Judgment] = []

    for entry in raw.get("must_rank_above") or []:
        subject, over = (str(part) for part in entry["pair"])
        judgments.append(
            Judgment(
                "must_rank_above",
                subject,
                over,
                str(entry.get("because", "")),
                _optional_text(entry.get("pending_review")),
            )
        )
    for kind in ("top_3_contains", "must_not_be_top"):
        for entry in raw.get(kind) or []:
            if isinstance(entry, Mapping):
                judgments.append(
                    Judgment(
                        kind,
                        str(entry["id"]),
                        None,
                        str(entry.get("because", "")),
                        _optional_text(entry.get("pending_review")),
                    )
                )
            else:
                judgments.append(Judgment(kind, str(entry), None, ""))

    _check_ids(path, judgments, content)
    return tuple(judgments)


def _check_ids(path: Path, judgments: Sequence[Judgment], content: Content) -> None:
    """Every judgment must name a candidate the corpus declares.

    A typo in an id would otherwise read as a candidate that never ranks — which is what a
    ``must_not_be_top`` judgment asserts, so half the corpus could pass by misspelling.
    """
    known = set(content.candidates) | set(content.refreshers)
    for judgment in judgments:
        for name in (judgment.subject, judgment.over):
            if name is not None and name not in known:
                raise ValueError(f"{path}: judgment names unknown candidate {name!r}")


def _optional_text(raw: Any) -> str | None:
    return None if raw is None else str(raw)


def _timestamp(raw: Any, default: datetime) -> datetime:
    if raw is None:
        return default
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(raw))


def _reject_unknown(path: Path, raw: Mapping[str, Any], allowed: set[str]) -> None:
    """A misspelled key must fail loudly.

    Silently ignoring ``scannned: none`` would leave a scenario claiming to exercise the
    unknown path while quietly running the fully-observed one — a green test asserting the
    opposite of what it says.
    """
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {', '.join(unknown)}")
