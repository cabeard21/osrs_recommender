import pytest

from tracker.gear.ammo import mark_frontier, recovery_rate, running_cost


@pytest.mark.parametrize("cape,lost", [(None, 2000), (10498, 800), (10499, 560), (22109, 400)])
def test_three_tick_replacement(cape, lost):
    rate, _ = recovery_rate(cape, None)
    result = running_cost(1.8, 5, rate, 100)
    assert result["arrows_lost_per_hour"] == pytest.approx(lost)
    assert result["gp_per_hour"] == pytest.approx(lost * 100)
    assert result["gp_per_damage"] == pytest.approx(lost * 100 / 18000)


def test_unknown_price_and_zero_damage():
    assert running_cost(1.8, 0, 0.8, None)["gp_per_hour"] is None
    assert running_cost(1.8, 0, 0.8, 100)["gp_per_damage"] is None
    assert running_cost(None, 1, 0.8, 100)["arrows_lost_per_hour"] is None


def test_recovery_interference_and_unknown():
    assert recovery_rate(10499, 1127)[0] == 0
    assert recovery_rate(10499, 2503)[0] == 0.72
    assert recovery_rate(10499, 999999)[0] is None
    assert recovery_rate(28947, None)[0] is None
    assert recovery_rate(None, 999999)[0] == 0


@pytest.mark.parametrize(
    "body",
    [
        11855,
        13584,
        1135,
        2499,
        2501,
        2503,
        7362,
        7374,
        12381,
        12492,
        10370,
        10378,
        10386,
        12500,
        12508,
        23264,
        11828,
        4736,
        4944,
        8839,
        13072,
        27000,
        27003,
        27229,
        27238,
        23975,
        27769,
        27771,
        29004,
        29013,
        29022,
        30076,
        29280,
        1103,
        1117,
        6615,
        6617,
        12235,
        20169,
        12277,
        23366,
        23392,
        23209,
        12460,
        12470,
        12480,
        11832,
        10551,
        10564,
        26384,
        24420,
        28936,
        6322,
        21021,
    ],
)
def test_compatible_body_coverage(body):
    for cape, expected in [(10498, 0.60), (10499, 0.72), (22109, 0.80)]:
        assert recovery_rate(cape, body) == (expected, [])


@pytest.mark.parametrize(
    "body",
    [
        1101,
        1105,
        1107,
        1109,
        1111,
        1113,
        1115,
        1119,
        1121,
        1123,
        1125,
        1127,
        2591,
        2583,
        2607,
        2599,
        2615,
        2623,
        2669,
        2661,
        2653,
        3140,
        21892,
        22327,
        4712,
        4868,
        4872,
        4720,
        4896,
        4728,
        4920,
        4749,
        4968,
        4757,
        4992,
    ],
)
def test_interfering_body_coverage(body):
    rate, reasons = recovery_rate(10499, body)
    assert rate == 0
    assert reasons


@pytest.mark.parametrize("body", [27845, 27842, 27851, 27837, 22641, 999999])
def test_unreviewed_body_remains_unknown(body):
    rate, reasons = recovery_rate(10499, body)
    assert rate is None
    assert reasons


def test_reviewed_body_ids_are_disjoint_physical_body_forms():
    import json
    from pathlib import Path

    from tracker.gear.ammo_armour import COMPATIBLE_BODIES, INTERFERING_BODIES

    rows = json.loads(Path("content/equipment/catalog.json").read_text(encoding="utf-8"))
    bodies = {row["id"] for row in rows if row["slot"] == "body"}
    assert not COMPATIBLE_BODIES.intersection(INTERFERING_BODIES)
    assert (COMPATIBLE_BODIES | INTERFERING_BODIES) <= bodies


def test_frontier_keeps_ties_and_unknown_cost_off_frontier():
    points = [
        {"dps": d, "gp_per_hour": g, "reasons": []}
        for d, g in [(5, 100), (5, 100), (4, 120), (6, None), (6, 200)]
    ]
    assert [p["frontier"] for p in mark_frontier(points)] == [True, True, False, False, True]
    assert "frontier" not in points[0]
