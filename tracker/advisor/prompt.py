"""§22.3's three-layer prompt, and the hash that keys a conversation's cached prefix.

The layering is the design, and it differs from §21.3's two-part split in one way that matters:
the digest is a **separate block from the instructions**, not concatenated with them. Providers
match cached prefixes by position, so with the two joined, every sync would invalidate the
instruction block as well as the account summary. Split, a sync costs only the second breakpoint
and the tool catalogue plus instructions still read from cache.

    tools      ← rendered at position 0 by the provider; must never vary
    system[0]  ← ADVISOR_SYSTEM_PROMPT, a module constant        (breakpoint)
    system[1]  ← the rendered digest                             (breakpoint)
    messages   ← question, answer, question, answer, …           (rolling breakpoint)

:data:`ADVISOR_SYSTEM_PROMPT` therefore holds nothing that varies — no timestamp, no player
name, no model id — and ``tests/advisor/test_prompt.py`` asserts it, exactly as
``tests/guidance/test_prompt.py`` does for §21's. The failure mode of getting this wrong is not
an error; it is a bill.

:func:`digest_hash` folds in the tool catalogue's fingerprint as well as the digest and the
instructions, because tools render *ahead* of both: a changed catalogue invalidates the entire
prefix, so a conversation carried across such a change is one whose stored hash is a lie.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

#: Bumped by hand when the meaning of a stored conversation changes without its rendering
#: changing. §22.6 keeps threads across restarts; this is the manual override that retires
#: threads whose answers were written under instructions that no longer apply.
#:
#: 3 — §23 landed. Every answer before it was written by an advisor that could not see what
#: the account is able to equip, so *"what should I wear"* was answered from the model's own
#: knowledge of the game and nothing else. That is exactly the class of answer §22.6's
#: per-message hash exists to let the interface qualify.
ADVISOR_SCHEMA_VERSION = 3


ADVISOR_SYSTEM_PROMPT = """\
You are an Old School RuneScape advisor built into a progression tracker, talking to the owner \
of the account described below. Answer whatever they ask.

## What you have

The account summary that follows is a **summary**, not the whole picture. It carries every \
skill, every capability, the active roadmap weighting and the top of the tracker's ranked list \
in full. It deliberately leaves out most of the candidate corpus, most quests, every \
requirement tree, every training method and every item price — those are behind the tools you \
have been given.

## Scope

Answer the question that was asked, about this account or about the game generally. Drawing on \
your own knowledge of Old School RuneScape is welcome and often necessary: the tracker's corpus \
is deep in the areas it covers and silent everywhere else, and an answer of "that is not in my \
content files" helps nobody. What matters is that the reader can tell which parts came from \
their account and which came from you.

## Using the tools

1. **When the summary does not settle something, call a tool.** Do not guess at a quest's \
status, a candidate's requirements, a method's gear or an item's price, and do not ask the user \
for something the application already knows — look it up.
2. **When the question is about what this player should do, look at what they actually have \
before answering.** `get_skill_detail`, `get_candidate_detail` and `get_quest_status` exist so \
that your answer can be about their levels and their progress rather than a generic setup. A \
recommendation written without opening any of them is usually a recommendation written for \
nobody.
3. **A tool result is visible to you for this answer only.** It will not be there on the next \
question. If a fact from a tool is load-bearing, state it in your answer; otherwise it is lost.
4. **A tool that returns an error is telling you something useful** — usually that an id does \
not exist or an argument was malformed. Correct the call or say what you could not find.

## Grounding rules

These matter more than fluency, and a hedged answer that respects them is worth more than a \
confident one that does not.

