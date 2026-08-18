"""Drawing §22's conversation.

Every sentence here was composed on :class:`~tracker.ui.view_model.AdvisorMessageRow`, for the
reason :mod:`tracker.ui.guidance` gives: a sentence assembled inside a ``ui.html(...)`` call can
only be checked by driving a browser, and a rule that expensive to check stops being checked.

**One deliberate exception to this package's escaping habit.** An answer is markdown, and is
drawn with :func:`nicegui.ui.markdown` rather than escaped into a paragraph — it is the one
place in the application where model-authored text becomes markup. That is safe because
NiceGUI sanitises the rendered HTML client-side, and it is *worth it* because a wall of
unformatted prose is a materially worse answer than the same words with its lists intact. The
question the user typed is escaped as usual: it is their text, not the model's, and it has no
reason to render as anything.

Every failure draws inside the conversation, where the reader is already looking. Never a
toast and never anywhere else on the page: D14 promises an advisor failure changes nothing
else, and a modal that interrupts the whole screen would quietly break that promise while the
code underneath still kept it. *Inside the conversation* is not the same as *faint*, though —
see :func:`render_error`.

**The layout is a consultation, not a chat.** A question is one line the reader typed; an
answer is a document with citations attached. Two mirrored bubbles — the default shape for
anything with a text box at the bottom — would be a claim that those are the same kind of
object. So they are drawn as different kinds: the question is a short recessed aside set to
the right, and the answer is a full-width panel hung off a gold rule that continues down
through its own footnotes.

That rule is this page's one piece of emphasis, and it is load-bearing rather than decorative.
Everything the model says about its own answer — what it was unsure of, what it looked up, who
wrote it, whether the account has moved since — hangs from it, so the receipts read as part of
the answer rather than as page furniture that happens to sit nearby. They are given three
different treatments because they are three different claims: a hedge is a request to go and
check something, and gets the same amber this application already spends on *you could act on
this*; the lookups are a record, and get the tabular face the rest of the app reserves for
data; the byline is the quietest thing on the page. All four were previously one dim size,
which is a reliable way to make a reader skip all of them.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from nicegui import ui

from tracker.ui.view_model import (
    ADVISOR_EMPTY,
    ADVISOR_PROMPTS,
    AdvisorConversationRow,
    AdvisorMessageRow,
    AdvisorThreadView,
)

#: Everything specific to this one view.
#:
#: Injected by the page rather than by :func:`tracker.ui.shell.inject_styles`, and that split
#: is the same ownership argument the shell makes about the state stylesheet, pointed the
#: other way: these rules are a property of the advisor surface and of nothing else, so
#: loading them on Skills or Roadmaps would be describing a page that does not exist.
ADVISOR_CSS = """
/* --- which conversation, and the ones before it -----------------------------------------
   Two jobs, and they were previously one control. *Start a new one* wants a button in a fixed
   place; *find an old one* wants a list you can read. Both were served by a single horizontally
   scrolling row of pills in which New was one more pill — so the row read as filter chrome, the
   titles were capped at 14rem and clipped mid-word at the viewport edge with nothing to say the
   row scrolled, and how many threads you had was unknowable.

   Now: a labelled row of fixed height carrying the name of the thread you are *in* (which
   nothing on the page said before), a menu behind it listing the rest at a width where titles
   can be read, and New as its own button. The eyebrow and the fixed position are what make the
   actions findable, so neither needs colour — the gold on this page stays spent on the answer
   rule and the Ask button. */
.advisor-threads {
  display: flex; flex-direction: column; gap: 0.35rem;
  padding-bottom: 0.7rem; margin-bottom: 0.9rem;
  border-bottom: 1px solid var(--edge-soft);
}
/* Uppercased under `shell.LAYOUT_CSS`'s rule: a fixed string this file authors, never content. */
.advisor-threads-label {
  font-family: var(--font-body); font-size: 0.625rem; font-weight: 600;
  letter-spacing: 0.09em; text-transform: uppercase; color: var(--ink-faint);
}
.advisor-threads-row { display: flex; align-items: stretch; gap: 0.5rem; }

.thread-picker {
  flex: 1 1 auto; min-width: 0;
  display: flex; align-items: center; gap: 0.5rem;
  min-height: 2.5rem; padding: 0.4rem 0.7rem;
  background: var(--panel); border: 1px solid var(--edge-soft); border-radius: 0.375rem;
  font-family: var(--font-body); font-size: 0.8125rem; line-height: 1.4;
  color: var(--ink); cursor: pointer; text-align: left;
}
.thread-picker:hover { border-color: var(--edge); }
/* `nowrap` is what keeps this row a fixed height. Without it a long title wrapped to two lines
   and the control grew, which is the behaviour the whole row was rebuilt to stop. */
