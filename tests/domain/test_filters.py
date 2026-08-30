"""Specification for the pure filter predicates in `jmacat.domain.filters`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jmacat.domain.filters import (
    BoundingBox,
    FilterError,
    NaiveDatetimeError,
    UnknownAreaError,
    available_area_names,
    bounding_box,
    depth_range,
    magnitude_range,
    named_area,
    time_range,
)

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


def test_magnitude_range_admits_an_event_inside_the_range() -> None:
    predicate = magnitude_range(minimum=3.0, maximum=7.0)
    assert predicate(event(magnitude=6.5)) is True


def test_magnitude_range_rejects_an_event_below_the_range() -> None:
    predicate = magnitude_range(minimum=3.0)
    assert predicate(event(magnitude=0.3)) is False


def test_magnitude_range_rejects_an_event_above_the_range() -> None:
    predicate = magnitude_range(maximum=3.0)
    assert predicate(event(magnitude=6.5)) is False


def test_magnitude_range_is_inclusive_of_both_boundaries() -> None:
    """ "M3.0 and above" must admit an M3.0 record; the range is closed."""
    assert magnitude_range(minimum=3.0)(event(magnitude=3.0)) is True
    assert magnitude_range(maximum=3.0)(event(magnitude=3.0)) is True


def test_magnitude_range_admits_a_negative_magnitude_in_range() -> None:
    """The catalog really does hold negative magnitudes: `h2023` carries
    M-0.6 (example C in docs/jma-hypocenter-format.md) and M-1.0 (example D).
    """
    assert magnitude_range(minimum=-1.0, maximum=0.0)(event(magnitude=-0.6)) is True


def test_magnitude_range_excludes_an_event_with_no_magnitude() -> None:
    """Policy: an active magnitude filter excludes a record whose magnitude is
    unknown. 9,973 of 257,020 `h2023` records and 11,621 of 28,235 `h1919`
    records have a blank magnitude field, so this is not a corner case.
    """
    predicate = magnitude_range(minimum=3.0)
    assert predicate(event(magnitude=None)) is False


def test_magnitude_range_excludes_a_missing_magnitude_for_an_upper_bound_too() -> None:
    """The policy is about the filter being active, not about which side is
    bounded: an unknown magnitude cannot be shown to be below a maximum either.
    """
    predicate = magnitude_range(maximum=3.0)
    assert predicate(event(magnitude=None)) is False


def test_magnitude_range_with_no_bounds_admits_a_missing_magnitude() -> None:
    """An unbounded magnitude filter is not an active filter, so it asserts
    nothing about the magnitude and must not drop records.
    """
    assert magnitude_range()(event(magnitude=None)) is True


def test_depth_range_admits_an_event_inside_the_range() -> None:
    predicate = depth_range(minimum_km=0.0, maximum_km=70.0)
    assert predicate(event(depth_km=50.0)) is True


def test_depth_range_rejects_a_deeper_event() -> None:
    """`h2023` example E is a 105 km TANIMBAR IS. event; a shallow-only filter
    must not admit it.
    """
    predicate = depth_range(maximum_km=70.0)
    assert predicate(event(depth_km=105.0)) is False


def test_depth_range_rejects_a_shallower_event() -> None:
    predicate = depth_range(minimum_km=70.0)
    assert predicate(event(depth_km=26.45)) is False


def test_depth_range_is_inclusive_of_both_boundaries() -> None:
    assert depth_range(maximum_km=50.0)(event(depth_km=50.0)) is True
    assert depth_range(minimum_km=50.0)(event(depth_km=50.0)) is True


def test_depth_range_admits_a_zero_depth_event() -> None:
    """`h1919` line 1130, the 1923 Kanto earthquake, carries depth 0 km. Zero
    is a real depth, not a missing value, and a `minimum_km=0.0` filter must
    admit it rather than treating the falsy value as absent.
    """
    assert depth_range(minimum_km=0.0)(event(depth_km=0.0)) is True


def test_depth_range_excludes_an_event_with_no_depth() -> None:
    """Same policy as magnitude: an active depth filter excludes a record
    whose depth is unknown.
    """
    assert depth_range(maximum_km=70.0)(event(depth_km=None)) is False


def test_depth_range_with_no_bounds_admits_a_missing_depth() -> None:
    assert depth_range()(event(depth_km=None)) is True


def test_bounding_box_admits_an_event_inside_the_box() -> None:
    box = BoundingBox(
        south=35.0, north=36.0, west=140.0, east=141.0, description="test"
    )
    assert bounding_box(box)(event()) is True


def test_bounding_box_rejects_an_event_north_of_the_box() -> None:
    box = BoundingBox(
        south=35.0, north=36.0, west=140.0, east=141.0, description="test"
    )
    assert bounding_box(box)(event(latitude=41.1705)) is False


def test_bounding_box_rejects_an_event_east_of_the_box() -> None:
    box = BoundingBox(
        south=35.0, north=36.0, west=140.0, east=141.0, description="test"
    )
    assert bounding_box(box)(event(longitude=142.931833)) is False


def test_bounding_box_edges_are_inclusive() -> None:
    """All four edges are closed: a record exactly on a corner is inside."""
    box = BoundingBox(
        south=35.0, north=36.0, west=140.0, east=141.0, description="test"
    )
    predicate = bounding_box(box)
    for lat, lon in ((35.0, 140.0), (36.0, 141.0), (35.0, 141.0), (36.0, 140.0)):
        assert predicate(event(latitude=lat, longitude=lon)) is True


def test_bounding_box_admits_a_southern_hemisphere_event() -> None:
    """`h2023` example E, TANIMBAR IS., INDONESIA at 7.058667 degS."""
    box = BoundingBox(
        south=-10.0, north=-5.0, west=129.0, east=131.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-7.058667, longitude=130.009)) is True


def test_bounding_box_crossing_the_antimeridian_admits_a_western_event() -> None:
    """A box with `west > east` is read as crossing +/-180.

    `h2023` holds the Kermadec-Tonga-Fiji cluster on both sides of the
    antimeridian: 18 records carry a negative longitude (example F,
    KERMADEC ISL., N.Z.L. at -178.661500) while others sit at +178 and +179.
    A box for that cluster cannot be written with `west < east`.
    """
    box = BoundingBox(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-30.2115, longitude=-178.6615)) is True


def test_bounding_box_crossing_the_antimeridian_admits_an_eastern_event() -> None:
    """The same box admits the positive-longitude half of the cluster:
    `h2023` has SOUTH OF FIJI records at +178 and +179.
    """
    box = BoundingBox(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-25.0, longitude=178.5)) is True


def test_bounding_box_crossing_the_antimeridian_rejects_the_gap() -> None:
    """The crossing box covers 175 -> 180 -> -175, not its complement. A
    longitude of 0 is in the excluded 355 degrees and must be rejected.
    """
    box = BoundingBox(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-25.0, longitude=0.0)) is False


def test_bounding_box_rejects_a_south_edge_above_its_north_edge() -> None:
    """Latitude has no wraparound, so `south > north` is a caller mistake,
    not a crossing box. It is refused rather than silently matching nothing.
    """
    with pytest.raises(FilterError):
        BoundingBox(south=36.0, north=35.0, west=140.0, east=141.0, description="test")


def test_bounding_box_rejects_an_out_of_range_coordinate() -> None:
    with pytest.raises(FilterError):
        BoundingBox(
            south=-100.0, north=35.0, west=140.0, east=141.0, description="test"
        )
    with pytest.raises(FilterError):
        BoundingBox(south=35.0, north=36.0, west=140.0, east=200.0, description="test")


def test_named_area_resolves_ishikawa_to_a_bounding_box() -> None:
    """The box is the land extent of Ishikawa prefecture, from the four
    extreme points published by the prefecture (sourced to GSI, World Geodetic
    System): N 37 deg 51'28" (Hegurajima), S 36 deg 04'01" (Mt Akatsuka),
    E 137 deg 21'55" (Himejima), W 136 deg 14'35" (Shioya fishing port).
    <https://www.pref.ishikawa.lg.jp/kensei/koho/gaiyo/p0.html>
    """
    box = named_area("ishikawa")
    assert box.north == pytest.approx(37 + 51 / 60 + 28 / 3600)
    assert box.south == pytest.approx(36 + 4 / 60 + 1 / 3600)
    assert box.east == pytest.approx(137 + 21 / 60 + 55 / 3600)
    assert box.west == pytest.approx(136 + 14 / 60 + 35 / 3600)


def test_named_area_lookup_is_case_insensitive_and_trims_whitespace() -> None:
    assert named_area("  Ishikawa ") == named_area("ishikawa")


def test_named_area_rejects_an_unknown_name() -> None:
    """An unknown name raises rather than resolving to an empty box, which
    would silently return zero events and look like "no earthquakes there".
    """
    with pytest.raises(UnknownAreaError):
        named_area("atlantis")


def test_unknown_area_error_lists_the_available_names() -> None:
    with pytest.raises(UnknownAreaError) as excinfo:
        named_area("atlantis")
    assert "ishikawa" in str(excinfo.value)


def test_named_area_box_description_states_it_is_an_approximation() -> None:
    """A user filtering "ishikawa" must not believe they got a prefecture
    boundary. The approximation is visible in the API, not only in the docs.
    """
    description = named_area("ishikawa").description
    assert "approximate" in description.lower()
    assert "pref.ishikawa.lg.jp" in description


def test_named_area_ishikawa_admits_the_2023_noto_peninsula_event() -> None:
    """`h2023` example H is NOTO PENINSULA REGION at 37 deg 32.34' N,
    137 deg 18.27' E - inside the prefecture's extent.
    """
    predicate = bounding_box(named_area("ishikawa"))
    noto = event(latitude=37 + 32.34 / 60, longitude=137 + 18.27 / 60)
    assert predicate(noto) is True


def test_named_area_ishikawa_rejects_a_chiba_event() -> None:
    """`h2023` line 1, NEAR CHOSHI CITY at 35.676500N 140.654500E."""
    predicate = bounding_box(named_area("ishikawa"))
    assert predicate(event()) is False


def test_available_area_names_are_sorted_and_include_ishikawa() -> None:
    names = available_area_names()
    assert "ishikawa" in names
    assert list(names) == sorted(names)
