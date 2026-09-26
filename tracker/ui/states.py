"""Distinct UI states for observed account unlocks.

Unknown means there is no accepted observation. It is visually and structurally distinct
from locked, so missing facts cannot look like a confirmed unmet requirement.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from tracker.domain.types import UnlockState


class UiState(Enum):
    """The four observed unlock render states."""

    UNLOCKED = "unlocked"
    AVAILABLE = "available"
    LOCKED = "locked"
    UNKNOWN = "unknown"


#: One CSS class per state. Injective, and asserted to be so — the property that makes the
#: §15 selector-disjointness test meaningful rather than incidental.
STATE_CLASSES: Mapping[UiState, str] = {
    UiState.UNLOCKED: "state-unlocked",
    UiState.AVAILABLE: "state-available",
    UiState.LOCKED: "state-locked",
    UiState.UNKNOWN: "state-unknown",
}

#: The word shown to the user. ``unknown`` reads as an instruction because that is what it
#: is: §15 says unknown means *"sync RuneLite"*, and a bare "unknown" invites the reader to
#: supply their own meaning — which will be "no".
STATE_LABELS: Mapping[UiState, str] = {
    UiState.UNLOCKED: "unlocked",
    UiState.AVAILABLE: "available",
    UiState.LOCKED: "locked",
    UiState.UNKNOWN: "unknown — not yet observed",
}

#: §15's rendering table, plus the hatch that keeps ``unknown`` from reading as a colour on
#: the locked-to-unlocked scale.
#:
#: **Weight tracks urgency, not merely identity.** These were four solid pills of equal
#: loudness, and since ``locked`` is the resting state of almost everything in this
#: application, the loudest thing on a page was reliably the one state that asks for
#: nothing — five grey pills to one green. So ``available``, the only state that means *you
#: could do this now*, is the only filled badge; ``unlocked`` reads quietly because it is
#: finished; and ``locked`` is a bare outline, because a default should not shout.
#:
#: That is a change of emphasis and not of meaning: the classes remain one per state and
#: remain injective, so §15's guarantee is exactly as strong as it was.
#:
#: ``unknown`` keeps its hatch and gains a ``?``. It is deliberately not filled at all, so
#: it is distinguishable without colour vision and sits nowhere on the locked-to-unlocked
#: scale — and the glyph says, without relying on either colour or fill, that this is a
#: question rather than a result. The hatch stroke is a fixed mid-tone rather than a token,
#: because it has to stay visible against both the dark and the light ground.
STATE_CSS = """
.state-badge {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.08rem 0.5rem; border-radius: 9999px;
  font-family: var(--font-body);
  font-size: 0.6875rem; font-weight: 600; line-height: 1.5;
  border: 1px solid transparent; white-space: nowrap;
}
.state-unlocked  { background: transparent; color: var(--jade); border-color: var(--jade); }
.state-available { background: var(--amber); color: var(--amber-ink); border-color: var(--amber); }
.state-locked    { background: transparent; color: var(--ink-faint); border-color: var(--edge); }
.state-unknown {
  background: repeating-linear-gradient(
    45deg, transparent, transparent 4px,
    rgba(140, 128, 105, 0.55) 4px, rgba(140, 128, 105, 0.55) 5px);
  color: var(--ink);
  border: 1px dashed var(--ink-faint);
}
.state-unknown::before { content: "?"; font-weight: 700; }
"""


def ui_state_for_unlock(state: UnlockState) -> UiState:
    """§6.3's ``UnlockState`` as a render state.

    ``available`` keeps its own state rather than collapsing into ``locked``. §6.3 warns
    that the word reads as positive and that §9.1 resolves it to *unsatisfied*; the UI's
    job is to show that it is attainable-but-not-held, which is neither of the other two.
    """
    return UiState(state.value)


def state_props(state: UiState) -> str:
    """The NiceGUI ``.props()`` string carrying ``data-state``.

    Emitted on every status-bearing element, including ones whose visual treatment is
    obvious to a human, so that "which elements claim this state?" is a query rather than
    a reading of the source.
    """
    return f"data-state={state.value}"
