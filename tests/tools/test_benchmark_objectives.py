"""Objective scaling evidence uses explicit fixtures and complete result digests."""

import pytest

from tools.benchmark_objectives import benchmark_case, objective_set, result_summary


@pytest.mark.parametrize("count", [1, 3, 8, 62])
def test_frozen_cohort_has_requested_canonical_dimensions(count):
    case = benchmark_case(count)
    assert len(case.catalog.items) == 119
    assert len(case.request.objectives) == count
    assert len({objective.id for objective in case.request.objectives}) == count
    assert case.request.secondary_priority == "default"
    assert case.snapshot.username == "redacted-search-regression"


def test_invalid_dimension_count_does_not_silently_substitute_workload():
    with pytest.raises(ValueError, match="Objective count"):
        objective_set(2)


def test_digest_checks_every_archived_solution_and_ignores_timing_observations():
    def result(last, duration):
        return {
            "selected_solution": {"score": 10, "timings_seconds": {"total": duration}},
            "unrestricted": None,
            "curve": [],
            "objective_frontiers": [
                {
                    "swap_limit": 0,
                    "points": (
                        {
                            "solution": {
                                "score": score,
                                "objective_values": {"prayer_bonus": 100 - score},
                            }
                        }
                        for score in [*range(79), last]
                    ),
                }
            ],
        }

    expected = result_summary(result(79, 1))
    assert expected == result_summary(result(79, 9))
    assert expected != result_summary(result(80, 1))
    assert expected["groups"][0]["count"] == 80
