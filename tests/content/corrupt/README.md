# Corrupt content fixtures

One minimal corpus per §10.7 rule, each asserted by `tests/content/test_validate.py` to
fail `make validate-content` with a diagnostic naming the rule. They are deliberately
*minimal* rather than copies of a full corpus: a fixture that only contains what makes
its rule fire is readable, and a second unrelated error would make the assertion vague.

Every corpus except `10_kappa_ordering` borrows `../fixtures/profile.yaml`, since a
scoring profile is mandatory (§9.7) and only that fixture is corrupting it.

Numbering is append-only: a new rule takes the next number, and `test_validate.py`
asserts that the directories on disk and the entries in `CORRUPT_CORPORA` are the same
set, so neither can drift from the other. `11`–`13` are §10.6's candidate rules.
