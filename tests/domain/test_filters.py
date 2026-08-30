"""Specification for the pure filter predicates in `jmacat.domain.filters`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from jmacat.domain.filters import (
    NAMED_AREAS,
    Bound,
    FilterableEvent,
    FilterError,
    NaiveDatetimeError,
    UnknownAreaError,
    _as_decimal,
    _dms,
    all_of,
    available_area_names,
    bounding_box,
    build_box,
    depth_range,
    magnitude_range,
    named_area,
    time_range,
)

JST = timezone(timedelta(hours=9), "JST")


@dataclass(frozen=True)
class StubEvent:
    """A stand-in satisfying `FilterableEvent` structurally.

    The measurements are `Decimal`, matching the real `Hypocenter`; see
    `test_hypocenter_satisfies_filterable_event`, which makes mypy prove the
    two agree. A stub that kept `float` here would type-check against the
    Protocol while the real record did not -- the defect this file now guards
    against.
    """

    origin_time: datetime
    latitude: Decimal
    longitude: Decimal
    depth_km: Decimal | None
    magnitude: Decimal | None


def event(
    *,
    origin_time: datetime = datetime(2023, 1, 1, 0, 8, 1, 500000, tzinfo=JST),
    latitude: Bound = Decimal("35.6765"),
    longitude: Bound = Decimal("140.6545"),
    depth_km: Bound | None = Decimal(50),
    magnitude: Bound | None = Decimal("0.3"),
) -> StubEvent:
    """An event defaulting to `h2023` line 1, NEAR CHOSHI CITY.

    Accepts plain numbers for brevity at the call sites and normalises them,
    so a test may write `magnitude=3.0` and still hold an exact value.
    """
    return StubEvent(
        origin_time,
        _as_decimal(latitude),
        _as_decimal(longitude),
        None if depth_km is None else _as_decimal(depth_km),
        None if magnitude is None else _as_decimal(magnitude),
    )


def to_six_places(value: Decimal) -> Decimal:
    """Round to the six decimals the published extents are quoted to.

    `_dms` returns an exact `Decimal`, and a DMS angle whose seconds are not a
    multiple of 3.6 does not terminate -- 37 deg 51' 28" is
    37.857777... forever. Comparing at the precision of the cited figure is
    therefore the honest assertion; `pytest.approx` cannot be used because it
    subtracts a float from a `Decimal`.
    """
    return value.quantize(Decimal("0.000001"))


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
    box = build_box(south=35.0, north=36.0, west=140.0, east=141.0, description="test")
    assert bounding_box(box)(event()) is True


def test_bounding_box_rejects_an_event_north_of_the_box() -> None:
    box = build_box(south=35.0, north=36.0, west=140.0, east=141.0, description="test")
    assert bounding_box(box)(event(latitude=41.1705)) is False


def test_bounding_box_rejects_an_event_east_of_the_box() -> None:
    box = build_box(south=35.0, north=36.0, west=140.0, east=141.0, description="test")
    assert bounding_box(box)(event(longitude=142.931833)) is False


def test_bounding_box_edges_are_inclusive() -> None:
    """All four edges are closed: a record exactly on a corner is inside."""
    box = build_box(south=35.0, north=36.0, west=140.0, east=141.0, description="test")
    predicate = bounding_box(box)
    for lat, lon in ((35.0, 140.0), (36.0, 141.0), (35.0, 141.0), (36.0, 140.0)):
        assert predicate(event(latitude=lat, longitude=lon)) is True


def test_bounding_box_admits_a_southern_hemisphere_event() -> None:
    """`h2023` example E, TANIMBAR IS., INDONESIA at 7.058667 degS."""
    box = build_box(south=-10.0, north=-5.0, west=129.0, east=131.0, description="test")
    assert bounding_box(box)(event(latitude=-7.058667, longitude=130.009)) is True


def test_bounding_box_crossing_the_antimeridian_admits_a_western_event() -> None:
    """A box with `west > east` is read as crossing +/-180.

    `h2023` holds the Kermadec-Tonga-Fiji cluster on both sides of the
    antimeridian: 18 records carry a negative longitude (example F,
    KERMADEC ISL., N.Z.L. at -178.661500) while others sit at +178 and +179.
    A box for that cluster cannot be written with `west < east`.
    """
    box = build_box(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-30.2115, longitude=-178.6615)) is True


def test_bounding_box_crossing_the_antimeridian_admits_an_eastern_event() -> None:
    """The same box admits the positive-longitude half of the cluster:
    `h2023` has SOUTH OF FIJI records at +178 and +179.
    """
    box = build_box(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-25.0, longitude=178.5)) is True


def test_bounding_box_crossing_the_antimeridian_rejects_the_gap() -> None:
    """The crossing box covers 175 -> 180 -> -175, not its complement. A
    longitude of 0 is in the excluded 355 degrees and must be rejected.
    """
    box = build_box(
        south=-40.0, north=-15.0, west=175.0, east=-175.0, description="test"
    )
    assert bounding_box(box)(event(latitude=-25.0, longitude=0.0)) is False


def test_bounding_box_rejects_a_south_edge_above_its_north_edge() -> None:
    """Latitude has no wraparound, so `south > north` is a caller mistake,
    not a crossing box. It is refused rather than silently matching nothing.
    """
    with pytest.raises(FilterError):
        build_box(south=36.0, north=35.0, west=140.0, east=141.0, description="test")


def test_bounding_box_rejects_an_out_of_range_coordinate() -> None:
    with pytest.raises(FilterError):
        build_box(south=-100.0, north=35.0, west=140.0, east=141.0, description="test")
    with pytest.raises(FilterError):
        build_box(south=35.0, north=36.0, west=140.0, east=200.0, description="test")


def test_named_area_resolves_ishikawa_to_a_bounding_box() -> None:
    """The box is the land extent of Ishikawa prefecture, from the four
    extreme points published by the prefecture (sourced to GSI, World Geodetic
    System): N 37 deg 51'28" (Hegurajima), S 36 deg 04'01" (Mt Akatsuka),
    E 137 deg 21'55" (Himejima), W 136 deg 14'35" (Shioya fishing port).
    <https://www.pref.ishikawa.lg.jp/kensei/koho/gaiyo/p0.html>
    """
    box = named_area("ishikawa")
    assert to_six_places(box.north) == Decimal("37.857778")
    assert to_six_places(box.south) == Decimal("36.066944")
    assert to_six_places(box.east) == Decimal("137.365278")
    assert to_six_places(box.west) == Decimal("136.243056")


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


def test_all_of_requires_every_predicate_to_pass() -> None:
    predicate = all_of(magnitude_range(minimum=3.0), depth_range(maximum_km=70.0))
    assert predicate(event(magnitude=6.5, depth_km=50.0)) is True
    assert predicate(event(magnitude=0.3, depth_km=50.0)) is False
    assert predicate(event(magnitude=6.5, depth_km=105.0)) is False


def test_all_of_with_no_predicates_admits_everything() -> None:
    """Every filter is optional, so composing none of them is the identity."""
    assert all_of()(event()) is True


def test_all_of_short_circuits_on_the_first_rejection() -> None:
    """A composed filter runs over 257,000 records, so a later predicate must
    not be evaluated once one has already rejected the event.
    """
    calls: list[str] = []

    def reject(_: FilterableEvent) -> bool:
        calls.append("reject")
        return False

    def record(_: FilterableEvent) -> bool:
        calls.append("record")
        return True

    assert all_of(reject, record)(event()) is False
    assert calls == ["reject"]


def test_all_of_composes_the_whole_issue_example() -> None:
    """ "M3.0 and above near Ishikawa in 2023" - the outcome issue #10 names."""
    predicate = all_of(
        time_range(
            start=datetime(2023, 1, 1, 0, 0, tzinfo=JST),
            end=datetime(2023, 12, 31, 23, 59, 59, 999999, tzinfo=JST),
        ),
        magnitude_range(minimum=3.0),
        bounding_box(named_area("ishikawa")),
    )
    noto = event(
        origin_time=datetime(2023, 5, 5, 14, 42, 4, 100000, tzinfo=JST),
        latitude=37 + 32.34 / 60,
        longitude=137 + 18.27 / 60,
        depth_km=12.14,
        magnitude=6.5,
    )
    assert predicate(noto) is True

    too_small = event(
        origin_time=datetime(2023, 5, 5, 14, 42, 4, 100000, tzinfo=JST),
        latitude=37 + 32.34 / 60,
        longitude=137 + 18.27 / 60,
        magnitude=0.3,
    )
    assert predicate(too_small) is False


