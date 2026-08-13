"""The §10.2 requirement grammar: parsing, round-tripping, and its canonical trap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tracker.content.errors import RequirementSyntaxError
from tracker.content.requirements import (
    LEAF_TYPES,
    AccountTypeLeaf,
    AllOf,
    AnyOf,
    AtLeast,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MembersLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    SkillLeaf,
    UnlockLeaf,
    iter_leaves,
    iter_nodes,
    parse,
)
from tracker.content.yaml_source import load_yaml_file

# The §4.1 / §10.2 worked example, exercising every construct that appears in real content.
ICE_BARRAGE = {
    "all_of": [
        {"skill": {"magic": 94}},
        {"unlock": "ancient_magicks"},
        {"any_of": [{"item": "mystic_robe_top"}, {"item": "ahrims_robetop"}]},
    ]
}


def write_yaml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "capability.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestLeaves:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ({"skill": {"magic": 94}}, SkillLeaf(skill="magic", level=94)),
            ({"unlock": "ancient_magicks"}, UnlockLeaf(key="ancient_magicks")),
            ({"unlock": "spellbook_ancient"}, UnlockLeaf(key="spellbook_ancient")),
            ({"quest": "desert_treasure_i"}, QuestLeaf(quest_id="desert_treasure_i")),
            ({"item": "voidwaker"}, ItemLeaf(item_id="voidwaker")),
            ({"milestone": "freeze_logging"}, MilestoneLeaf(key="freeze_logging")),
            ({"capability": "ice_barrage_nh"}, CapabilityLeaf(capability_id="ice_barrage_nh")),
            ({"combat_level": 100}, CombatLevelLeaf(level=100)),
            ({"quest_points": 150}, QuestPointsLeaf(points=150)),
            ({"account_type": "ironman"}, AccountTypeLeaf(account_type="ironman")),
            ({"members": True}, MembersLeaf(members=True)),
        ],
    )
    def test_every_leaf_type_parses(self, raw: dict[str, Any], expected: Any) -> None:
        assert parse(raw) == expected

    def test_every_declared_leaf_type_is_covered(self) -> None:
        """§9.1 requires every leaf to resolve; none may be silently unimplemented.

        Pinned as an exact set rather than a subset, so adding a leaf is a decision someone
        has to make here on purpose. §10.8 allows a new leaf type as a legitimate code
        change — ``account_type`` and ``members`` are Step 9's, and they are listed because
        an ironman is a constraint an account was created under, not an ``unlock:`` key it
        gained (§6.3).
        """
        assert LEAF_TYPES == {
            "skill",
            "unlock",
            "quest",
            "item",
            "milestone",
            "capability",
            "combat_level",
            "quest_points",
            "account_type",
            "members",
        }

    def test_nodes_are_frozen(self) -> None:
        leaf = parse({"unlock": "rigour"})
        with pytest.raises(ValueError, match="frozen"):
            leaf.key = "augury"  # type: ignore[misc,union-attr]


class TestCombinators:
    def test_all_of(self) -> None:
        node = parse({"all_of": [{"unlock": "rigour"}, {"unlock": "augury"}]})
        assert isinstance(node, AllOf)
        assert len(node.children) == 2

    def test_any_of(self) -> None:
        node = parse({"any_of": [{"item": "voidwaker"}, {"item": "armadyl_godsword"}]})
        assert isinstance(node, AnyOf)

    def test_not(self) -> None:
        node = parse({"not": {"unlock": "rigour"}})
        assert isinstance(node, Not)
        assert node.child == UnlockLeaf(key="rigour")

    def test_at_least(self) -> None:
        node = parse({"at_least": {"n": 2, "of": [{"item": "a"}, {"item": "b"}, {"item": "c"}]}})
        assert isinstance(node, AtLeast)
        assert node.n == 2
        assert len(node.of) == 3

    def test_at_least_rejects_an_unreachable_n(self) -> None:
        """n > len(of) can never be satisfied — a content bug, not a runtime condition."""
        with pytest.raises(RequirementSyntaxError, match="never be satisfied"):
            parse({"at_least": {"n": 3, "of": [{"item": "a"}, {"item": "b"}]}})

    def test_nesting_is_arbitrary(self) -> None:
        node = parse(
            {
                "not": {
                    "any_of": [
                        {"all_of": [{"skill": {"magic": 94}}]},
                        {"at_least": {"n": 1, "of": [{"item": "voidwaker"}]}},
                    ]
                }
            }
        )
        assert isinstance(node, Not)


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw",
        [
            ICE_BARRAGE,
            {"not": {"unlock": "rigour"}},
            {"at_least": {"n": 2, "of": [{"item": "a"}, {"item": "b"}]}},
            {"all_of": [{"combat_level": 100}, {"quest_points": 150}]},
            {"any_of": [{"milestone": "m"}, {"capability": "c"}, {"quest": "q"}]},
        ],
    )
    def test_parse_render_parse_is_stable(self, raw: dict[str, Any]) -> None:
        """to_yaml() must produce something parse() accepts back to an equal tree."""
        once = parse(raw)
        assert once.to_yaml() == raw
        assert parse(once.to_yaml()) == once


class TestWalking:
    def test_iter_nodes_visits_parents_before_children(self) -> None:
        nodes = list(iter_nodes(parse(ICE_BARRAGE)))
        assert nodes[0].type == "all_of"
        assert [node.type for node in nodes] == [
            "all_of",
            "skill",
            "unlock",
            "any_of",
            "item",
            "item",
        ]

    def test_iter_leaves_counts_the_unlock_fraction_denominator(self) -> None:
        """§6.9 — unlock_fraction divides by the number of leaves, not nodes."""
        leaves = list(iter_leaves(parse(ICE_BARRAGE)))
        assert len(leaves) == 4
        assert {leaf.type for leaf in leaves} == {"skill", "unlock", "item"}


class TestTheMissingSpaceTrap:
    """§10.2's named trap. The v0.1 draft shipped this bug twice."""

    def test_string_payload_on_a_skill_leaf_is_rejected(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="space after the colon"):
            parse({"skill": "magic:94"})

    def test_yaml_flow_mapping_without_a_space_is_rejected(self, tmp_path: Path) -> None:
        """`{magic:94}` parses as the key 'magic:94' with a null value, not a mapping."""
        path = write_yaml(
            tmp_path,
            "id: ice_barrage\nrequires:\n  all_of:\n    - skill: {magic:94}\n",
        )
        document = load_yaml_file(path)

        with pytest.raises(RequirementSyntaxError) as caught:
            parse(document["requires"], file=path)

        assert "space after the colon" in str(caught.value)

    def test_the_error_names_the_file_and_the_line(self, tmp_path: Path) -> None:
        """§10.7 exists so this fails at validation time with a usable message."""
        path = write_yaml(
            tmp_path,
            "id: ice_barrage\n"
            "requires:\n"
            "  all_of:\n"
            "    - unlock: ancient_magicks\n"
            "    - skill: {magic:94}\n",
        )
        document = load_yaml_file(path)

        with pytest.raises(RequirementSyntaxError) as caught:
            parse(document["requires"], file=path)

        message = str(caught.value)
        assert str(path) in message
        assert ":5:" in message, f"expected line 5 in {message!r}"
        assert "all_of[1].skill" in message

    def test_block_scalar_without_a_space_is_rejected(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path, "requires:\n  skill: magic:94\n")
        document = load_yaml_file(path)

        with pytest.raises(RequirementSyntaxError, match="space after the colon"):
            parse(document["requires"], file=path)

    def test_a_bare_key_with_a_colon_is_rejected(self, tmp_path: Path) -> None:
        """`- unlock:ancient_magicks` becomes one key with a null value."""
        path = write_yaml(tmp_path, "requires:\n  all_of:\n    - {unlock:ancient_magicks}\n")
        document = load_yaml_file(path)

        with pytest.raises(RequirementSyntaxError, match="space after the colon"):
            parse(document["requires"], file=path)


