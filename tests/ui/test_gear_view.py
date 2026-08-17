"""§23.5's page, at the layer where its one hard rule can be asserted.

The rule is §15's: an unknown rung must not render as one known to be absent. Testing that
through a browser would assert about CSS; testing it here asserts about the *state* the badge
is drawn from, which is where the mistake would actually be made.

These run against the real seed corpus rather than a hand-built one, so they also catch the
case where the shipped ladders stop producing a melee weapon slot at all.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from tracker.content.loader import Content
from tracker.domain.types import Tri
from tracker.gear.setup import GearPick, SetupSlot
from tracker.ui import read_model
from tracker.ui.gear import slot_labels
from tracker.ui.states import STATE_LABELS, UiState
from tracker.ui.view_model import GearPickRow, GearSlotRow, GearView

#: The three words ownership is allowed to use. Deliberately a closed set: the bug this
#: guards was ownership silently borrowing the *fit* vocabulary, and a new word appearing
#: here should be a decision rather than a fallback.
HELD_WORDS = {"held", "not held", "not yet seen"}


def _weapon(view: GearView) -> GearSlotRow:
    return next(slot for style in view.styles if style.style == "melee" for slot in style.slots)


def _picks(view: GearView) -> list[GearPickRow]:
    return [
        pick
        for style in view.styles
        for slot in style.slots
        for pick in (slot.recommended, slot.best_held, slot.next_rung, *slot.aspirational)
        if pick is not None
    ]


class TestNoPlayer:
    def test_it_renders_nothing_rather_than_an_empty_account(
        self, session: Session, content: Content
    ) -> None:
        """An empty page is right; an account reported as owning nothing would not be."""
        view = read_model.gear_view(session, None, content)
        assert view.styles == ()
        assert view.scan_note is None


class TestHonesty:
    def test_unknown_ownership_is_never_drawn_as_known_absent(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        view = read_model.gear_view(session, player_id, content)
        if view.fully_scanned:
            return  # The rule only bites while something has never been looked in.

        for style in view.styles:
            for slot in style.slots:
                for pick in (slot.recommended, slot.best_held, slot.next_rung):
                    if pick is not None and pick.held_state is UiState.UNKNOWN:
                        assert pick.held_state is not UiState.LOCKED

    def test_the_page_names_the_containers_nobody_opened(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        """The caveat scopes the whole page, so it sits on the view rather than on a row."""
        view = read_model.gear_view(session, player_id, content)
        if not view.fully_scanned:
            assert view.scan_note is not None
            assert "Never scanned" in view.scan_note


class TestRows:
    def test_every_style_renders_and_in_a_fixed_order(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        view = read_model.gear_view(session, player_id, content)
        assert [style.style for style in view.styles] == ["melee", "ranged", "magic"]
        assert slot_labels(view)

    def test_an_uncached_price_says_so_rather_than_showing_zero(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        """§8.3: absent is absent. A zero here would read as free."""
        view = read_model.gear_view(session, player_id, content)
        for style in view.styles:
            for slot in style.slots:
                for pick in (slot.recommended, slot.best_held, slot.next_rung):
                    if pick is not None:
                        assert pick.price_label != "0 gp"

    def test_a_blocked_rung_names_the_requirement_not_just_the_block(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        """*"Needs 60 Attack"* is actionable; a bare lock icon is not."""
        view = read_model.gear_view(session, player_id, content)
        blocked = [
            slot.next_rung
            for style in view.styles
            for slot in style.slots
            if slot.next_rung is not None and slot.next_rung.fit_state is UiState.LOCKED
        ]
        for pick in blocked:
            assert pick.note is not None and pick.note.startswith("Needs ")


class TestTheTwoQuestionsAreWordedApart:
    """Ownership and fit share a state vocabulary; they must not share a *word* one.

    The regression: the page badged ``held_state`` with no label override, so it fell back
    to :data:`~tracker.ui.states.STATE_LABELS` — ``unlocked | locked`` — and a rung the
    account could wear but did not own rendered as "locked" directly under the heading
    *best you can equip*.
    """

    def test_ownership_never_borrows_the_lock_scales_words(
        self, session: Session, player_id: int, content: Content
    ) -> None:
        view = read_model.gear_view(session, player_id, content)
        assert _picks(view), "no rungs rendered, so this asserts nothing"
        for pick in _picks(view):
            assert pick.held_label in HELD_WORDS
            assert pick.held_label != STATE_LABELS[pick.held_state]

    def test_a_wearable_rung_you_do_not_own_is_not_called_locked(self) -> None:
        """The screenshot's case, stated directly: Rune boots, met but unowned."""
        row = read_model._gear_pick_row(
            GearPick(
                item_id="rune_boots",
                name="Rune boots",
                tier=2,
                fit=Tri.SATISFIED,
                held=Tri.UNSATISFIED,
            ),
            5,
        )
        assert row is not None
        assert row.held_label == "not held"
        # Satisfied fit is implied by every layer that can carry it, so no second badge.
        assert row.fit_label == ""

    def test_an_unseen_rung_is_worded_as_unseen_rather_than_absent(self) -> None:
        """§4.5 reaching the badge: unknown is not a quieter way of saying no."""
        row = read_model._gear_pick_row(
            GearPick(
                item_id="dragon_boots",
                name="Dragon boots",
                tier=3,
                fit=Tri.SATISFIED,
                held=Tri.UNKNOWN,
            ),
            5,
        )
        assert row is not None
        assert row.held_state is UiState.UNKNOWN
        assert row.held_label == "not yet seen"

    def test_an_unwearable_rung_carries_a_fit_badge_too(self) -> None:
        row = read_model._gear_pick_row(
            GearPick(
                item_id="dragon_boots",
                name="Dragon boots",
                tier=3,
                fit=Tri.UNSATISFIED,
                held=Tri.UNSATISFIED,
            ),
            5,
        )
        assert row is not None
        assert row.fit_label == "cannot equip yet"
        assert row.fit_state is UiState.LOCKED