# --- _dms: DMS to signed decimal degrees ------------------------------------


def test_dms_converts_a_northern_hemisphere_extent() -> None:
    """Ishikawa's north extent, 37 deg 51' 28" N, published by the prefecture
    (source: GSI). 37 + 51/60 + 28/3600 = 37.858(3).
    """
    assert to_six_places(_dms(37, 51, 28)) == Decimal("37.857778")


def test_dms_converts_an_eastern_hemisphere_extent() -> None:
    """Ishikawa's west extent, 136 deg 14' 35" E. 136 + 14/60 + 35/3600."""
    assert to_six_places(_dms(136, 14, 35)) == Decimal("136.243056")


def test_dms_applies_the_sign_to_minutes_and_seconds_in_the_south() -> None:
    """A southern latitude is a whole magnitude negated, not a negative degree
    with positive minutes added back.

    30 deg 12' 41" S is -30.211389, not -29.788611; the two differ by 0.42 deg,
    about 47 km of latitude. `h2023` holds real southern-hemisphere records
    (the Kermadec-Tonga-Fiji cluster), so a `NAMED_AREAS` box drawn there must
    not be silently 47 km out.
    """
    assert to_six_places(_dms(30, 12, 41, negative=True)) == Decimal("-30.211389")


def test_dms_applies_the_sign_to_minutes_and_seconds_in_the_west() -> None:
    """7 deg 3' 31" W is -7.058611, not -6.941389 - about 13 km of longitude
    at the equator.
    """
    assert to_six_places(_dms(7, 3, 31, negative=True)) == Decimal("-7.058611")


