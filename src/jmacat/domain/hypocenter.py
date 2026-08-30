"""The JMA hypocenter record: layout, decoding and physical units.

Standard library only (see CONTRIBUTING.md). Every column constant and every
conversion here traces to `docs/jma-hypocenter-format.md`, which reproduces
JMA's own layout table at
<https://www.data.jma.go.jp/eqev/data/bulletin/data/format/hypfmt_e.html>.

The governing rule for this module is CONTRIBUTING's "prefer failing loudly
over returning a value that might be wrong". Every field that cannot be decoded
raises a typed error naming the field; nothing falls back to a plausible value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

RECORD_LENGTH = 96
"""Bytes per record, excluding the LF terminator (format doc, field table)."""


class RecordError(Exception):
    """Base class for every failure to decode a hypocenter record."""


class RecordLengthError(RecordError):
    """The line is not exactly `RECORD_LENGTH` bytes.

    Kept distinct from `FieldError`: the line never reached field decoding, so
    no field can be blamed. The format doc's "Record width is stable across
    eras" section requires rejecting such a line rather than slicing it, since
    a short line would otherwise silently yield blank - and therefore `None` -
    for every field past its end.
    """

    def __init__(self, length: int) -> None:
        self.length = length
        super().__init__(
            f"A hypocenter record must be {RECORD_LENGTH} bytes, got {length}."
        )


class FieldError(RecordError):
    """A single field could not be decoded. Names the offending field."""

    def __init__(self, field: str, columns: str, raw: str, reason: str) -> None:
        self.field = field
        self.columns = columns
        self.raw = raw
        self.reason = reason
        super().__init__(f"{field} (columns {columns}) is {raw!r}: {reason}")


MINUTES_PER_DEGREE = Decimal(60)
"""Sexagesimal wheel. A minutes field reaching 60 means the slice is wrong."""


def _signed_degrees(raw: str, *, field: str) -> tuple[int, Decimal]:
    """Split a degree field into its sign and magnitude.

    Format doc, Traps 2: the sign lives in the leftmost column of the *degree*
    field and the digits are right-aligned, so a one-digit southern latitude
    reads `- 7` - a space *between* the sign and the digit. `int("- 7")`
    raises, so interior spaces are removed before converting. The minutes field
    is always unsigned and inherits this sign.
    """
    sign = -1 if "-" in raw else 1
    digits = raw.replace("-", "").replace(" ", "")
    if not digits.isdigit():
        raise FieldError(field, "degrees", raw, "not an integer number of degrees")
    return sign, Decimal(digits)


def _fixed_point(raw: str, *, field: str, columns: str) -> Decimal | None:
    """Decode a JMA fixed-point field (`F4.2`, `F5.2`, `F3.2`).

    Format doc, Traps 9: these fields are *fixed-position*. The last two
    columns hold the two decimal places and the leading columns the integer
    part. JMA blanks the decimal columns when the hypocenter is fixed while
    keeping the integer part in place, so `.strip()` on the whole field deletes
    the decimals rather than the padding and the surviving digits are then read
    as if they had been decimals - `int("06  ".strip()) / 100` gives 0.06 min
    where the truth is 6.00 min, an 11 km error that raises nothing.

    So the two parts are sliced separately. Blank decimals mean *unknown
    decimals* on a value that is present; a wholly blank field means *no value*
    and returns `None` (Traps 6).
    """
    integer_part, decimal_part = raw[:-2].strip(), raw[-2:].strip()
    if not integer_part and not decimal_part:
        return None
    if integer_part and not integer_part.isdigit():
        raise FieldError(field, columns, raw, "integer part is not a number")
    if decimal_part and not decimal_part.isdigit():
        raise FieldError(field, columns, raw, "decimal part is not a number")
    # A blank decimal part contributes 0 to the arithmetic; the value is the
    # integer part at reduced precision, not an absent value.
    return Decimal(integer_part or 0) + Decimal(decimal_part or 0) / 100


def decimal_degrees(degrees: str, minutes: str, *, field: str) -> Decimal:
    """Degrees plus decimal minutes -> decimal degrees, sign included.

    Format doc, Traps 1: `354059` in c22-28 is 35 deg 40.59 min = 35.6765 deg,
    not 35.4059 deg - the two differ by roughly 27 km. Traps 2: the sign from
    the degree field applies to the minutes as well.
    """
    sign, whole = _signed_degrees(degrees, field=field)
    fraction = _fixed_point(minutes, field=field, columns="minutes")
    if fraction is None:
        raise FieldError(field, "minutes", minutes, "minutes are blank")
    if fraction >= MINUTES_PER_DEGREE:
        raise FieldError(
            field,
            "minutes",
            minutes,
            f"{fraction} minutes is not below {MINUTES_PER_DEGREE}; "
            "a sexagesimal field can never reach 60, so the slice is wrong",
        )
    return sign * (whole + fraction / MINUTES_PER_DEGREE)


JST = timezone(timedelta(hours=9), "JST")
"""Japan Standard Time, UTC+9 - the time zone of every JMA origin time.

