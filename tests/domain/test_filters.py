"""Specification for the pure filter predicates in `jmacat.domain.filters`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jmacat.domain.filters import NaiveDatetimeError, time_range

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


def test_time_range_rejects_a_naive_start_bound() -> None:
    """Catalog times are JST (UTC+9). A naive bound would silently shift the
    window by 9 hours against a JST origin time, so it is refused outright.
    """
    with pytest.raises(NaiveDatetimeError):
        time_range(start=datetime(2023, 1, 1, 0, 0))


def test_time_range_rejects_a_naive_end_bound() -> None:
    with pytest.raises(NaiveDatetimeError):
        time_range(end=datetime(2023, 1, 2, 0, 0))


def test_time_range_compares_across_time_zones_by_absolute_instant() -> None:
    """Bounds need not be JST; an aware bound in any zone is compared by
    instant. 2023-01-01 00:00 JST is 2022-12-31 15:00 UTC.
    """
    predicate = time_range(
        start=datetime(2022, 12, 31, 15, 0, tzinfo=UTC),
        end=datetime(2022, 12, 31, 15, 30, tzinfo=UTC),
    )
    at_start = event(origin_time=datetime(2023, 1, 1, 0, 0, tzinfo=JST))
    assert predicate(at_start) is True


def test_time_range_rejects_an_event_whose_origin_time_is_naive() -> None:
    """A naive origin time cannot be compared to an aware bound: Python raises
    `TypeError`. Raising the filter's own error instead names the real cause.
    """
    predicate = time_range(start=datetime(2023, 1, 1, 0, 0, tzinfo=JST))
    with pytest.raises(NaiveDatetimeError):
        predicate(event(origin_time=datetime(2023, 6, 1, 0, 0)))