def test_dms_expresses_a_coordinate_just_south_of_the_equator() -> None:
    """-0 deg 30' is a real coordinate half a degree south of the equator.

    It cannot be written by negating the degrees term: Python's `int` has no
    negative zero, so `-0 == 0`. The `negative=` flag carries the hemisphere
    independently of the degrees value, which is what makes this case
    expressible at all.
    """
    assert _dms(0, 30, 0, negative=True) == Decimal("-0.5")
    assert _dms(0, 30, 0) == Decimal("0.5")


def test_dms_rejects_a_negative_degrees_argument() -> None:
    """Negative degrees are refused rather than interpreted, because `-0`
    cannot express the southern side of the equator. The error must name the
    constraint and the replacement.
    """
    with pytest.raises(FilterError) as excinfo:
        _dms(-30, 12, 41)
    message = str(excinfo.value)
    assert "negative=True" in message
    assert "-0" in message


def test_dms_rejects_negative_minutes_or_seconds() -> None:
    """Minutes and seconds are magnitudes; a sign on them is a caller mistake
    that would otherwise subtract from the degrees term.
    """
    with pytest.raises(FilterError):
        _dms(30, -12, 41)
    with pytest.raises(FilterError):
        _dms(30, 12, -41)


# --- documented box edge semantics ------------------------------------------


def test_bounding_box_with_west_equal_to_east_is_a_zero_width_meridian() -> None:
    """`west == east` is neither crossing nor an error: the edges are
    inclusive, so the box admits exactly that one longitude and nothing else.
    It is the longitude counterpart of `south == north` selecting a parallel.
    """
    meridian = build_box(
        south=36.0, north=38.0, west=137.0, east=137.0, description="Test meridian."
    )
    assert meridian.crosses_antimeridian is False
    assert meridian.contains(37.0, 137.0) is True
    assert meridian.contains(37.0, 137.000001) is False
    assert meridian.contains(37.0, 136.999999) is False