.thread-picker-title {
  flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* The name of the current thread when there is no list behind it to open. Deliberately not a
   disabled button: on a first visit there is nothing to pick between, and a control that
   cannot act is worse than no control. */
.thread-current {
  flex: 1 1 auto; min-width: 0; display: flex; align-items: center;
  min-height: 2.5rem; font-size: 0.8125rem; color: var(--ink-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* Drawn from borders rather than set as `▾`, for the reason `shell.THEME_CSS` gives about its
   own dot: this app is reached over Tailscale, the webfonts may not resolve, and a glyph that
   falls back lands at a different size and weight on every platform. */
.thread-caret {
  flex: 0 0 auto; width: 0; height: 0;
  border-left: 0.28rem solid transparent; border-right: 0.28rem solid transparent;
  border-top: 0.3rem solid var(--ink-dim);
}

.thread-new {
  flex: 0 0 auto; min-height: 2.5rem; padding: 0 0.9rem;
  background: none; border: 1px solid var(--edge); border-radius: 0.375rem;
  font-family: var(--font-body); font-size: 0.8125rem; font-weight: 600;
  color: var(--ink); cursor: pointer; white-space: nowrap;
}
.thread-new:hover { border-color: var(--gold); color: var(--gold); }

/* --- the list behind the picker -------------------------------------------------------- */
.thread-menu { min-width: 15rem; max-width: min(24rem, calc(100vw - 1.5rem)); padding: 0.25rem; }
.thread-row { display: flex; align-items: stretch; gap: 0.25rem; }
.thread-open {
  flex: 1 1 auto; min-width: 0;
  display: flex; flex-direction: column; gap: 0.1rem;
  padding: 0.45rem 0.55rem;
  background: none; border: 0; border-radius: 0.25rem;
  font-family: var(--font-body); text-align: left; color: var(--ink); cursor: pointer;
}
.thread-open:hover { background: var(--panel); }
.thread-open[aria-current="true"] .thread-open-title { color: var(--gold); }
.thread-open-title {
  font-size: 0.8125rem; line-height: 1.35;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.thread-open-when { font-family: var(--font-data); font-size: 0.625rem; color: var(--ink-faint); }

/* The only destructive control in the application, so it stays the quietest thing in the list
   until you reach for it: rust on hover only. The colour this codebase spends on *this is
   wrong* should not be sitting on screen beside three threads that are perfectly fine. */
.thread-delete {
  position: relative; flex: 0 0 auto; width: 2.25rem; align-self: stretch;
  background: none; border: 0; border-radius: 0.25rem;
  color: var(--ink-faint); cursor: pointer;
}
.thread-delete:hover { color: var(--rust); background: var(--panel); }
/* Two bars rather than `✕`, on the same argument as `.thread-caret`. */
.thread-delete::before, .thread-delete::after {
  content: ""; position: absolute; top: 50%; left: 50%;
  width: 0.7rem; height: 1px; margin: -1px 0 0 -0.35rem; background: currentColor;
}
.thread-delete::before { transform: rotate(45deg); }
.thread-delete::after { transform: rotate(-45deg); }

/* --- and the question it asks first ---------------------------------------------------- */
.advisor-confirm {
  display: flex; flex-direction: column; gap: 0.6rem; padding: 1rem; max-width: 22rem;
}
.advisor-confirm-title { font-size: 0.9375rem; font-weight: 600; color: var(--ink); }
.advisor-confirm-body { font-size: 0.8125rem; line-height: 1.55; color: var(--ink-dim); }
.advisor-confirm-actions {
  display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 0.2rem;
}
.advisor-confirm-actions button {
  min-height: 2.25rem; padding: 0 0.9rem; border-radius: 0.375rem;
  font-family: var(--font-body); font-size: 0.8125rem; font-weight: 600; cursor: pointer;
}
.advisor-confirm-cancel { background: none; border: 1px solid var(--edge); color: var(--ink); }
.advisor-confirm-go {
  background: var(--rust); border: 1px solid var(--rust); color: var(--ground);
}

/* --- the transcript ------------------------------------------------------------------ */
.advisor-thread { display: flex; flex-direction: column; gap: 1.6rem; }

.msg-who {
  font-family: var(--font-body); font-size: 0.6875rem; font-weight: 600;
  /* Uppercased, which this codebase otherwise reserves for fixed strings it authors itself
     (see the note in `shell.LAYOUT_CSS`) — and these are exactly that: two labels written
     here, never a name or a sentence handed in from content or from a model. */
  letter-spacing: 0.09em; text-transform: uppercase; color: var(--ink-faint);
}

.msg-you { display: flex; flex-direction: column; align-items: flex-end; gap: 0.3rem; }
.msg-you .msg-body {
  max-width: 44ch; padding: 0.5rem 0.75rem;
  background: var(--panel-2); border: 1px solid var(--edge-soft);
  /* Square on the corner nearest its own label, so the question points back at the person
     who asked it without a tail needing to be drawn on it. */
  border-radius: 0.4rem 0.4rem 0 0.4rem;
  font-size: 0.875rem; line-height: 1.55; color: var(--ink); text-align: left;
}

/* Capped at a measure rather than left to fill the shell's 60rem. At the answer's body size
   that full width is around 115 characters a line, roughly twice the distance an eye tracks
   back accurately — and an answer is the longest continuous prose in the application, so it
   is the one place where the measure actually costs comprehension. The cap governs the
   footnotes too, which is why it sits on the message and not on the body. */
.msg-advisor {
  display: flex; flex-direction: column; gap: 0.5rem; max-width: 68ch;
  padding-left: 0.9rem; border-left: 2px solid var(--gold);
}
.msg-advisor > .msg-who { color: var(--gold); }
.msg-advisor .msg-body { font-size: 0.9375rem; line-height: 1.65; color: var(--ink); }

/* --- an answer's markdown -------------------------------------------------------------
   This is the only place in the application where arbitrary markup reaches the page, and it
   previously had no typography at all: a model that opened with `##` got the browser default,
   which is bold, 1.5em and in whichever serif the device falls back to — the loudest thing on
   a page whose own title is set at 1.25rem.

   Headings are set in the *body* face on purpose. The display face is this application's own
   voice — the page title, the stat figures — and letting a model's heading borrow it would be
   an attribution the answer has not earned. Code and tables take the data face for the reason
   the gear ladder does: what the advisor quotes back is item names, prices and level
   requirements, and those are tabular. */
.msg-advisor .nicegui-markdown > :first-child { margin-top: 0; }
.msg-advisor .nicegui-markdown > :last-child { margin-bottom: 0; }
.msg-advisor .nicegui-markdown p { margin: 0 0 0.7rem; }
.msg-advisor .nicegui-markdown h1,
.msg-advisor .nicegui-markdown h2,
.msg-advisor .nicegui-markdown h3,
.msg-advisor .nicegui-markdown h4,
.msg-advisor .nicegui-markdown h5,
.msg-advisor .nicegui-markdown h6 {
  font-family: var(--font-body); font-size: 0.9375rem; font-weight: 600;
  line-height: 1.4; color: var(--ink); margin: 1.15rem 0 0.4rem;
}
.msg-advisor .nicegui-markdown ul,
.msg-advisor .nicegui-markdown ol { margin: 0 0 0.7rem; padding-left: 1.2rem; }
.msg-advisor .nicegui-markdown ul { list-style: disc; }
.msg-advisor .nicegui-markdown ol { list-style: decimal; }
.msg-advisor .nicegui-markdown li { margin-bottom: 0.25rem; }
.msg-advisor .nicegui-markdown li::marker { color: var(--ink-faint); }
.msg-advisor .nicegui-markdown strong { font-weight: 600; color: var(--ink); }
.msg-advisor .nicegui-markdown em { font-style: italic; }
.msg-advisor .nicegui-markdown a {
  color: var(--gold); text-decoration: underline; text-underline-offset: 2px;
}
.msg-advisor .nicegui-markdown code {
  font-family: var(--font-data); font-size: 0.8125em;
  background: var(--panel-2); border: 1px solid var(--edge-soft);
  border-radius: 0.2rem; padding: 0.05em 0.3em; color: var(--ink);
}
.msg-advisor .nicegui-markdown pre {
  background: var(--panel-2); border: 1px solid var(--edge-soft); border-radius: 0.3rem;
  padding: 0.6rem 0.7rem; margin: 0 0 0.7rem; overflow-x: auto;
}
.msg-advisor .nicegui-markdown pre code {
  background: none; border: 0; padding: 0; font-size: 0.75rem; line-height: 1.55;
}
.msg-advisor .nicegui-markdown blockquote {
  margin: 0 0 0.7rem; padding-left: 0.75rem;
  border-left: 2px solid var(--edge); color: var(--ink-dim);
}
.msg-advisor .nicegui-markdown hr {
  border: 0; border-top: 1px solid var(--edge-soft); margin: 1.1rem 0;
}
/* `display: block` turns the table into its own scroll container. A markdown table is the one
   piece of model output whose width this app cannot bound — and a phone that scrolls sideways
   is exactly the failure `shell.LAYOUT_CSS` spends its `overflow-wrap` rule preventing. */
.msg-advisor .nicegui-markdown table {
  display: block; overflow-x: auto; max-width: 100%; width: max-content;
  border-collapse: collapse; margin: 0 0 0.7rem;
  font-family: var(--font-data); font-size: 0.75rem;
}
.msg-advisor .nicegui-markdown th,
.msg-advisor .nicegui-markdown td {
  border: 1px solid var(--edge-soft); padding: 0.3rem 0.45rem; text-align: left;
}
.msg-advisor .nicegui-markdown th { color: var(--ink-dim); font-weight: 600; }

/* --- the receipts --------------------------------------------------------------------- */
.msg-foot { display: flex; flex-direction: column; gap: 0.35rem; }

/* A hedge asks the reader to go and check something, so it takes the amber this application
   already spends on `available` — the one state meaning *you could act on this now*. Same
   colour, same request, and a reader who learned it on the unlocks page has learned it here. */
.msg-hedge {
  background: var(--amber-ink); border-left: 2px solid var(--amber);
  border-radius: 0 0.25rem 0.25rem 0; padding: 0.45rem 0.6rem;
}
.msg-hedge-title { font-size: 0.75rem; font-weight: 600; color: var(--amber); display: block; }
.msg-hedge-list { margin: 0.3rem 0 0; padding-left: 1.1rem; list-style: disc; }
.msg-hedge-list li { font-size: 0.8125rem; line-height: 1.5; color: var(--ink); }
.msg-hedge-list li::marker { color: var(--amber); }

.msg-note { font-size: 0.75rem; line-height: 1.5; color: var(--ink-dim); }
.msg-sources {
  font-family: var(--font-data); font-size: 0.6875rem; line-height: 1.5; color: var(--ink-dim);
}
.msg-byline { font-size: 0.6875rem; color: var(--ink-faint); }

/* --- the states around a conversation ------------------------------------------------- */
.advisor-empty { display: flex; flex-direction: column; gap: 0.75rem; }
.advisor-empty-text { font-size: 0.875rem; line-height: 1.6; color: var(--ink-dim); }
.advisor-prompts { display: flex; flex-direction: column; gap: 0.4rem; align-items: flex-start; }
.advisor-prompt {
  max-width: 100%; padding: 0.4rem 0.7rem; text-align: left;
  background: none; border: 1px dashed var(--edge); border-radius: 0.375rem;
  font-family: var(--font-body); font-size: 0.8125rem; line-height: 1.45;
  color: var(--ink); cursor: pointer;
}
.advisor-prompt:hover { border-style: solid; border-color: var(--gold); color: var(--gold); }

.advisor-pending { display: flex; align-items: center; gap: 0.5rem; }
.advisor-pending .msg-note { font-style: italic; }

/* A failure is the one thing on this page the reader has to notice, and it was previously
   drawn as `.msg-note` — the faintest treatment the application owns, reserved everywhere
   else for asides nobody has to read. It keeps D14's promise by staying inside the
   conversation rather than becoming a toast, and earns its weight from `--rust`, which this
   codebase already spends on *this is wrong* (`badges.confidence-low`, the gear notes). The
   rule down its left edge is the answer's rule in another colour, so a failure occupies the
   same column as the answer it replaced instead of reading as page furniture. */
.advisor-error {
  max-width: 68ch; padding: 0.5rem 0.7rem;
  background: var(--panel); border-left: 2px solid var(--rust);
  border-radius: 0 0.25rem 0.25rem 0;
  font-size: 0.8125rem; line-height: 1.55; color: var(--ink);
}
/* The spinner is constructed with `color=None` for the reason given below, so it inherits
   here and no `!important` is needed — or would help. */
.advisor-pending .q-spinner { color: var(--gold); }

/* --- the composer ----------------------------------------------------------------------
   Sticky, so the box stays reachable without scrolling to the foot of a long thread — offset
   by the height of the phone nav, which is fixed over the bottom of the viewport, and dropped
   to the floor from 48rem where that nav moves to the top of the document instead. */
.advisor-composer {
  position: sticky; bottom: calc(3rem + env(safe-area-inset-bottom, 0px));
  z-index: 20; display: flex; flex-direction: column; gap: 0.3rem;
  margin-top: 1.25rem; padding: 0.6rem 0;
  background: var(--ground); border-top: 1px solid var(--edge-soft);
}
.advisor-composer-row { display: flex; align-items: flex-end; gap: 0.5rem; }
@media (min-width: 48rem) { .advisor-composer { bottom: 0; } }

/* No `!important` here, and adding some would make this *worse* rather than better.

   NiceGUI 3 loads Quasar inside a CSS cascade layer, and the cascade reverses layer order for
   important declarations: an unlayered `!important` — which is all `ui.add_css` can produce —
   ranks below every layered one, so `.bg-primary !important` beat this rule at any specificity
   while it carried `!important` too, and stopped beating it the moment that was removed. The
   button is therefore built with `color=None` (see `pages.advisor_page`) so `bg-primary` is
   never attached, and this plain unlayered rule then wins uncontested, the way an unlayered
   *normal* declaration always does. Fighting the class is not an option that exists; not
   asking for it is. */
.q-btn[data-testid="advisor-send"] {
  background: var(--gold); color: var(--amber-ink);
  min-height: 2.75rem; padding: 0 1.1rem; border-radius: 0.375rem;
  font-family: var(--font-body); font-weight: 600;
}
.advisor-hint { font-size: 0.6875rem; color: var(--ink-faint); text-align: right; }
"""


def inject_styles() -> None:
    """Add this view's stylesheet. Called once, by the page."""
    ui.add_css(ADVISOR_CSS)


def render_thread(
    view: AdvisorThreadView, *, on_prompt: Callable[[str], None] | None = None
) -> None:
    """Draw every stored message in order, or the empty state."""
    if view.is_empty:
        render_empty(on_prompt=on_prompt)
        return
    for message in view.messages:
        render_message(message)


def render_empty(*, on_prompt: Callable[[str], None] | None = None) -> None:
    """What the advisor can see, and three ways to start.

    The sentence on its own described the surface and then left the reader to compose a first
    question from nothing, which is the hardest question they will ever be asked here. The
    three prompts are chosen to show the *range* rather than to be good questions — one needs
    the account digest, one needs the corpus, one needs both — so reading them teaches what
    this thing is for. They are omitted entirely when there is no box to fill, rather than
    drawn as dead text: a control that does not act is worse than no control.
    """
    container = ui.element("div").classes("advisor-empty")
    container.props("data-testid=advisor-empty")
    with container:
        ui.html(html.escape(ADVISOR_EMPTY)).classes("advisor-empty-text")
        if on_prompt is None:
            return
        with ui.element("div").classes("advisor-prompts"):
            for prompt in ADVISOR_PROMPTS:
                button = ui.element("button").classes("advisor-prompt")
                button.props("type=button data-testid=advisor-prompt")
                button.on("click", lambda _, text=prompt: on_prompt(text))
                with button:
                    ui.html(html.escape(prompt))


def render_message(row: AdvisorMessageRow) -> ui.element:
    """One question or one answer, with §22.8's attribution beneath it.

    Returns its container, because the optimistic path in :mod:`tracker.ui.pages` has to be
    able to take an *unstored* question back off the screen when the turn fails.
    """
    container = ui.element("div").classes(f"msg msg-{'advisor' if row.is_answer else 'you'}")
    container.props(f"data-testid=advisor-message data-role={row.role}")
    with container:
        ui.html(html.escape(row.who_label)).classes("msg-who")

        body = ui.element("div").classes("msg-body")
        body.props("data-testid=advisor-text")
        with body:
            if row.is_answer:
                # The one place model text becomes markup — see the module docstring.
                ui.markdown(row.text)
            else:
                ui.html(html.escape(row.text))

        _footer(row)
    return container


def _footer(row: AdvisorMessageRow) -> None:
    """What an answer says about itself, or nothing at all.

    Skipped whole for a question, and skipped for an answer carrying none of these — an empty
    footer would draw a rule under nothing and imply there was something there to read.
    """
    notes = (row.uncertainty_label, row.staleness_note, row.truncation_note, row.sources_label)
    if not any(notes) and row.provenance_label is None:
        return

    with ui.element("div").classes("msg-foot"):
        # Drawn apart from the answer, because this is the model telling you which parts of
        # its own reply to check — a different request of the reader than the reply itself.
        if row.uncertainty_label is not None:
            uncertain = ui.element("div").classes("msg-hedge")
            uncertain.props("data-testid=advisor-uncertain")
            with uncertain:
                ui.html(html.escape(row.uncertainty_label)).classes("msg-hedge-title")
                with ui.element("ul").classes("msg-hedge-list"):
                    for item in row.uncertain:
                        with ui.element("li"):
                            ui.html(html.escape(item))

        _note(row.staleness_note, "advisor-stale", "msg-note")
        _note(row.truncation_note, "advisor-truncated", "msg-note")
        _note(row.sources_label, "advisor-sources", "msg-sources")
        _note(row.provenance_label, "advisor-provenance", "msg-byline")


def render_question(text: str) -> ui.element:
    """The question, echoed immediately, before any answer exists.

    Optimistic because the alternative is a second or more of a page that looks like it ignored
    the keypress. The row is drawn from the same view type as a stored one, so nothing about it
    is a special case except that its answer has not arrived.

    Drawn *separately* from the spinner, and that separation is the whole point of this
    function existing. The two used to be one call inside one wrapper, and the caller deleted
    the wrapper when the answer landed — which deleted the question with it. Every turn after
    the first therefore rendered as an answer with nothing above it, on a page whose entire
    layout argument is that a question and an answer are two different kinds of object. They
    have different lifetimes, so they are two elements: the spinner always goes, and the
    question goes only when the turn failed and there is nothing to have asked.
    """
    return render_message(AdvisorMessageRow(role="you", text=text))


def render_pending() -> ui.element:
    """The spinner that stands in for the answer, and nothing else."""
    pending = ui.element("div").classes("advisor-pending")
    pending.props("data-testid=advisor-pending")
    with pending:
        # `color=None` for the same reason the Ask button takes it: Quasar's `text-primary`
        # is a layered `!important` that no stylesheet added here can outrank, so the only
        # way onto the palette is to never attach the class. It then inherits from the CSS.
        ui.spinner(size="sm", color=None)
        ui.html("Thinking…").classes("msg-note")
    return pending


def render_error(message: str) -> None:
    """Say what happened, in the conversation, where the reader is already looking.

    Deliberately not a toast and not a dialog: the advisor is a terminal output (D14), so its
    failure changes nothing else on the page, and an interruption that covered the screen would
    contradict that while the code underneath still honoured it.

    Not *quiet*, though, which is a different question and one this drew the wrong answer to
    for a while. It was styled as `.msg-note` — the same faint grey aside used for "written
    before your most recent sync" — so the sentence a reader must act on looked exactly like
    the two they may ignore. See ``.advisor-error`` for what it takes instead.
    """
    element = ui.element("div").classes("advisor-error")
    element.props("data-testid=advisor-error")
    with element:
        ui.html(html.escape(message))


def render_live_region() -> ui.element:
    """The announcement line, present from first paint and never visible.

    This page is the one surface in the application driven from the keyboard: a reader sends
    with Ctrl+Enter, waits several seconds for a paid call, and then has content appended
    somewhere below the fold. Without this, none of that is reported to a screen reader — the
    spinner is a graphic and the answer is silent markup.

    A *persistent* region whose text changes, rather than ``aria-live`` on the transcript
    itself. Two reasons, and the second is the one that matters. A live region has to be in
    the document before it changes for the change to be announced reliably, which a freshly
    appended element is not. And an answer here is a document — headings, a table, several
    hundred words — so marking the transcript live would read the entire thing aloud on
    arrival, with no way to stop it. What belongs in a live region is the *event*; the answer
    itself is ordinary content the reader can then navigate to at their own pace.
    """
    region = ui.element("div").classes("sr-only")
    region.props("data-testid=advisor-status role=status aria-live=polite")
    return region


def announce(region: ui.element, message: str) -> None:
    """Replace the live region's text, which is what makes it speak."""
    region.clear()
    with region:
        ui.html(html.escape(message))


#: What the announcement says once an answer has landed.
#:
#: The event and not the answer, for :func:`render_live_region`'s reason. It names where the
#: content went, because "the advisor answered" on its own leaves a reader who cannot see the
#: page with no idea what to do next.
ANSWER_ANNOUNCEMENT = "The advisor answered. The reply is at the end of the conversation."

#: What it says while a turn is in flight — the spinner's caption, for readers who get no
#: spinner.
PENDING_ANNOUNCEMENT = "Question sent. Waiting for the advisor."


def scroll_to_latest() -> None:
    """Bring the foot of the conversation into view.

    An answer is appended to the bottom of a thread that is often already taller than the
    screen, so without this the page's response to a question is to change nothing the reader
    can see.

    ``block: "start"`` rather than ``"nearest"``, and the difference is not cosmetic.
    *Nearest* scrolls the minimum, which for anything shorter than the viewport parks the new
    content against the bottom edge — behind the sticky composer and, on a phone, behind the
    nav bar as well. *Start* puts the top of what just arrived at the top of the screen, which
    is both where an answer should be read from and the only one of the two that is
    predictable across answer lengths.

    No ``behavior`` is requested, so this inherits the document's ``scroll-behavior`` — which
    means ``prefers-reduced-motion``, already honoured in
    :data:`~tracker.ui.shell.LAYOUT_CSS`, governs it without anything further here.

    Written against the transcript's own ``data-testid`` rather than an element handle,
    because NiceGUI's DOM ids are an implementation detail of the framework and this selector
    is one the browser tests already depend on.

    **Deferred two frames, and that is the whole reason this works.** ``run_javascript`` goes
    down the same websocket as the element updates it follows, but Vue applies those patches
    on ``nextTick`` — so script that runs on arrival sees the thread *without* the message
    just appended to it. Scrolling then is not merely early, it is silently wrong: the
    browser clamps a scroll to the document as it stands, the answer renders afterwards and
    makes the document taller, and the page is left parked short of where it asked to be with
    no error anywhere. Measured on a 390x844 viewport, that landed a 2332px answer 464px down
    the screen — on screen, which is why an assertion about *scrolling* rather than about
    where the answer ended up would have called it fine.

    One frame gets past Vue's flush; the second gets past the layout that flush triggers, so
    ``scrollIntoView`` measures the document that now contains the answer. ``rAF`` rather than
    a timeout because the thing being waited for is a paint, and a timeout that happens to be
    long enough on one machine is the bug above wearing a different number.
    """
    ui.run_javascript(
        "const scroll = () => {"
        "  const thread = document.querySelector('[data-testid=advisor-thread]');"
        "  const last = thread && thread.lastElementChild;"
        "  if (last) { last.scrollIntoView({block: 'start'}); }"
        "};"
        "requestAnimationFrame(() => requestAnimationFrame(scroll));"
    )


def render_conversation_list(
    view: AdvisorThreadView,
    on_select: Callable[[int], None],
    on_new: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    """Which conversation you are in, the ones before it, and the way to start another.

    Three questions, and the row answers them in that order because that is the order they are
    asked in. *Where am I* came first only after it turned out nothing on the page answered it
    at all: the previous row of pills marked the current thread with a gold outline, which is a
    claim you can only read if you already know the vocabulary and can see the pill, and its
    title was clipped at 14rem either way.

    Plain ``<button>`` elements rather than :func:`nicegui.ui.button`, because a Quasar button
    arrives carrying its own ground, its ripple and ``color="primary"`` — and that prop is what
    put Quasar blue, the one colour outside this application's palette, on the one element here
    the reader is meant to find first.

    Current is carried by ``aria-current`` with the styling hung off it, the way the nav does
    it: one source, so a row cannot look selected without announcing it.
    """
    container = ui.element("div").classes("advisor-threads")
    container.props("data-testid=advisor-conversations aria-label=Conversations")
    with container:
        confirm = _delete_confirmation(on_delete)
        ui.html("Conversation").classes("advisor-threads-label")
        with ui.element("div").classes("advisor-threads-row"):
            _picker(view, on_select, confirm)

            new = ui.element("button").classes("thread-new")
            new.props("type=button data-testid=advisor-new")
            new.on("click", lambda _: on_new())
            with new:
                ui.html("New")


def _picker(
    view: AdvisorThreadView,
    on_select: Callable[[int], None],
    confirm: Callable[[AdvisorConversationRow], None],
) -> None:
    """The thread on screen, and — if there are others — the list of them."""
    if not view.has_conversations:
        ui.html(html.escape(view.current_label)).classes("thread-current")
        return

    picker = ui.element("button").classes("thread-picker")
    picker.props("type=button data-testid=advisor-picker aria-haspopup=menu")
    with picker:
        ui.html(html.escape(view.current_label)).classes("thread-picker-title")
        ui.element("span").classes("thread-caret")
        with ui.menu().classes("thread-menu") as menu:
            menu.props("data-testid=advisor-thread-menu")

            def request_delete(row: AdvisorConversationRow) -> None:
                """Close the list before asking, so the question is not posed over it."""
                menu.close()
                confirm(row)

            for row in view.conversations:
                _thread_row(row, on_select=on_select, on_remove=request_delete)


def _thread_row(
    row: AdvisorConversationRow,
    *,
    on_select: Callable[[int], None],
    on_remove: Callable[[AdvisorConversationRow], None],
) -> None:
    """One past conversation: open it, or get rid of it.

    Two elements rather than one row with a swipe or a long-press, because both of those are
    gestures a reader has to discover, and this list exists precisely because the last version
    of it could not be discovered.
    """
    with ui.element("div").classes("thread-row"):
        open_button = ui.element("button").classes("thread-open")
        open_button.props("type=button data-testid=advisor-conversation")
        open_button.props(f"data-current={str(row.current).lower()}")
        open_button.props(f"aria-current={str(row.current).lower()}")
        open_button.on("click", lambda _, identifier=row.conversation_id: on_select(identifier))
        with open_button:
            ui.html(html.escape(row.title)).classes("thread-open-title")
            if row.when_label is not None:
                ui.html(html.escape(row.when_label)).classes("thread-open-when")

        remove = ui.element("button").classes("thread-delete")
        remove.props("type=button data-testid=advisor-delete")
        remove.on("click", lambda _, chosen=row: on_remove(chosen))
        with remove:
            # The visible mark is two CSS bars, which say nothing. Every one of these buttons
            # is otherwise identical, so the name has to carry which thread it removes.
            ui.html(html.escape(f"Delete “{row.title}”")).classes("sr-only")


def _delete_confirmation(
    on_delete: Callable[[int], None],
) -> Callable[[AdvisorConversationRow], None]:
    """Build the one confirmation dialog, and return the way to point it at a thread.

    One dialog re-aimed rather than one built per click. A dialog constructed inside an event
    handler has to guess which slot it belongs to, and this one is opened from inside a menu
    that is closing as it opens; building it once at render time removes both questions.

    Asked at all because this is the only irreversible thing the application does. Everything
    else here is a read — and a conversation is the one artefact in this app the user paid a
    provider to produce.
    """
    pending: AdvisorConversationRow | None = None

    with ui.dialog() as dialog:
        dialog.props("data-testid=advisor-delete-dialog")
        with ui.element("div").classes("advisor-confirm"):
            ui.html("Delete this conversation?").classes("advisor-confirm-title")
            body = ui.element("div").classes("advisor-confirm-body")
            body.props("data-testid=advisor-delete-body")
            with ui.element("div").classes("advisor-confirm-actions"):
                cancel = ui.element("button").classes("advisor-confirm-cancel")
                cancel.props("type=button data-testid=advisor-delete-cancel")
                cancel.on("click", lambda _: dialog.close())
                with cancel:
                    ui.html("Cancel")

                # Named for what it does, and it keeps that name from the row it was opened
                # from through to here — the ✕, this button and the sentence above all say
                # *delete*, so nothing has to be re-learned mid-flow.
                go = ui.element("button").classes("advisor-confirm-go")
                go.props("type=button data-testid=advisor-delete-confirm")
                go.on("click", lambda _: _commit())
                with go:
                    ui.html("Delete")

    def _commit() -> None:
        dialog.close()
        if pending is not None:
            on_delete(pending.conversation_id)

    def open_for(row: AdvisorConversationRow) -> None:
        nonlocal pending
        pending = row
        body.clear()
        with body:
            ui.html(html.escape(f"“{row.title}” and its answers will be removed for good."))
        dialog.open()

    return open_for


def _note(text: str | None, testid: str, css_class: str) -> None:
    """A small aside, or nothing.

    Omitted rather than drawn empty for :mod:`tracker.ui.guidance`'s reason: a heading over no
    content reads as a claim, and each of these notes is an exception rather than a field.
    """
    if text is None:
        return
    element = ui.element("div").classes(css_class)
    element.props(f"data-testid={testid}")
    with element:
        ui.html(html.escape(text))
