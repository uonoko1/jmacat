"""Pure filter predicates over hypocenter events.

Each filter is a factory returning an `EventPredicate` — a pure function from
an event to whether it is kept. Filters compose with `all_of`, and every
filter is optional: an unwanted one is simply not passed.

Filters read events through the `FilterableEvent` Protocol, so they do not
depend on the concrete hypocenter value object.

Four conventions decide results and are therefore stated here rather than left
to the reader to infer; each is tested.

**Ranges are closed.** Every bound — time, magnitude, depth, and all four
edges of a bounding box — is inclusive. A record exactly on a limit is kept,
so `minimum=3.0` admits an M3.0 record, which is what "M3.0 and above" means.

**Missing values are excluded while their filter is active.** A record whose
magnitude or depth is `None` fails a bounded `magnitude_range` / `depth_range`
and passes an unbounded one. Blank fields are common — 9,973 of 257,020
`h2023` records carry no magnitude — so this is not a corner case. See
`_passes_optional_range`.

**Time bounds must be timezone-aware.** JMA origin times are JST (UTC+9); a
naive bound would shift the window by nine hours in silence, so it is refused.
Bounds in any zone are compared by absolute instant.

**A bounding box may cross the antimeridian**, written as `west > east`. The
catalog holds events on both sides of ±180. See `BoundingBox`.

Named areas (`named_area`) are **approximate rectangles, not boundaries**. See
`NAMED_AREAS` for the limitation and the provenance of each box.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class FilterError(ValueError):
    """A filter was constructed with arguments it cannot honour."""


class NaiveDatetimeError(FilterError):
    """A time bound was given without a time zone.

    JMA origin times are Japan Standard Time (UTC+9); see
    `docs/jma-hypocenter-format.md`, *Time zone*. Comparing a JST origin time
    against a naive bound would either shift the window by 9 hours (if the
    caller meant UTC) or raise `TypeError` deep inside the predicate, once per
    record. Refusing the bound at construction time turns a silent 9-hour
    error into a loud one, before any record is read.
    """


class FilterableEvent(Protocol):
    """The attributes a filter reads off an event.

    A structural type, not a base class. The concrete hypocenter value object
    (issues #3/#4) is built in parallel with these filters; naming only the
    five attributes a filter actually needs lets the two meet without either
    importing the other, and lets a test stub or a future record type satisfy
    the filters without inheriting anything.

    `depth_km` and `magnitude` are optional because the catalog leaves them
    blank: 9,973 of 257,020 `h2023` records carry no magnitude. See
    `docs/jma-hypocenter-format.md` for the field-level blanking rules.
    """

    @property
    def origin_time(self) -> datetime:
        """Origin time. Timezone-aware; JMA publishes JST (UTC+9)."""
        ...

    @property
    def latitude(self) -> float:
        """Signed decimal degrees, north positive."""
        ...

    @property
    def longitude(self) -> float:
        """Signed decimal degrees, east positive, in [-180, 180]."""
        ...

    @property
    def depth_km(self) -> float | None:
        """Depth in kilometres, or None when the catalog leaves it blank."""
        ...

    @property
    def magnitude(self) -> float | None:
        """Primary magnitude, or None when the catalog leaves it blank."""
        ...


def _require_aware(value: datetime | None, *, name: str) -> None:
    """Reject a naive datetime bound.

    `utcoffset() is None` is the documented test for awareness and is correct
    for zones whose offset is zero, where a truthiness check on the offset
    would wrongly call an aware UTC datetime naive.
    """
    if value is not None and value.utcoffset() is None:
        raise NaiveDatetimeError(
            f"{name} must be timezone-aware; JMA origin times are JST (UTC+9), "
            f"so a naive bound would shift the window silently. Got {value!r}."
        )


EventPredicate = Callable[[FilterableEvent], bool]
"""A filter: a pure function from an event to whether it is kept."""


def all_of(*predicates: EventPredicate) -> EventPredicate:
    """Compose filters: accept an event only if every predicate accepts it.

    This is how "every filter is optional" is expressed — an unwanted filter is
    simply not passed, and `all_of()` with no predicates admits everything.
    Callers therefore build the argument list conditionally rather than passing
    sentinel values into each filter.

    Evaluation **short-circuits** on the first rejection. A composed filter is
    applied to every record of a 257,000-record year, so the cheap predicates
    should be listed first.
    """

    def predicate(event: FilterableEvent) -> bool:
        return all(each(event) for each in predicates)

    return predicate


def _passes_optional_range(
    value: float | None,
    *,
    minimum: float | None,
    maximum: float | None,
) -> bool:
    """Test an optional measurement against an inclusive range.

    **The missing-value policy lives here, once, for both magnitude and depth:
    an unknown value fails an active range and passes an inactive one.**

    The reasoning, since either answer type checks and the choice silently
    changes a scientific result. A range filter is a claim *about* the value —
    "this record's magnitude is at least 3.0". A record with no magnitude
    supports no such claim, so admitting it would put records into an "M3.0+"
    result set that are not known to be M3.0+, and a user counting that set
    would over-count. The blank field is common enough for that to matter:
    9,973 of 257,020 `h2023` records and 11,621 of 28,235 `h1919` records carry
    no magnitude, so the wrong policy would silently distort a 1919-1950 study
    by 41 per cent of its rows.

    The opposite failure — dropping records the user wanted — is the one the
    user can see and correct, because a record absent from the output is
    recoverable by widening or dropping the filter, whereas a record wrongly
    present is indistinguishable from a real one. CONTRIBUTING's "prefer
    failing loudly over returning a value that might be wrong" points the same
    way. A caller who wants the unknowns keeps them by not applying the filter,
    or by applying it to the subset that has the value.

    When neither bound is given the filter asserts nothing, so it must not drop
    anything; that is why the `None` value is admitted in that case rather than
    rejected outright.
    """
    if minimum is None and maximum is None:
        return True
    if value is None:
        return False
    if minimum is not None and value < minimum:
        return False
    return not (maximum is not None and value > maximum)


def time_range(
    *, start: datetime | None = None, end: datetime | None = None
) -> EventPredicate:
    """Accept events whose origin time lies in the closed interval [start, end].

    Both bounds are **inclusive**: a record whose origin time equals `start` or
    `end` is admitted. Either may be `None`, leaving that side unbounded.

    Both bounds must be **timezone-aware**; a naive one raises
    `NaiveDatetimeError`. Bounds need not be JST — comparison is by absolute
    instant, so an aware UTC bound works and means what it says.
    """
    _require_aware(start, name="start")
    _require_aware(end, name="end")

    def predicate(event: FilterableEvent) -> bool:
        origin = event.origin_time
        _require_aware(origin, name="origin_time")
        if start is not None and origin < start:
            return False
        return not (end is not None and origin > end)

    return predicate


def magnitude_range(
    *, minimum: float | None = None, maximum: float | None = None
) -> EventPredicate:
    """Accept events whose magnitude lies in the closed interval.

    Both bounds are **inclusive**: `minimum=3.0` admits an M3.0 record, which
    is what a user asking for "M3.0 and above" means. Either may be `None`,
    leaving that side unbounded.

    **Missing magnitude: excluded while this filter is active.** A record whose
    magnitude is `None` is rejected whenever `minimum` or `maximum` is given,
    and admitted when neither is. See `_passes_optional_range` for why.
    """

    def predicate(event: FilterableEvent) -> bool:
        return _passes_optional_range(event.magnitude, minimum=minimum, maximum=maximum)

    return predicate


def depth_range(
    *, minimum_km: float | None = None, maximum_km: float | None = None
) -> EventPredicate:
    """Accept events whose hypocentral depth lies in the closed interval.

    Bounds are in kilometres and **inclusive**; either may be `None`.

    **Missing depth: excluded while this filter is active**, on the same
    reasoning as `magnitude_range`; see `_passes_optional_range`.

    Depth 0 km is a real value in the catalog (`h1919` line 1130, the 1923
    Kanto earthquake) and is never treated as absent.
    """

    def predicate(event: FilterableEvent) -> bool:
        return _passes_optional_range(
            event.depth_km, minimum=minimum_km, maximum=maximum_km
        )

    return predicate


@dataclass(frozen=True)
class BoundingBox:
    """A latitude/longitude rectangle in signed decimal degrees.

    `south`/`north` are latitudes in [-90, 90] and `west`/`east` are longitudes
    in [-180, 180], matching the sign convention the JMA record itself uses
    (the sign column at c22 and c33; see `docs/jma-hypocenter-format.md`).

    **Crossing the antimeridian.** `west > east` is not an error: it means the
    box runs eastward from `west` across +/-180 to `east`. `west=175,
    east=-175` is the 10-degree band around the antimeridian, not the 350
    degrees the other way. This case is real rather than theoretical — `h2023`
    holds the Kermadec-Tonga-Fiji cluster on both sides of the line, 18 records
    at negative longitudes down to -179.2 alongside SOUTH OF FIJI records at
    +178 and +179 — and a box for it cannot be expressed with `west < east`.
    An implementation that assumed `west < east` would return an empty result
    for the western half and never say why.

    Latitude has no such wraparound, so `south > north` is always a caller
    mistake and is rejected.

    `description` is required and carries the provenance of the numbers, so
    that a hand-drawn box can never travel through the system anonymously.
    """

    south: float
    north: float
    west: float
    east: float
    description: str

    def __post_init__(self) -> None:
        for name, value in (("south", self.south), ("north", self.north)):
            if not -90.0 <= value <= 90.0:
                raise FilterError(f"{name} must be in [-90, 90]; got {value!r}.")
        for name, value in (("west", self.west), ("east", self.east)):
            if not -180.0 <= value <= 180.0:
                raise FilterError(f"{name} must be in [-180, 180]; got {value!r}.")
        if self.south > self.north:
            raise FilterError(
                f"south ({self.south}) must not exceed north ({self.north}). "
                "Latitude does not wrap; only longitude may cross the "
                "antimeridian, which is written as west > east."
            )

    @property
    def crosses_antimeridian(self) -> bool:
        """Whether this box runs across +/-180 (that is, `west > east`)."""
        return self.west > self.east

    def contains(self, latitude: float, longitude: float) -> bool:
        """Whether a point lies in the box; all four edges are inclusive."""
        if not self.south <= latitude <= self.north:
            return False
        if self.crosses_antimeridian:
            return longitude >= self.west or longitude <= self.east
        return self.west <= longitude <= self.east


def bounding_box(box: BoundingBox) -> EventPredicate:
    """Accept events whose epicentre lies inside `box`, edges included."""

    def predicate(event: FilterableEvent) -> bool:
        return box.contains(event.latitude, event.longitude)

    return predicate


class UnknownAreaError(FilterError):
    """A named area is not in `NAMED_AREAS`.

    Raised rather than resolving to an empty box: an empty box returns zero
    events, which a user reads as "no earthquakes happened there" instead of
    "you misspelled the name".
    """


def _dms(
    degrees: int, minutes: int, seconds: float, *, negative: bool = False
) -> float:
    """Degrees/minutes/seconds to signed decimal degrees.

    The published prefecture extents are given in DMS; converting here rather
    than committing pre-rounded decimals keeps each number visibly traceable
    to the figure in the citation.

    `degrees`, `minutes` and `seconds` are **magnitudes and must not be
    negative**; the hemisphere is carried by `negative=` instead. Passing a
    negative degrees value raises `FilterError`.

    Why the sign is a separate argument rather than a sign on `degrees`. The
    sign belongs to the whole angle, not to its first term: 30 deg 12' 41" S
    is -30.211389, and negating only the degrees gives -29.788611, an error of
    0.42 deg — about 47 km of latitude. That much is fixable by negating the
    sum. What is not fixable that way is `-0`: a coordinate between the
    equator and 1 deg S, such as -0 deg 30', has degrees zero, and Python's
    `int` has no negative zero, so `-0 == 0` and the hemisphere is already
    lost before this function is called. A separate flag is the only encoding
    in which `_dms(0, 30, 0, negative=True) == -0.5` can be written at all.

    All four Ishikawa edges are positive, so no box in `NAMED_AREAS` presently
    exercises the negative path. It is enforced here because `NAMED_AREAS` is
    an extension point: `h2023` holds real southern- and western-hemisphere
    records (the Kermadec-Tonga-Fiji cluster, down to -179.374 deg), so the
    first area added there would otherwise get a silently displaced box.

    Raises:
        FilterError: any of `degrees`, `minutes`, `seconds` is negative.
    """
    if degrees < 0:
        raise FilterError(
            f"degrees must not be negative; got {degrees!r}. Pass the magnitude "
            "with negative=True for a southern latitude or western longitude. "
            "A sign on degrees cannot express -0 deg (a coordinate south of the "
            "equator or west of Greenwich by less than one degree), because "
            "-0 == 0 for int."
        )
    for name, value in (("minutes", minutes), ("seconds", seconds)):
        if value < 0:
            raise FilterError(
                f"{name} must not be negative; got {value!r}. Minutes and "
                "seconds are magnitudes; the hemisphere is carried by "
                "negative=."
            )
    magnitude = degrees + minutes / 60 + seconds / 3600
    return -magnitude if negative else magnitude


#: Named areas, each an **approximate rectangle**, not a boundary.
#:
#: **The MVP decision, and its limitation.** These are hand-maintained bounding
#: boxes kept in this repository. They are *not* prefecture polygons, and this
#: layer deliberately does not attempt a point-in-prefecture test.
#:
#: A rectangle drawn around a prefecture's extreme points necessarily includes
#: territory outside it — for Ishikawa the box spans the Noto peninsula's
#: north-east tip and the south-west coast, so it also covers parts of Toyama,
#: Gifu, Fukui and a large area of the Sea of Japan. A user filtering
#: `ishikawa` gets *events in a box around Ishikawa*, which is a usefully
#: narrower slice of 257,000 records but is not "events in Ishikawa
#: prefecture". Measured on `h2023`, the box selects 31,954 of 257,020
#: records; the JMA region names on those records show 21,813 NOTO PENINSULA
#: REGION and 9,173 OFF NOTO PENINSULA as intended, but also 205 TOYAMA GIFU
#: BORDER REG, 189 CENTRAL FUKUI PREF, 178 NORTHERN GIFU PREF and 94 TOYAMA
#: PREF — about 2 per cent of the result lies outside the prefecture.
#:
#: Anyone needing the real boundary needs a polygon dataset and a
#: point-in-polygon test, which brings an authoritative source, a licence
#: review, and a dependency this standard-library-only layer cannot take.
#:
#: The alternative was rejected on those grounds: a prefecture polygon from an
#: unverified source that a researcher mistakes for authoritative is worse than
#: a rectangle that says plainly what it is. The approximation is therefore
#: visible in the API — every box carries its `description`, which names the
#: source and the word "approximate" — and not only in the documentation.
#:
#: Each box's numbers must cite where they came from. Do not add an area whose
#: extent you cannot attribute.
NAMED_AREAS: dict[str, BoundingBox] = {
    # Extreme points published by the Ishikawa prefectural government, sourced
    # to GSI (国土地理院) and stated to be in the World Geodetic System:
    #   north 37 deg 51' 28" N  Hegurajima, Ama-machi, Wajima
    #   south 36 deg 04' 01" N  Mt Akatsuka, Hakusan
    #   east  137 deg 21' 55" E Himejima, Misaki-machi, Suzu
    #   west  136 deg 14' 35" E Shioya fishing port, Kaga
    # <https://www.pref.ishikawa.lg.jp/kensei/koho/gaiyo/p0.html>
    "ishikawa": BoundingBox(
        south=_dms(36, 4, 1),
        north=_dms(37, 51, 28),
        west=_dms(136, 14, 35),
        east=_dms(137, 21, 55),
        description=(
            "Approximate bounding box around Ishikawa prefecture, from its "
            "four extreme points as published by the prefecture (source: GSI, "
            "World Geodetic System). NOT a prefecture boundary: the rectangle "
            "also covers parts of Toyama, Gifu and Fukui and a large area of "
            "the Sea of Japan. "
            "https://www.pref.ishikawa.lg.jp/kensei/koho/gaiyo/p0.html"
        ),
    ),
}


def available_area_names() -> tuple[str, ...]:
    """The names `named_area` accepts, sorted."""
    return tuple(sorted(NAMED_AREAS))


def named_area(name: str) -> BoundingBox:
    """Resolve a named area to its approximate bounding box.

    Lookup ignores surrounding whitespace and case. The returned box is an
    approximation, not a boundary — see `NAMED_AREAS` — and carries that
    caveat in its `description`.

    Raises:
        UnknownAreaError: the name is not one of `available_area_names()`.
    """
    key = name.strip().lower()
    try:
        return NAMED_AREAS[key]
    except KeyError:
        raise UnknownAreaError(
            f"Unknown area {name!r}. Available: {', '.join(available_area_names())}."
        ) from None
