"""§6.5's phrasing rule, implemented once so it cannot be paraphrased twice.

> The UI must say *"last saw your bank 3 weeks ago"* rather than *"you don't have a
> Voidwaker."*

This is §4.5 surfacing at the presentation layer: when we looked is a different fact from
what is true, and a sentence that reports the second from the first is a claim the data does
not support. The cases §6.5 distinguishes each get their own sentence, and the never-scanned
case gets one that contains no claim about ownership at all.

Pure string construction, no NiceGUI import — so the wording is testable without a browser,
which is the only way a phrasing rule stays enforced.
"""

from __future__ import annotations

from datetime import datetime

from tracker.domain.types import Container

#: Plain-language names for §6.5's containers. "your bank" rather than "bank" because the
#: sentences below read as speech, and §6.5 quotes one of them verbatim.
CONTAINER_NAMES = {
    Container.BANK: "your bank",
    Container.INVENTORY: "your inventory",
    Container.EQUIPMENT: "your equipment",
}


def humanize_age(then: datetime, now: datetime) -> str:
    """A coarse, non-committal age: "3 weeks ago", "just now".

    Coarse on purpose. The precision of ``scanned_at`` is real, but rendering it invites
    the reader to treat a 14-day-old scan as meaningfully better than a 15-day-old one.
    Future timestamps — a clock skew between the plugin's host and this one — render as
    "just now" rather than as a negative age.
    """
    seconds = (now - then).total_seconds()
    if seconds < 60:
        return "just now"

    for size, unit in (
        (31_536_000.0, "year"),
        (2_592_000.0, "month"),
        (604_800.0, "week"),
        (86_400.0, "day"),
        (3_600.0, "hour"),
        (60.0, "minute"),
    ):
        count = int(seconds // size)
        if count >= 1:
            return f"{count} {unit}{'s' if count > 1 else ''} ago"

    return "just now"  # pragma: no cover — the <60s guard above already covers this


def scan_note(container: Container, scanned_at: datetime | None, now: datetime) -> str:
    """The §6.5 sentence for one container's staleness.

    ``None`` is the case the whole model exists for: no scan has ever covered this
    container, so nothing at all is known about what is in it. The sentence therefore
    reports only the gap in our observation and asks for a sync — it does not say the item
    is absent, because that is precisely the inference §6.5 forbids.
    """
    name = CONTAINER_NAMES[container]
    if scanned_at is None:
        return f"We have never seen {name} — open it in-game with RuneLite running."
    return f"Last saw {name} {humanize_age(scanned_at, now)}."


def ownership_note(
    item_name: str, container: Container, scanned_at: datetime | None, now: datetime
) -> str:
    """Why an item requirement is unmet, said in terms of observation rather than ownership.

    Both branches name the *scan*, never the item's absence. With a scan on record the
    honest statement is still about the look, not the conclusion: the scan is what we have,
    and its age is what the reader needs in order to weigh it.
    """
    name = CONTAINER_NAMES[container]
    if scanned_at is None:
        return f"{item_name}: we have never seen {name}, so we cannot tell."
    return f"{item_name}: not seen when we last looked at {name}, {humanize_age(scanned_at, now)}."