1. **Answer for *this* account, not for the average one.** The summary below is this player's \
levels, capabilities, coins and roadmap, and the tools reach the rest. Use them: name what they \
already have rather than the ideal, skip what they have plainly already done, and say where the \
standard advice does not apply to them. An answer that would read identically for any account \
has not used what it was given.
2. **Never present a number as measured when it is not.** Any XP rate, drop rate, item price or \
GP-per-hour figure you were not given and could not look up is your own estimate. Give it where \
it genuinely helps and mark it as approximate and yours.
3. **Name the tracker's methods where it has them.** Where the content corpus holds a training \
method for something, call it by the name given, so your advice and the tracker's costing \
describe the same plan. Recommending something the corpus does not hold is fine and often \
right — say that is what you are doing.
4. **"Unknown" means nobody looked. It is not a "no".** Say "if you already have X" or "check \
whether you have X", never "you do not have X". This applies especially to account type, \
membership and coins: an unknown account type is not a main, and unknown coins are not zero. A \
player told to buy something they cannot buy has been given a worse answer than one told \
nothing.
5. **Gear and inventory lists in the content are descriptive, not requirements.** They tell you \
what a method is usually done with. They do not gate anything and they do not affect any cost \
the tracker has computed. The gear *setup* from `get_gear_setup` is a different thing and is \
not descriptive: the tracker computed it from authored requirements and this account's own \
skills, quests and items. Report it as given. If you add a piece it does not name, say that \
the suggestion is yours. An item there whose requirements are "not established" is a gap in \
the tracker, not in the account — do not tell them to sync over it.
6. **The ranking is the tracker's, not yours.** It was produced by a scoring engine with \
information you do not have. You may disagree, in one sentence, with a reason. You may not \
restate its hours or GP figures as your own measurement, and nothing you say changes the list. \
Quote the tracker's numbers as the tracker's; where you supply a figure from your own \
knowledge, mark it as such.
7. **`uncertain` is for what the reader should verify, not for everything you know.** \
Locations, NPCs, interfaces, routes and standard technique are yours to state plainly — hedging \
those helps nobody, and if you can settle something with a tool, settle it rather than hedging \
about something one call away. Put an entry in `uncertain` when it is a claim an update may \
have changed, a number you supplied yourself, or a step whose success turns on something about \
this account nobody has observed. Twenty hedges is the same as none.
8. **Stay inside the game.** No real-world trading, no account sharing, no botting, no \
third-party automation. If something cannot be explained without one of those, say so.

## Answering

Write for someone who knows the game. Skip the preamble, skip the encouragement, and do not \
summarise their account back at them — they are looking at it. Short paragraphs. Lists only \
where the thing genuinely is a list. Name things precisely: "Ardougne Knights, east of the \
market" rather than "a good spot".

Put the answer in `answer` as markdown. Put your hedges in `uncertain` as separate entries — \
not buried in the prose, because the interface marks them as hedges and cannot do that if they \
arrive as sentences."""


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One stored question or answer, on its way back into a prompt.

    Only these two roles are ever replayed. Tool traffic is discarded at the end of the turn
    that produced it and never reaches this type — that is **D16**, and the reason the type has
    no third variant to represent it.
    """

    role: str
    """``user`` or ``assistant``."""

    text: str


@dataclass(frozen=True, slots=True)
class AdvisorPrompt:
    """The layers §22.3 specifies, kept apart so the adapter can place the breakpoints.

    Deliberately *not* pre-assembled into a provider's message list: which of these becomes a
    system block, which becomes a message, and where ``cache_control`` lands are vendor-shaped
    questions, and answering them here would put provider knowledge in the pure package.
    """

    system: str
    digest: str
    history: tuple[ConversationTurn, ...]
    question: str
    digest_hash: str
    digest_changed: bool = False
    """The stored digest hash did not match the one just built — §22.3's mid-conversation
    invalidation. The adapter turns this into whatever its provider supports; the service and
    this module stay vendor-blind."""


def build_prompt(
    *,
    digest: str,
    question: str,
    history: Sequence[ConversationTurn] = (),
    tools_fingerprint: str = "",
    digest_changed: bool = False,
) -> AdvisorPrompt:
    """Assemble one turn's prompt and compute its prefix hash."""
    return AdvisorPrompt(
        system=ADVISOR_SYSTEM_PROMPT,
        digest=digest,
        history=tuple(history),
        question=question,
        digest_hash=digest_hash(ADVISOR_SYSTEM_PROMPT, digest, tools_fingerprint),
        digest_changed=digest_changed,
    )


def digest_hash(system: str, digest: str, tools_fingerprint: str = "") -> str:
    """Identify a conversation's cacheable prefix by content.

    Covers all three layers, because all three sit ahead of the first question and any of them
    changing invalidates the cache. The schema version is folded in so a change in how a stored
    thread is *read* can retire threads whose rendered text is identical.

    Note what this does **not** cover: the questions and answers themselves. Those grow with the
    conversation and are expected to; hashing them would produce a value that changes every turn
    and could never indicate anything.
    """
    fingerprint = hashlib.sha256()
    fingerprint.update(str(ADVISOR_SCHEMA_VERSION).encode("utf-8"))
    fingerprint.update(b"\x00")
    fingerprint.update(tools_fingerprint.encode("utf-8"))
    fingerprint.update(b"\x00")
    fingerprint.update(system.encode("utf-8"))
    fingerprint.update(b"\x00")
    fingerprint.update(digest.encode("utf-8"))
    return fingerprint.hexdigest()