def test_a_non_crossing_box_ending_at_180_admits_only_the_positive_sign() -> None:
    """+180 and -180 name the same meridian but are different numbers, and a
    non-crossing box compares the numbers it is given.

    `h1919` line 23516 is a real record at exactly 180.000 deg E, so the
    distinction decides whether that record is found. A box meant to hold the
    meridian from both sides must cross it (`west=170, east=-170`).
    """
    eastern = build_box(
        south=-90.0, north=90.0, west=170.0, east=180.0, description="Test box."
    )
    assert eastern.contains(-21.0, 180.0) is True
    assert eastern.contains(-21.0, -180.0) is False

    western = build_box(
        south=-90.0, north=90.0, west=-180.0, east=-170.0, description="Test box."
    )
    assert western.contains(-21.0, -180.0) is True
    assert western.contains(-21.0, 180.0) is False

    crossing = build_box(
        south=-90.0, north=90.0, west=170.0, east=-170.0, description="Test box."
    )
    assert crossing.contains(-21.0, 180.0) is True
    assert crossing.contains(-21.0, -180.0) is True


def test_time_range_with_no_bounds_still_rejects_a_naive_origin_time() -> None:
    """The documented asymmetry with `magnitude_range` / `depth_range`: an
    unbounded measurement filter asserts nothing and drops nothing, but an
    unbounded `time_range()` still refuses a naive origin time, because that
    is a defect in the event rather than a fact about it.
    """
    naive = event(origin_time=datetime(2023, 1, 1, 0, 8, 1, 500000))
    with pytest.raises(NaiveDatetimeError):
        time_range()(naive)

    assert magnitude_range()(event(magnitude=None)) is True
    assert depth_range()(event(depth_km=None)) is True


def test_named_areas_cannot_be_mutated_from_outside() -> None:
    """Every box must cite its provenance, and `description` carries that
    citation. A plain module-level dict lets any importer insert an
    uncited box that `available_area_names` then advertises as if it were
    maintained here, so the mapping is read-only.
    """
    with pytest.raises(TypeError):
        NAMED_AREAS["atlantis"] = build_box(  # type: ignore[index]
            south=0.0, north=1.0, west=0.0, east=1.0, description="Uncited."
        )
    assert "atlantis" not in available_area_names()


# --- Conformance: the Protocol and the real value object ------------------
#
# PR #16 shipped filters written against `FilterableEvent` while the concrete
# record did not yet exist, and the Protocol guessed `float` for measurements
# the parser produces as `Decimal`. Every filter type-checked, every test
# passed, and `parse_record(...)` could not be handed to a single one of them.
# These tests exist so that can never be true again.

NEAR_CHOSHI = (
    "J2023010100080150 012 354059 100 1403927 136 50     03v   721   3110"
    "NEAR CHOSHI CITY          9A"
)
"""h2023 line 1, verbatim. The catalog itself is not committed (JMA terms)."""


def test_hypocenter_satisfies_filterable_event() -> None:
    """A real parsed record *is* a `FilterableEvent` -- proved by mypy.

    The assignment below is the test. mypy checks a concrete `Hypocenter`
    against the Protocol structurally, so if either side changes an attribute's
    name or type -- the parser widening `depth_km`, this module retyping
    `latitude` -- this file stops type-checking and CI fails, naming the
    attribute that drifted.

    The runtime assertions are secondary; they keep the test meaningful under
    plain pytest and pin the direction of the coupling, which is that the
    Protocol adapts to the parser rather than the reverse.
    """
    from jmacat.domain.hypocenter import parse_record

    probe: FilterableEvent = parse_record(NEAR_CHOSHI)

    assert isinstance(probe.latitude, Decimal)
    assert isinstance(probe.longitude, Decimal)
    assert isinstance(probe.magnitude, Decimal)
    assert probe.origin_time.utcoffset() is not None


