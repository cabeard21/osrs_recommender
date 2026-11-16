"""An expanded beam larger than the numeric cache must reuse each computed projection."""

from types import SimpleNamespace

from tracker.gear.optimizer import SLOTS
from tracker.gear.progress import NULL_REPORTER
from tracker.gear.vector_options import OptionVariant, VectorOptions
from tracker.gear.vector_search import VectorSearch


def test_large_batch_preserves_retained_order_without_rescoring_after_cache_eviction():
    role = SimpleNamespace(id="a", style="slash", weight=1, locks={})
    request = SimpleNamespace(locks={}, budget_gp=0, objectives=(SimpleNamespace(id="defence"),))
    items = {
        1: SimpleNamespace(slot="weapon"),
        **{item: SimpleNamespace(slot="head") for item in range(100, 868)},
    }
    search = SimpleNamespace(
        request=request,
        cancelled=None,
        reporter=NULL_REPORTER,
        compatible=lambda equipment: True,
        cost=lambda carried: 0,
        eligible=items,
    )

    def values(equipment):
        bonus = float(equipment.get("head", 0))
        return 1000 - bonus, bonus

    class NumericOptions(VectorOptions):
        def __init__(self):
            super().__init__(search)
            self.evaluations = 0

        def _variants(self, equipment, configured):
            self.evaluations += 1
            return (OptionVariant(configured, None, {"supported": True}, values(equipment)),)

    def equipment(options):
        engine = VectorSearch.__new__(VectorSearch)
        engine.search, engine.options = search, options
        engine.limit, engine.nodes = 1_000_000, 0
        engine.pools = {slot: [None] for slot in SLOTS}
        engine.pools = {**engine.pools, "weapon": [1], "head": list(range(100, 868))}
        engine.capture = lambda assignment: None
        return engine.equipment((role,), 100000)

    # A stateless numeric oracle fixes the retained physical configurations and
    # their order independently of cache contents and materialization strategy.
    expected = equipment(SimpleNamespace(projection=lambda row, roles, **kwargs: values(row)))
    cached = NumericOptions()
    actual = equipment(cached)
    assert actual == expected
    # One evaluation per expanded head, plus at most one cache refill of the
    # retained 256 states in a subsequent slot. Retention itself must reuse the
    # already computed vectors rather than traversing the evicted batch again.
    assert cached.evaluations <= 768 + 256 + 5


def test_projection_preserves_weighting_and_independent_option_extremes():
    roles = (
        SimpleNamespace(id="a", style="slash", weight=1),
        SimpleNamespace(id="b", style="ranged", weight=3),
    )
    options = VectorOptions(SimpleNamespace(request=SimpleNamespace(objectives=("defence",))))
    alternatives = {
        "a": ((10.0, 1.0), (2.0, 9.0)),
        "b": ((4.0, 7.0), (6.0, 5.0)),
    }
    options.variants = lambda equipment, role: tuple(
        OptionVariant(role, None, {"supported": True}, values) for values in alternatives[role.id]
    )
    assert options.projection({}, roles, require_supported=True) == (7.0, 7.5)
    options.variants = lambda equipment, role: ()
    options.envelope_cache.clear()  # The test replaces its otherwise frozen scoring context.
    assert options.projection({}, roles, require_supported=True) is None
    assert options.projection({}, roles, require_supported=False) == (0.0, 0.0)
