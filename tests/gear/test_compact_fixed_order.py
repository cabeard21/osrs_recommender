"""Fixed beam and compact record caches retain independent first-observed orders."""

from types import SimpleNamespace

from tests.gear.test_fixed_reporting import fixed_inputs
from tests.gear.test_incremental_scoring import item
from tests.gear.test_prayer_search_efficiency import search
from tracker.gear.execution_profile import execution_context


def test_fractional_term_orders_are_prepared_independently_for_fixed_cache_families(monkeypatch):
    import tracker.gear.optimizer as module

    args = fixed_inputs("magic")
    extra = {
        10: item(10, "head", magic_damage=0.1),
        11: item(11, "body", magic_damage=0.2),
        12: item(12, "legs", magic_damage=-0.3),
    }
    args[2] = SimpleNamespace(items={**args[2].items, **extra}, version="fractional-order")
    role = args[1].roles[0]
    first = {"head": 10, "body": 11, "legs": 12}
    second = dict(reversed(tuple(first.items())))
    with execution_context(
        "combined", args[1], factored_evaluation=True, fixed_reporting=True, compact_states=True
    ):
        instance = search(args)
        instance.compact_cache.clear()
        instance.performance_cache.clear()
        orders = []
        original = module.evaluate_prepared_score

        def score(prepared, *a, **kw):
            orders.append(prepared._magic_terms)
            return original(prepared, *a, **kw)

        monkeypatch.setattr(module, "evaluate_prepared_score", score)
        instance.fixed_performance(first, role)
        instance.compact_combat(second, role)
        assert orders == [(0.1, 0.2, -0.3), (-0.3, 0.2, 0.1)]
        # Each existing canonical cache retains its own first-observed order.
        instance.fixed_performance(second, role)
        instance.compact_combat(first, role)
        assert len(orders) == 2