def test_every_filter_accepts_a_real_parsed_record() -> None:
    """The filters run on a `Hypocenter`, not only on `StubEvent`.

    Conformance to the Protocol is a static claim; this is the runtime half.
    Each filter is applied to a real record whose values it should admit.
    """
    from jmacat.domain.hypocenter import parse_record

    record = parse_record(NEAR_CHOSHI)
    box = build_box(south=35, north=36, west=140, east=141, description="Test box.")
    predicate = all_of(
        time_range(
            start=datetime(2023, 1, 1, tzinfo=JST),
            end=datetime(2023, 1, 2, tzinfo=JST),
        ),
        magnitude_range(minimum=0.1),
        depth_range(minimum_km=0, maximum_km=100),
        bounding_box(box),
    )

    assert predicate(record) is True


# --- The float bound / Decimal value boundary -----------------------------


def test_a_float_bound_admits_a_record_lying_exactly_on_it() -> None:
    """`minimum=3.1` keeps an M3.1 record, though `Decimal("3.1") >= 3.1` is False.

    This is the regression test for the defect that made this branch's Protocol
    wrong. Record magnitudes are exact `Decimal`s; the literal `3.1` is a float
    a hair *above* three-point-one, so comparing the two directly rejects the
    record sitting on the bound -- exactly the record an inclusive range exists
    to keep. `magnitude_range` normalises the bound with `Decimal(str(...))`,
    so the filter means the decimal the caller wrote.
    """
    assert (Decimal("3.1") >= 3.1) is False, "the hazard this test guards"

    on_the_bound = event(magnitude=Decimal("3.1"))
    assert magnitude_range(minimum=3.1)(on_the_bound) is True
    assert magnitude_range(maximum=3.1)(on_the_bound) is True


def test_every_one_decimal_magnitude_bound_is_inclusive() -> None:
    """Exhaustive over M0.0-M9.9: a record on the bound is always kept.

    41 of these 100 bounds are float values that fall the wrong side of their
    own decimal, so a raw float comparison fails most of this range rather
    than a lucky few cases.
    """
    for tenths in range(100):
        bound = tenths / 10
        record = event(magnitude=Decimal(str(bound)))
        assert magnitude_range(minimum=bound)(record) is True, bound
        assert magnitude_range(maximum=bound)(record) is True, bound


def test_a_float_bound_still_excludes_a_record_below_it() -> None:
    """Normalising the bound must not make the filter admit everything."""
    assert magnitude_range(minimum=3.1)(event(magnitude=Decimal("3.0"))) is False
    assert magnitude_range(maximum=3.1)(event(magnitude=Decimal("3.2"))) is False


def test_a_bound_may_be_int_float_or_decimal() -> None:
    """All three spellings of the same limit behave identically."""
    record = event(magnitude=Decimal(3))
    for bound in (3, 3.0, Decimal("3.0")):
        assert magnitude_range(minimum=bound)(record) is True, bound
        assert magnitude_range(minimum=bound)(event(magnitude=Decimal("2.9"))) is False


def test_a_box_edge_given_as_a_float_admits_a_record_on_the_edge() -> None:
    """The same normalisation applies to the four box edges.

    A coordinate is `degrees + minutes/100/60`, which for two thirds of the
    possible minute values does not terminate; an edge written as a float
    would not equal the record's exact value.
    """
    edge = Decimal("137.1")
    box = build_box(south=36, north=38, west=137.1, east=138, description="Test box.")
    assert box.contains(Decimal(37), edge) is True


def test_depth_bounds_normalise_the_same_way() -> None:
    """Depth is `Decimal` too; its bounds go through the same door."""
    record = event(depth_km=Decimal("70.1"))
    assert depth_range(minimum_km=70.1)(record) is True
    assert depth_range(maximum_km=70.1)(record) is True