Stated by the specification only on the English layout table, in the Year
field: "Year of origin time (Japan Standard Time = UTC + 9 h; the same applies
below.)". The Japanese table omits it entirely. The note is not scoped by
record type, so `U` and `I` records are read as JST too; the format doc
cross-checks both against external UTC catalogs (the 2023 Turkey M7.8 and the
1920 Haiyuan M8.3) and both agree after a 9 h shift.

Attached to every returned datetime rather than left implicit: a naive
datetime compared against a UTC catalog is silently nine hours wrong.
"""


def _integer_field(raw: str, *, field: str, columns: str) -> int:
    """A blank-free integer field. Blank or non-numeric is an error, not a 0."""
    if not raw.strip().isdigit():
        raise FieldError(field, columns, raw, "not an integer")
    return int(raw)


ORIGIN_TIME_COLUMNS = {
    "year": "02-05",
    "month": "06-07",
    "day": "08-09",
    "hour": "10-11",
    "minute": "12-13",
}
"""Columns of the blank-free integer time fields (format doc, field table)."""


def origin_time(
    year: str, month: str, day: str, hour: str, minute: str, second: str
) -> datetime:
    """Fields 2-7 (c02-17) -> an aware datetime in JST.

    Year through minute are plain integers and never blank. The second field is
    `F4.2` - seconds x 100 - and goes through the fixed-point decoding, because
    it meets Traps 9 as well: h1919 holds 3 records whose second decimals alone
    are blank (`54  ` is 54.00 s, not 0.54 s) and 18 whose second field is
    wholly blank, meaning the event is located only to the minute.

    A wholly blank second yields a datetime at second 0. That is a rendering
    choice, not a claim of precision: `Hypocenter.second_is_known` carries the
    distinction so a caller can tell "unknown" from "exactly 00.00 s".
    """
    raws = (year, month, day, hour, minute)
    values = [
        _integer_field(raw, field=name, columns=columns)
        for raw, (name, columns) in zip(raws, ORIGIN_TIME_COLUMNS.items(), strict=True)
    ]
    seconds = _fixed_point(second, field="second", columns="14-17") or Decimal(0)
    whole_seconds, fraction = divmod(seconds, 1)
    try:
        return datetime(
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            int(whole_seconds),
            int(fraction * 1_000_000),
            tzinfo=JST,
        )
    except ValueError as error:
        raise FieldError(
            "origin time",
            "02-17",
            "".join(raws) + second,
            str(error),
        ) from error


NEGATIVE_MAGNITUDE_UNITS = {"-": 0, "A": 1, "B": 2, "C": 3}
"""Leading character -> whole magnitude units to subtract (format doc).