class TestOneRungIsDrawnOnce:
    """The screenshot's other defect: Leather gloves in both layers of one slot."""

    def _slot(self, recommended: GearPick | None, best_held: GearPick | None) -> GearSlotRow:
        return read_model._gear_slot_row(
            SetupSlot(
                style="melee",
                slot="hands",
                ladder_size=3,
                recommended=recommended,
                best_held=best_held,
            )
        )

    def test_the_same_rung_in_both_layers_is_flagged(self) -> None:
        gloves = GearPick(
            item_id="leather_gloves",
            name="Leather gloves",
            tier=1,
            fit=Tri.SATISFIED,
            held=Tri.SATISFIED,
        )
        assert self._slot(gloves, gloves).held_is_recommended

    def test_different_rungs_keep_both_layers(self) -> None:
        """The disagreement is the case §23 exists to show — it must survive the collapse."""
        row = self._slot(
            GearPick(
                item_id="rune_boots",
                name="Rune boots",
                tier=2,
                fit=Tri.SATISFIED,
                held=Tri.UNSATISFIED,
            ),
            GearPick(
                item_id="leather_boots",
                name="Leather boots",
                tier=1,
                fit=Tri.SATISFIED,
                held=Tri.SATISFIED,
            ),
        )
        assert not row.held_is_recommended

    def test_a_missing_layer_is_never_a_match(self) -> None:
        assert not self._slot(None, None).held_is_recommended


