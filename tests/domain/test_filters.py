"""Specification for the pure filter predicates in `jmacat.domain.filters`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from jmacat.domain.filters import time_range

JST = timezone(timedelta(hours=9), "JST")


@dataclass(frozen=True)
class StubEvent:
    """A stand-in satisfying `FilterableEvent` structurally.

    Dev-D's real value object (issues #3/#4) is not on `main` yet; the filters
    are written against a Protocol, so this stub exercises the same contract.
    """

    origin_time: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None


def event(
    *,
    origin_time: datetime = datetime(2023, 1, 1, 0, 8, 1, 500000, tzinfo=JST),
    latitude: float = 35.6765,
    longitude: float = 140.6545,
    depth_km: float | None = 50.0,
    magnitude: float | None = 0.3,
) -> StubEvent:
    """An event defaulting to `h2023` line 1, NEAR CHOSHI CITY."""
    return StubEvent(origin_time, latitude, longitude, depth_km, magnitude)


def test_time_range_admits_an_event_inside_the_window() -> None:
    predicate = time_range(
        start=datetime(2023, 1, 1, 0, 0, tzinfo=JST),
        end=datetime(2023, 1, 2, 0, 0, tzinfo=JST),
    )
    assert predicate(event()) is True


def test_time_range_rejects_an_event_before_the_window() -> None:
    predicate = time_range(
        start=datetime(2023, 1, 1, 0, 0, tzinfo=JST),
        end=datetime(2023, 1, 2, 0, 0, tzinfo=JST),
    )
    before = event(origin_time=datetime(2022, 12, 31, 23, 59, tzinfo=JST))
    assert predicate(before) is False


def test_time_range_rejects_an_event_after_the_window() -> None:
    predicate = time_range(
        start=datetime(2023, 1, 1, 0, 0, tzinfo=JST),
        end=datetime(2023, 1, 2, 0, 0, tzinfo=JST),
    )
    after = event(origin_time=datetime(2023, 1, 2, 0, 1, tzinfo=JST))
    assert predicate(after) is False


def test_time_range_is_inclusive_of_its_start_boundary() -> None:
    """A record exactly on `start` is admitted: the range is closed."""
    start = datetime(2023, 1, 1, 0, 0, tzinfo=JST)
    predicate = time_range(start=start, end=datetime(2023, 1, 2, 0, 0, tzinfo=JST))
    assert predicate(event(origin_time=start)) is True


def test_time_range_is_inclusive_of_its_end_boundary() -> None:
    """A record exactly on `end` is admitted: the range is closed."""
    end = datetime(2023, 1, 2, 0, 0, tzinfo=JST)
    predicate = time_range(start=datetime(2023, 1, 1, 0, 0, tzinfo=JST), end=end)
    assert predicate(event(origin_time=end)) is True
