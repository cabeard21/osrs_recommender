"""§8.3 fetch scope: only ids referenced by the active roadmap's transitive closure.

Content is built directly as Python objects rather than from YAML fixtures — scope.py
is a pure function of an already-loaded `Content`, and constructing the corpus in code
keeps each test's "what is and is not reachable" shape visible in one place, including
the corpus-wide item ids a roadmap must exclude.
"""

from __future__ import annotations

from pathlib import Path

from tracker.content.loader import Content
from tracker.content.requirements import parse as parse_requirement
from tracker.content.schema import (
    Candidate,
    Capability,
    Item,
    KappaPresets,
    LevelRange,
    Roadmap,
    ScoringProfile,
    ScoringWeights,
    TrainingMethod,
)
from tracker.content.validate import load_and_validate
from tracker.domain.types import CandidateKind
from tracker.integrations.prices.scope import scoped_item_ids

_PROFILE = ScoringProfile(
    version=1,
    kappa_gp=KappaPresets(high=8_000_000, normal=20_000_000, low=50_000_000),
    weights=ScoringWeights(
        pvp_value=0.3,
        leverage=0.3,
        proximity=0.2,
        effort_decay=0.1,
        cost_decay=0.1,
        method_unlock=0.0,
    ),
)


def _item(item_id: str, numeric_id: int) -> Item:
    return Item(id=item_id, name=item_id, item_id=numeric_id, price_mode="live")


class TestReachability:
    """Only capabilities the roadmap weights, or reaches transitively, contribute."""

    def test_directly_weighted_capability_contributes_its_items(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690), "unrelated": _item("unrelated", 999)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690})

    def test_unreferenced_item_is_excluded_even_though_it_is_in_the_corpus(self) -> None:
        """The exit criterion: an item the corpus declares but no reachable capability,
        candidate or training method references must never appear in the scope."""
        content = Content(
            profile=_PROFILE,
            items={
                "voidwaker": _item("voidwaker", 27690),
                "never_referenced": _item("never_referenced", 999),
            },
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
        )

        result = scoped_item_ids(content, ["main"])
        assert 999 not in result
        assert result == frozenset({27690})

    def test_transitively_reachable_capability_contributes_too(self) -> None:
        """`deep` requires `capability: shallow` (§10.2's DAG) without the roadmap
        weighting `shallow` directly — its items must still be in scope."""
        content = Content(
            profile=_PROFILE,
            items={"ags": _item("ags", 11802), "robe": _item("robe", 4091)},
            capabilities={
                "shallow": Capability(
                    id="shallow", name="Shallow", requires=parse_requirement({"item": "robe"})
                ),
                "deep": Capability(
                    id="deep",
                    name="Deep",
                    requires=parse_requirement(
                        {"all_of": [{"capability": "shallow"}, {"item": "ags"}]}
                    ),
                ),
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"deep": 1.0})},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({11802, 4091})

    def test_a_roadmap_never_selected_contributes_nothing(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
        )

        assert scoped_item_ids(content, ["some_other_roadmap"]) == frozenset()

    def test_unknown_id_that_resolves_to_no_numeric_item_id_is_dropped_not_errored(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"static_only": Item(id="static_only", name="Static", price_mode="static")},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "static_only"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset()


class TestTrainingMethods:
    """A training method's own item requirement is in scope when its skill is
    referenced by a reachable capability — even though the capability's own
    requirement tree says nothing about that item."""

    def test_training_method_item_for_a_referenced_skill_is_included(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"staff": _item("staff", 4675)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"skill": {"magic": 90}})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            training_methods={
                "bursting": TrainingMethod(
                    id="bursting",
                    name="Bursting",
                    skill="magic",
                    xp_per_hour=100_000,
                    level_range=LevelRange(min=82, max=99),
                    requires=parse_requirement({"item": "staff"}),
                )
            },
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({4675})

    def test_training_method_for_an_unreferenced_skill_is_excluded(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"axe": _item("axe", 1351)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"skill": {"magic": 90}})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            training_methods={
                "woodcutting": TrainingMethod(
                    id="woodcutting",
                    name="Woodcutting",
                    skill="woodcutting",
                    xp_per_hour=50_000,
                    level_range=LevelRange(min=1, max=99),
                    requires=parse_requirement({"item": "axe"}),
                )
            },
        )

        assert scoped_item_ids(content, ["main"]) == frozenset()


def _candidate(candidate_id: str, advances: dict[str, float], item_id: str) -> Candidate:
    """A real `Candidate`, not a stand-in — its `advances` is a mapping, not a sequence."""
    return Candidate(
        id=candidate_id,
        name=candidate_id,
        kind=CandidateKind.ACQUISITION,
        advances=advances,
        completion=parse_requirement({"item": item_id}),
    )


class TestCandidateScope:
    """§8.3 — "the active roadmap's ... candidates", not every candidate declared."""

    def test_a_corpus_with_no_candidates_scopes_from_capabilities_alone(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690})

    def test_a_candidate_advancing_a_reachable_capability_contributes_its_items(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690), "brew": _item("brew", 6685)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            candidates={"buy_brew": _candidate("buy_brew", {"cap_a": 1.0}, "brew")},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690, 6685})

    def test_a_candidate_advancing_an_unreachable_capability_is_excluded(self) -> None:
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690), "unrelated": _item("unrelated", 999)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            candidates={"buy_unrelated": _candidate("buy_unrelated", {"cap_z": 1.0}, "unrelated")},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690})

    def test_a_candidate_advancing_nothing_is_excluded(self) -> None:
        """An empty `advances` map advances nothing, so it is in no roadmap's scope.
        `train_woodcutting` is the shipped corpus's own example of one."""
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690), "unrelated": _item("unrelated", 999)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"item": "voidwaker"})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            candidates={"buy_nothing": _candidate("buy_nothing", {}, "unrelated")},
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690})

    def test_a_candidate_gate_contributes_items_too(self) -> None:
        """`requires` names things that must be held before starting, which still cost gp."""
        content = Content(
            profile=_PROFILE,
            items={"voidwaker": _item("voidwaker", 27690), "brew": _item("brew", 6685)},
            capabilities={
                "cap_a": Capability(
                    id="cap_a", name="A", requires=parse_requirement({"skill": {"magic": 94}})
                )
            },
            roadmaps={"main": Roadmap(id="main", name="Main", capabilities={"cap_a": 1.0})},
            candidates={
                "buy_brew": Candidate(
                    id="buy_brew",
                    name="buy_brew",
                    kind=CandidateKind.ACQUISITION,
                    advances={"cap_a": 1.0},
                    requires=parse_requirement({"item": "voidwaker"}),
                    completion=parse_requirement({"item": "brew"}),
                )
            },
        )

        assert scoped_item_ids(content, ["main"]) == frozenset({27690, 6685})


class TestAgainstTheShippedCorpus:
    """The scoping rules, exercised against real content rather than constructed shapes."""

    def test_main_nh_scope_is_a_strict_subset_of_the_corpus_items(self) -> None:
        content = load_and_validate(Path(__file__).parents[3] / "content")
        all_numeric_ids = {
            item.item_id for item in content.items.values() if item.item_id is not None
        }
        scoped = scoped_item_ids(content, ["main_nh"])

        assert scoped
        assert scoped <= all_numeric_ids

    def test_an_unselected_roadmap_does_not_widen_the_scope(self) -> None:
        content = load_and_validate(Path(__file__).parents[3] / "content")
        assert scoped_item_ids(content, []) == frozenset()