class TestAcquisitionIsAThirdQuestionAndNotAThirdBadge:
    """§23.5. *How is this obtained* is as real as fit and ownership, and is worded apart.

    It gets a sentence rather than a badge for a layout reason with teeth: two badges on the
    name line already wrapped on a phone once, and the fix was to move the second one down
    beside the sentence explaining it.
    """

    def test_an_untradeable_rung_names_its_content_and_shows_no_price(self) -> None:
        row = read_model._gear_pick_row(
            GearPick(
                item_id="infernal_cape",
                name="Infernal cape",
                tier=5,
                fit=Tri.SATISFIED,
                held=Tri.UNSATISFIED,
                obtainable=Tri.UNSATISFIED,
                acquired_from="the Inferno",
                price_gp=999_000_000,
            ),
            5,
        )

        assert row is not None
        assert row.acquire_label == "Earn it — the Inferno. It cannot be bought."
        # The corpus really does cache a figure against an untradeable piece — the Avernic
        # defender's is its hilt — and a gp label beside it invites a purchase nobody can make.
        assert row.price_label == ""

    def test_a_tradeable_rung_carries_no_acquisition_sentence(self) -> None:
        """An answer of *yes* earns no space, on the rule ``fit_label`` already follows."""
        row = read_model._gear_pick_row(
            GearPick(
                item_id="black_cape",
                name="Black cape",
                tier=1,
                fit=Tri.SATISFIED,
                held=Tri.UNSATISFIED,
                obtainable=Tri.SATISFIED,
                price_gp=1_000,
            ),
            5,
        )

        assert row is not None
        assert row.acquire_label == ""
        assert row.price_label == "1K gp"

    def test_an_unknown_acquisition_says_so_rather_than_going_quiet(self) -> None:
        """It does not demote, so the only place the uncertainty can live is the wording."""
        row = read_model._gear_pick_row(
            GearPick(
                item_id="eye_of_ayak",
                name="Eye of ayak",
                tier=16,
                fit=Tri.SATISFIED,
                held=Tri.UNSATISFIED,
                obtainable=Tri.UNKNOWN,
            ),
            17,
        )

        assert row is not None
        assert row.acquire_label == "The tracker has not recorded how this is obtained."

    def test_the_earn_role_never_borrows_the_recommendation_s_emphasis(self) -> None:
        """Gold means *wear this*, and an earn target is the one rung spending cannot reach.

        Asserted on the roles rather than on the CSS: the stylesheet keys off the role, so a
        rung that never carries ``best`` can never be painted as the recommendation.
        """
        from tracker.ui.gear import rungs

        earn = GearPickRow(
            name="Fire cape",
            rung_label="rung 4 of 5",
            held_state=UiState.LOCKED,
            fit_state=UiState.UNLOCKED,
            price_label="",
            held_label="not held",
            acquire_label="Earn it — the Fight Caves. It cannot be bought.",
            tier=4,
        )
        recommended = GearPickRow(
            name="Black cape",
            rung_label="rung 1 of 5",
            held_state=UiState.LOCKED,
            fit_state=UiState.UNLOCKED,
            price_label="1,000 gp",
            held_label="not held",
            tier=1,
        )
        slot = GearSlotRow(
            slot="cape",
            ladder_label="5 rungs",
            recommended=recommended,
            best_held=None,
            next_rung=None,
            earn=earn,
        )

        roles = {rung.pick.name: rung.roles for rung in rungs(slot)}
        assert roles["Fire cape"] == ["earn it"]
        assert "best you can equip" not in roles["Fire cape"]
        assert roles["Black cape"] == ["best you can equip"]


