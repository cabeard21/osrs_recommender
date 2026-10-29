"""Keep shared search scenarios together while distributing independent tests."""

from collections import Counter

import pytest

# These full-account searches dominate runtime despite having few assertions.
_SEARCH_PRIORITY = {
    "frozen_account_account_four": 0,
    "frozen_account_account_three": 1,
    "frozen_account_joint_four": 2,
}


def _group(item: pytest.Item) -> str:
    names = {
        str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
        for mark in item.iter_markers("xdist_group")
    }
    return "_".join(sorted(names))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Run before xdist appends group names to node IDs. Preserve loadscope-style
    # fixture reuse elsewhere; frozen scenarios can share results across modules.
    for item in items:
        if any(item.iter_markers("xdist_group")):
            continue
        if isinstance(item, pytest.Function) and "frozen_account_result" in item.fixturenames:
            group = f"frozen_account_{item.callspec.params['name']}"
        else:
            group = item.nodeid.rsplit("::", 1)[0]
        item.add_marker(pytest.mark.xdist_group(group))

    if config.getoption("dist", default="no") == "loadgroup":
        counts = Counter(_group(item) for item in items)
        # CI disables xdist's count-only reordering so expensive singleton groups
        # start early. Retain largest-group-first scheduling for the other tests.
        items.sort(key=lambda item: (_SEARCH_PRIORITY.get(_group(item), 3), -counts[_group(item)]))
