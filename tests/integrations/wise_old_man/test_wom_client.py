"""Wise Old Man client tests (§7.2), including G5's negative-sentinel normalization.

The mocked ``GET /players/{username}`` response shape matches what was verified
against the live API at implementation time (see the module docstring of
``tracker.integrations.wise_old_man.client``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from tracker.config.settings import WiseOldManSettings
from tracker.domain.types import Source
from tracker.integrations.wise_old_man.client import WiseOldManClient

_FIXED_NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _client(handler: httpx.MockTransport) -> WiseOldManClient:
    return WiseOldManClient(
        WiseOldManSettings(), transport=handler, sleep=lambda _: None, clock=lambda: _FIXED_NOW
    )


def _response(skills: dict[str, object], activities: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "latestSnapshot": {
                "createdAt": "2026-08-04T06:12:03.602Z",
                "data": {"skills": skills, "activities": activities},
            }
        },
    )


class TestG5NegativeOneNormalizesToNone:
    """G5: Hiscores/WOM `-1` normalizes to `None` at the adapter boundary, never `0`."""

    def test_unranked_skill_xp_becomes_none_not_zero(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={
                    "overall": {"metric": "overall", "experience": 100, "rank": 1, "level": 50},
                    "hunter": {"metric": "hunter", "experience": -1, "rank": -1, "level": 1},
                },
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")

        hunter = next(s for s in snapshot.skills if s.skill == "hunter")
        assert hunter.xp is None
        assert hunter.xp != 0

    def test_ranked_skill_xp_passes_through_unchanged(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={
                    "overall": {"metric": "overall", "experience": 100, "rank": 1, "level": 50},
                    "magic": {
                        "metric": "magic",
                        "experience": 13_034_431,
                        "rank": 45213,
                        "level": 94,
                    },
                },
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")

        magic = next(s for s in snapshot.skills if s.skill == "magic")
        assert magic.xp == 13_034_431
        assert magic.level == 94

    def test_unranked_lms_score_becomes_none_not_zero(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={},
                activities={
                    "last_man_standing": {"metric": "last_man_standing", "score": -1, "rank": -1}
                },
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")

        assert snapshot.lms_score is None

    def test_ranked_lms_score_passes_through_unchanged(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={},
                activities={
                    "last_man_standing": {
                        "metric": "last_man_standing",
                        "score": 1204,
                        "rank": 8213,
                    }
                },
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")

        assert snapshot.lms_score == 1204


class TestPlayerFetch:
    def test_runecrafting_metric_uses_canonical_runecraft_skill(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={
                    "runecrafting": {
                        "metric": "runecrafting",
                        "experience": 4470,
                        "rank": 1,
                        "level": 20,
                    }
                },
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("Rehvun")

        assert len(snapshot.skills) == 1
        assert snapshot.skills[0].skill == "runecraft"
        assert snapshot.skills[0].source is Source.WISE_OLD_MAN

    def test_duplicate_provider_alias_prefers_native_runecraft_metric(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={
                    "runecrafting": {"metric": "runecrafting", "experience": 4470, "level": 20},
                    "runecraft": {"metric": "runecraft", "experience": 5018, "level": 21},
                },
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("Rehvun")

        assert [(skill.skill, skill.level, skill.xp) for skill in snapshot.skills] == [
            ("runecraft", 21, 5018)
        ]

    def test_overall_is_excluded_from_the_skill_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={
                    "overall": {"metric": "overall", "experience": 100, "rank": 1, "level": 50}
                },
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")

        assert all(s.skill != "overall" for s in snapshot.skills)

    def test_source_is_always_wise_old_man(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _response(
                skills={"magic": {"metric": "magic", "experience": 100, "rank": 1, "level": 10}},
                activities={},
            )

        client = _client(httpx.MockTransport(handler))
        snapshot = client.player("zezima")
        assert all(s.source is Source.WISE_OLD_MAN for s in snapshot.skills)

    def test_username_is_the_only_thing_sent_upstream(self) -> None:
        """§11.6: outbound requests carry only what the provider needs — a username."""
        seen_requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_requests.append(request)
            return _response(skills={}, activities={})

        client = _client(httpx.MockTransport(handler))
        client.player("Zezima Two")

        assert len(seen_requests) == 1
        request = seen_requests[0]
        assert request.url.path.endswith("/players/Zezima Two")
        assert not request.url.params  # no extra query parameters
        assert request.content == b""  # no request body
