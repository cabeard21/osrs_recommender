# Corrupt content fixtures

One minimal corpus per §10.7 rule, each asserted by `tests/content/test_validate.py` to
fail `make validate-content` with a diagnostic naming the rule. They are deliberately
*minimal* rather than copies of a full corpus: a fixture that only contains what makes
its rule fire is readable, and a second unrelated error would make the assertion vague.

Every corpus except `10_kappa_ordering` borrows `../fixtures/profile.yaml`, since a
scoring profile is mandatory (§9.7) and only that fixture is corrupting it.

Numbering is append-only: a new rule takes the next number, and `test_validate.py`
asserts that the directories on disk and the entries in `CORRUPT_CORPORA` are the same
set, so neither can drift from the other. `11`–`13` are §10.6's candidate rules, `15`–`17`
are §10.5's gear ladders, `18`–`20` are §23.2's wear gates, and `21` is §10.5's
acquisition axis.

`21` is not a second copy of `20`. Both are contradictions on an item, and they contradict
different things: `20` says at once that the *wear gate* is known and that it is not, while
`21` says at once that a piece can be bought and that it must be won from a boss. Two
questions, two fields, two rules.

`17` and `22` are the two halves of one rule, and neither is redundant. An id shared by two
rows is *legal* when they are one piece placed on two ladders — an Antler guard is a tribrid
shield both the melee and the ranged guide print, and owning it really does place the account
on both. `17` shares an id between two genuinely different items (a Voidwaker id among an
Armadyl godsword's variants); `22` shares one between two rows that agree they are the same
item and disagree about its wear gate. Drop either and the rule can be relaxed into
uselessness or tightened back into forbidding the legitimate case.

`18` looks redundant beside `02` and is not: `02` reaches a dangling id through a
*capability*, so it would keep passing if item requirement trees were checked by nobody.
It exists to assert that items are in `_requirement_sources`, which is the one line that
whole rule depends on.