class TestTheLadderSaysWhatItSkips:
    """A bounded drawing that does not admit it is bounded reads as a complete one.

    The page draws only rungs that carry a role, which is the right bound — nobody reads a
    twenty-three rung ammunition ladder top to bottom. Doing it silently produced two separate
    reports of the same confusion: *"why is there nothing between rung 1 and rung 5"* and
    *"is Mooleta missing"*. In both cases the ladder was complete and the drawing was not.
    """

    @staticmethod
    def _slot(**kwargs: object) -> GearSlotRow:
        def row(name: str, tier: int) -> GearPickRow:
            return GearPickRow(
                name=name,
                rung_label=f"rung {tier} of 5",
                held_state=UiState.LOCKED,
                fit_state=UiState.UNLOCKED,
                price_label="",
                held_label="not held",
                tier=tier,
            )

        defaults: dict[str, object] = {
            "slot": "neck",
            "ladder_label": "5 rungs",
            "recommended": row("Amulet of blood fury", 5),
            "best_held": row("Amulet of strength", 1),
            "next_rung": None,
            "ladder": (
                (1, "Amulet of strength"),
                (2, "Amulet of fury"),
                (3, "Amulet of torture"),
                (4, "Amulet of rancour"),
                (5, "Amulet of blood fury"),
            ),
        }
        defaults.update(kwargs)
        return GearSlotRow(**defaults)  # type: ignore[arg-type]

    def test_a_run_of_undrawn_rungs_becomes_one_named_gap(self) -> None:
        """The reported neck slot, exactly: rung 5 recommended, rung 1 held, nothing between."""
        from tracker.ui.gear import _Gap, ladder_rows

        rows = ladder_rows(self._slot())
        gaps = [row for row in rows if isinstance(row, _Gap)]

        assert len(gaps) == 1
        assert gaps[0].tiers == (4, 3, 2)
        assert "3 rungs not shown" in gaps[0].label
        # Named, not merely counted — a count cannot answer "is the one I want in there?".
        assert "Amulet of fury" in gaps[0].label

    def test_a_skipped_rung_is_named_even_when_the_gap_is_long(self) -> None:
        """The Mooleta case. It sits fourth in a run of seven, so a three-name truncation
        would have hidden the very rung that prompted the question."""
        from tracker.ui.gear import _Gap, ladder_rows

        names = [
            "Bronze defender",
            "Iron defender",
            "Steel defender",
            "Mooleta",
            "Black defender",
            "Mithril defender",
            "Adamant defender",
            "Antler guard",
        ]
        recommended = GearPickRow(
            name="Antler guard",
            rung_label="rung 8 of 8",
            held_state=UiState.LOCKED,
            fit_state=UiState.UNLOCKED,
            price_label="",
            held_label="not held",
            tier=8,
        )
        slot = self._slot(
            slot="shield",
            ladder_label="8 rungs",
            recommended=recommended,
            best_held=None,
            ladder=tuple(enumerate(names, start=1)),
        )

        gap = next(row for row in ladder_rows(slot) if isinstance(row, _Gap))
        assert "Mooleta" in gap.label

    def test_a_ladder_with_no_gaps_gets_no_markers(self) -> None:
        """The marker is a statement about an omission, so it must not appear without one."""
        from tracker.ui.gear import _Gap, ladder_rows

        slot = self._slot(
            ladder_label="1 rung",
            recommended=GearPickRow(
                name="Peaceful blessing",
                rung_label="rung 1 of 1",
                held_state=UiState.LOCKED,
                fit_state=UiState.UNLOCKED,
                price_label="",
                held_label="not held",
                tier=1,
            ),
            best_held=None,
            ladder=((1, "Peaceful blessing"),),
        )

        assert not [row for row in ladder_rows(slot) if isinstance(row, _Gap)]

    def test_a_held_rung_below_the_recommendation_is_drawn_rather_than_skipped(self) -> None:
        """``also_held`` was computed by §23.4 and discarded here, so a spare set in the bank
        could go unmentioned on the page whose whole job is to say what the account has."""
        from tracker.ui.gear import rungs

        spare = GearPickRow(
            name="Amulet of fury",
            rung_label="rung 2 of 5",
            held_state=UiState.UNLOCKED,
            fit_state=UiState.UNLOCKED,
            price_label="",
            held_label="held",
            tier=2,
        )
        drawn = rungs(self._slot(also_held=(spare,)))

        roles = {rung.pick.name: rung.roles for rung in drawn}
        assert roles["Amulet of fury"] == ["also holding"]
