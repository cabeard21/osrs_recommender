"""Private native execution flags and evidence never change public contracts."""

import pytest

from tools.gear_search_quality_fixture import load_case


def test_capture_is_scoped_and_immutable_snapshots():
    from tracker.gear.native import capture, record

    with capture() as outer:
        record("stage", stage="loadout", attempts=10)
        first = outer.snapshot()
        with capture() as inner:
            record("fallback", reason="magic")
        record("stage", stage="joint", attempts=20)
    assert len(first["events"]) == 1
    assert len(outer.snapshot()["events"]) == 2
    assert inner.snapshot()["events"] == [{"event": "fallback", "reason": "magic"}]


@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_native_service_flag_is_strict(bad):
    from tracker.gear.service import GearService

    with pytest.raises(ValueError, match="native search"):
        GearService(load_case("melee_1m").content, native_search=bad)


def test_native_service_passes_flag_and_collects_sidecar(monkeypatch):
    from tracker.gear.native import record
    from tracker.gear.service import GearService

    case = load_case("melee_1m")
    service = GearService(
        case.content,
        optimization_profile="combined",
        factored_evaluation=True,
        compact_states=True,
        native_search=True,
    )
    service._equipment = case.catalog

    def run(*args, **kwargs):
        assert kwargs["_native_search"] is True
        record("stage", stage="loadout", attempts=10)
        return {"ok": True}

    monkeypatch.setattr("tracker.gear.optimizer.optimize", run)
    assert service.optimize(
        case.snapshot, case.request, price_records=case.prices, now=case.at
    ) == {"ok": True}
    assert service.native_diagnostics["events"][0]["stage"] == "loadout"


def test_native_scope_resets_on_failure():
    from tracker.gear.native import active, execution

    assert not active()
    with pytest.raises(RuntimeError), execution(True):
        assert active()
        raise RuntimeError("test")
    assert not active()


@pytest.mark.parametrize("style", ["stab", "slash", "crush", "ranged", "magic", "special"])
@pytest.mark.parametrize("priority", ["accuracy", "magic_damage_bonus", "balanced_defence_roll"])
def test_existing_modes_are_declared_supported(style, priority):
    from tracker.gear.native import support_reason

    case = load_case("melee_1m")
    role = case.request.roles[0].model_copy(update={"style": style})
    request = case.request.model_copy(update={"roles": (role,), "secondary_priority": priority})
    assert support_reason(request) is None


def test_copied_lane_discards_native_stage_and_rebinds_changed_objective(monkeypatch):
    from copy import copy
    from types import SimpleNamespace

    import tracker.gear.native as native

    original = SimpleNamespace(native_context=object(), _native_stage_context=object())
    lane = copy(original)
    replacement = object()
    monkeypatch.setattr(native, "create_context", lambda search: replacement)
    native.reset_context(lane, scoring=True)
    assert lane._native_stage_context is None
    assert lane.native_context is replacement
    assert original._native_stage_context is not None
    assert original.native_context is not replacement


def test_reset_disabled_native_does_not_activate_a_lane(monkeypatch):
    from types import SimpleNamespace

    import tracker.gear.native as native

    lane = SimpleNamespace(native_context=None, _native_stage_context=object())
    monkeypatch.setattr(
        native, "create_context", lambda search: pytest.fail("unexpected activation")
    )
    native.reset_context(lane, scoring=True)
    assert lane._native_stage_context is None
    assert lane.native_context is None


def test_worker_evidence_merges_without_changing_prior_snapshot():
    from tracker.gear.native import capture, merge, record

    with capture() as evidence:
        record("native_request", roles=("ranged",))
        before = evidence.snapshot()
        merge({"events": [{"event": "fallback", "reason": "running_cost_lane"}]})
    assert before["fallback_requests"] == 0
    assert evidence.snapshot()["native_requests"] == 1
    assert evidence.snapshot()["fallback_requests"] == 1


def test_native_stage_chunk_accounting_and_cancellation(monkeypatch):
    import sys
    from types import SimpleNamespace

    from tracker.gear.native.adapter import expand

    sizes = []
    reports = []

    class Stage:
        done = False

        def advance(self, count):
            sizes.append(count)
            return count

        def finish(self, limit):
            return [{"weapon": 1}]

    stage = Stage()
    module = SimpleNamespace(StageContext=lambda *_: SimpleNamespace(begin=lambda **kwargs: stage))
    monkeypatch.setitem(sys.modules, "tracker.gear.native._stages", module)
    search = SimpleNamespace(
        native_context=object(),
        nodes=1000,
        native_limit=2200,
        cancelled=None,
        native_report=lambda: reports.append(search.nodes),
    )
    result = expand(search, "loadout", [{}], [1], roles=(), limit=1)
    assert sizes == [24, 1024, 152]
    assert reports == [1024, 2048]
    assert search.nodes == 2200
    assert result == [{"weapon": 1}]
    search.cancelled = lambda: True
    with pytest.raises(ValueError, match="optimization_cancelled"):
        expand(search, "loadout", [{}], [1], roles=(), limit=1)


def test_native_stage_must_make_progress(monkeypatch):
    import sys
    from types import SimpleNamespace

    from tracker.gear.native.adapter import expand

    stage = SimpleNamespace(done=False, advance=lambda _: 0)
    module = SimpleNamespace(StageContext=lambda *_: SimpleNamespace(begin=lambda **kw: stage))
    monkeypatch.setitem(sys.modules, "tracker.gear.native._stages", module)
    search = SimpleNamespace(native_context=object(), nodes=0, native_limit=10, cancelled=None)
    with pytest.raises(RuntimeError, match="no progress"):
        expand(search, "loadout", [{}], [1], roles=(), limit=1)


def test_expansion_does_not_reuse_stages_from_an_unreset_copy(monkeypatch):
    import sys
    from copy import copy
    from types import SimpleNamespace

    from tracker.gear.native.adapter import expand

    owners = []
    stage = SimpleNamespace(done=True, finish=lambda limit: [])

    def context(scoring, search):
        owners.append(search)
        return SimpleNamespace(begin=lambda **kw: stage)

    monkeypatch.setitem(
        sys.modules, "tracker.gear.native._stages", SimpleNamespace(StageContext=context)
    )
    search = SimpleNamespace(native_context=object(), nodes=0, native_limit=10, cancelled=None)
    expand(search, "loadout", [{}], [], limit=1)
    clone = copy(search)
    expand(clone, "loadout", [{}], [], limit=1)
    assert len(owners) == 2
    assert owners[0] is search
    assert owners[1] is clone
