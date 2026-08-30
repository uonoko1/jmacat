"""Pure filter predicates over hypocenter events."""

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
) -> Callable[[FilterableEvent], bool]:
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
) -> Callable[[FilterableEvent], bool]:
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
) -> Callable[[FilterableEvent], bool]:
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


def bounding_box(box: BoundingBox) -> Callable[[FilterableEvent], bool]:
    """Accept events whose epicentre lies inside `box`, edges included."""

    def predicate(event: FilterableEvent) -> bool:
        return box.contains(event.latitude, event.longitude)

    return predicate
