"""The four render states, and the one place their visual identities are decided (§15).

§15's hardest UI requirement is a *negative* one:

> Unknown must never render as locked. It means "sync RuneLite", not "go do this."

"Visually distinct" is a human judgment and cannot be asserted. So the distinction is
carried by data instead: every status-bearing element in the UI emits
``data-state="unknown|locked|available|unlocked"`` and exactly one class from
:data:`STATE_CLASSES`, and the mapping is injective by construction. A test can then assert
that the ``unknown`` and ``locked`` selectors are disjoint — which is what §15 actually
means — rather than that two colours look different.

Keeping the mapping here, rather than inline at each call site, is what makes that true of
the *whole* UI rather than of whichever view was written most recently. Capabilities carry
three states (§4.4's ``status`` has no ``available``) and unlocks carry four (§6.3); both
draw from this vocabulary, so the guarantee holds across views that share no code.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from tracker.domain.types import Status, UnlockState


class UiState(Enum):
    """The render vocabulary — the union of §6.3's four unlock states.

    Deliberately its own type rather than a reuse of :class:`~tracker.domain.types.Status`
    or :class:`~tracker.domain.types.UnlockState`. Those are *domain* enums with different
    members (``Status`` has no ``available``), and a UI that switched on either directly
    would need two rendering paths for one visual language — which is how the two would
    drift until ``unknown`` picked up ``locked``'s treatment in one of them.
    """

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
#: the locked-to-unlocked scale. The other three are solid fills; ``unknown`` is
#: deliberately not filled at all, so it is distinguishable without colour vision and does
#: not sit anywhere on that scale.
STATE_CSS = """
.state-badge {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.1rem 0.55rem; border-radius: 9999px;
  font-size: 0.75rem; font-weight: 600; line-height: 1.4;
  border: 1px solid transparent; white-space: nowrap;
}
.state-unlocked  { background: #16a34a; color: #ffffff; }
.state-available { background: #eab308; color: #1f2937; }
.state-locked    { background: #9ca3af; color: #ffffff; }
.state-unknown {
  background: repeating-linear-gradient(
    45deg, transparent, transparent 4px, #94a3b8 4px, #94a3b8 5px);
  color: #1f2937;
  border: 1px dashed #475569;
}
"""


def ui_state_for_status(status: Status) -> UiState:
    """§4.4's ``status`` as a render state.

    Total by construction: ``Status`` has exactly three members and each names a member of
    :class:`UiState`. There is no fallback branch, because a fallback is how ``unknown``
    would one day arrive at ``locked``.
    """
    return UiState(status.value)


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