`-1`…`-9` are M-0.1…M-0.9, `A0`…`A9` M-1.0…M-1.9, `B*` M-2.x and `C*` M-3.x.
`B` and `C` occur in neither corpus but are specified, so they are handled.
"""


def magnitude(raw: str) -> Decimal | None:
    """Field 17 or 19 (`F2.1`) -> a signed magnitude.

    Format doc, *Magnitude* and Traps 3: micro-earthquakes go below zero and
    JMA writes the sign into the first character. `-6` is M-0.6, not M-6.0,
    and `A0` is M-1.0, which `int(raw) / 10` cannot decode at all. Nearly one
    in ten h2023 records carries a negative magnitude 1.

    Two blanks mean no magnitude was determined, which returns `None` rather
    than M0.0 (Traps 6).
    """
    if not raw.strip():
        return None
    head, tenths = raw[0], raw[1:]
    if not tenths.isdigit():
        raise FieldError("magnitude", "53-54/56-57", raw, "tenths digit is not a digit")
    if head.isdigit():
        return Decimal(f"{head}.{tenths}")
    units = NEGATIVE_MAGNITUDE_UNITS.get(head)
    if units is None:
        raise FieldError(
            "magnitude", "53-54/56-57", raw, f"unknown magnitude sign code {head!r}"
        )
    return -(Decimal(units) + Decimal(tenths) / 10)


def depth_km(raw: str) -> Decimal | None:
    """Field 15 (c45-49) -> kilometres, honouring both of its encodings.

    Format doc, *Depth*: this is the only field with two meanings, and the
    reliable discriminator is the two trailing blanks at c48-49.

    * `c48-49` both blank - the `I3,2X` depth-slice/fixed form. The three
      digits at c45-47 are whole kilometres: ` 50  ` is 50 km. Reading it as
      F5.2 would give 0.50 km, a hundredfold error (Traps 5).
    * otherwise - the `F5.2` depth-free form, hundredths of a km. The integer
      part is c45-47 and the decimals c48-49, so ` 2645` is 26.45 km.

    The F5.2 branch goes through the same fixed-point decoding as the minutes
    fields, because it meets Traps 9 too: h1919 holds 297 records whose final
    decimal column alone is blank (` 150 ` = 15.0 km). Taking such a field as
    four digits of whole kilometres instead yields depths up to 5400 km,
    deeper than the Earth; the fixed-point reading tops out at 540 km.
    """
    if raw[3:5] == "  ":
        whole = raw[:3].strip()
        if not whole:
            return None
        if not whole.isdigit():
            raise FieldError("depth", "45-49", raw, "not an integer number of km")
        return Decimal(whole)
    return _fixed_point(raw, field="depth", columns="45-49")


class RecordType(Enum):
    """Field 1 (c01): who determined the hypocenter (format doc, field table)."""

    JMA = "J"
    USGS = "U"
    INTERNATIONAL = "I"
    """Another international agency - ISC, IASPEI and the like."""


# Column ranges, 1-indexed and inclusive, exactly as the specification's own
# "Col." column gives them. Kept as named constants rather than inline slices
# so that a shifted offset is a one-line change with a test behind it: the
# format doc's Traps 4 records that these offsets were once derived by counting
# characters in northern-hemisphere sample lines, which silently drops the sign
# column on every southern and western record.
LATITUDE_DEGREES = (22, 24)
LATITUDE_MINUTES = (25, 28)
LONGITUDE_DEGREES = (33, 36)
LONGITUDE_MINUTES = (37, 40)
DEPTH = (45, 49)
MAGNITUDE_1 = (53, 54)
MAGNITUDE_TYPE_1 = (55, 55)
MAGNITUDE_2 = (56, 57)
MAGNITUDE_TYPE_2 = (58, 58)
DISTRICT = (65, 65)
REGION_NUMBER = (66, 68)
REGION_NAME = (69, 92)
STATION_COUNT = (93, 95)


@dataclass(frozen=True, slots=True)
class Hypocenter:
    """One earthquake hypocenter, in physical units.

    Immutable: a decoded record is a value, and a caller that mutated one would
    silently invalidate any comparison already made against it.

    Every optional field is `None` when its columns are blank, never 0. The
    format doc's Traps 6 is explicit that a `.strip() or "0"` fallback converts
    "unknown" into "exactly zero", which is worse than raising.
    """

    record_type: RecordType
    origin_time: datetime
    """Aware, in JST (UTC+9). See `JST`; never naive."""
    second_is_known: bool
    """False when c14-17 was wholly blank, i.e. located only to the minute.

    `origin_time` still has to render a second, so without this flag a caller
    cannot tell an unknown second from a determined 00.00 s.
    """
    latitude: Decimal
    longitude: Decimal
    depth_km: Decimal | None
    magnitude: Decimal | None
    magnitude_type: str | None
    magnitude_2: Decimal | None
    magnitude_type_2: str | None
    district: int | None
    region_number: int | None
    region_name: str | None
    station_count: int | None


def _columns(line: str, span: tuple[int, int]) -> str:
    """The 1-indexed, inclusive column range `span` of `line`.

    The specification numbers columns from 1 and includes both ends, so the
    conversion to a Python slice lives here once rather than at each use.
    """
    start, end = span
    return line[start - 1 : end]


def _optional_text(raw: str) -> str | None:
    """A text field: blank means absent (Traps 6), not the empty string."""
    return raw.strip() or None


def _optional_integer(raw: str, *, field: str, columns: str) -> int | None:
    """An integer field that may be blank. Blank is `None`, never 0."""
    text = raw.strip()
    if not text:
        return None
    if not text.isdigit():
        raise FieldError(field, columns, raw, "not an integer")
    return int(text)


def _span(span: tuple[int, int]) -> str:
    """A column span rendered the way the specification writes it."""
    start, end = span
    return f"{start:02d}-{end:02d}" if start != end else f"{start:02d}"


def parse_record(line: str) -> Hypocenter:
    """Decode one 96-byte JMA hypocenter record into physical units.

    Pure: no I/O, no clock, no global state. Raises `RecordLengthError` if the
    line is the wrong width and `FieldError` - naming the field - if any field
    cannot be decoded. Nothing is guessed and no unparseable field falls back
    to a plausible value.
    """
    if len(line) != RECORD_LENGTH:
        raise RecordLengthError(len(line))

    type_code = line[0]
    try:
        record_type = RecordType(type_code)
    except ValueError as error:
        raise FieldError(
            "record type",
            "01",
            type_code,
            "not one of the defined codes J, U and I",
        ) from error

    second = line[13:17]
    return Hypocenter(
        record_type=record_type,
        origin_time=origin_time(
            line[1:5], line[5:7], line[7:9], line[9:11], line[11:13], second
        ),
        # Blank decimals still mean a known second; only a wholly blank field
        # means the second was never determined (format doc, Traps 9).
        second_is_known=bool(second.strip()),
        latitude=decimal_degrees(
            _columns(line, LATITUDE_DEGREES),
            _columns(line, LATITUDE_MINUTES),
            field="latitude",
        ),
        longitude=decimal_degrees(
            _columns(line, LONGITUDE_DEGREES),
            _columns(line, LONGITUDE_MINUTES),
            field="longitude",
        ),
        depth_km=depth_km(_columns(line, DEPTH)),
        magnitude=magnitude(_columns(line, MAGNITUDE_1)),
        magnitude_type=_optional_text(_columns(line, MAGNITUDE_TYPE_1)),
        magnitude_2=magnitude(_columns(line, MAGNITUDE_2)),
        magnitude_type_2=_optional_text(_columns(line, MAGNITUDE_TYPE_2)),
        # District and region are carried as plain numbers and deliberately not
        # validated against the appendix: the format doc's Unresolved 3 finds
        # district 9 and region 8/400 in the data with no appendix entry, so a
        # parser that rejected them would reject real records.
        district=_optional_integer(
            _columns(line, DISTRICT), field="district", columns=_span(DISTRICT)
        ),
        region_number=_optional_integer(
            _columns(line, REGION_NUMBER),
            field="region number",
            columns=_span(REGION_NUMBER),
        ),
        region_name=_optional_text(_columns(line, REGION_NAME)),
        station_count=_optional_integer(
            _columns(line, STATION_COUNT),
            field="station count",
            columns=_span(STATION_COUNT),
        ),
    )