class TestOtherSyntaxErrors:
    def test_unknown_requirement_type(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="unknown requirement type 'skll'"):
            parse({"skll": {"magic": 94}})

    def test_multi_key_node_suggests_all_of(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="single-key mapping"):
            parse({"unlock": "rigour", "item": "voidwaker"})

    def test_skill_leaf_with_two_skills_is_rejected(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="exactly one skill"):
            parse({"skill": {"magic": 94, "defence": 75}})

    def test_skill_level_must_be_an_integer(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="integer level"):
            parse({"skill": {"magic": "94"}})

    def test_skill_level_out_of_range_is_rejected(self) -> None:
        with pytest.raises(RequirementSyntaxError):
            parse({"skill": {"magic": 120}})

    def test_string_leaf_rejects_a_number(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="names one id as a string"):
            parse({"unlock": 42})

    def test_integer_leaf_rejects_a_string(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="integer target"):
            parse({"combat_level": "100"})

    def test_boolean_is_not_an_integer_level(self) -> None:
        """`skill: {magic: yes}` parses as True in YAML; bool is not a level."""
        with pytest.raises(RequirementSyntaxError, match="integer level"):
            parse({"skill": {"magic": True}})

    def test_empty_all_of_is_rejected(self) -> None:
        with pytest.raises(RequirementSyntaxError):
            parse({"all_of": []})

    def test_combinator_needs_a_list(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="expected a list"):
            parse({"all_of": {"unlock": "rigour"}})

    def test_at_least_missing_of(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="missing of"):
            parse({"at_least": {"n": 2}})

    def test_a_bare_string_requirement_is_rejected(self) -> None:
        with pytest.raises(RequirementSyntaxError, match="expected a requirement mapping"):
            parse("ancient_magicks")

    def test_nested_error_reports_its_path(self) -> None:
        with pytest.raises(RequirementSyntaxError) as caught:
            parse({"all_of": [{"unlock": "rigour"}, {"any_of": [{"unlock": 7}]}]})
        assert "all_of[1].any_of[0].unlock" in str(caught.value)
