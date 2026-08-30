"""The output column schema shared by every `EventWriter` adapter.

One declarative table, read by both the Parquet writer and the CSV writer, so
the two formats cannot drift apart. Column order, name, physical unit and the
meaning of a null are all stated here, because they are what a researcher joins
against — a column whose unit lives only in a developer's head is how a
hundredfold error ships unnoticed (see *Traps* 5 and 9 in
`docs/jma-hypocenter-format.md`).

Scope: what the parser decodes, and nothing else
------------------------------------------------

Every column below is read from an attribute that `domain.hypocenter.Hypocenter`
actually carries. The record has 31 fields; the parser decodes 16 of them, and
this schema exposes exactly those.

An earlier revision of this table also declared columns for the eleven fields
nobody decodes — the four standard errors, the travel time table, the location
precision, the subsidiary information, the maximum intensity, the damage and
tsunami classes and the determination flag. Every one of them would have been
null on every row of every file, forever. That is worse than an absent column,
because a null column *looks like data*: a reader sees `maximum_intensity` in
the schema, finds it empty, and concludes that no event in 2023 was felt.
An absent column asks a question; an always-null column answers it wrongly.

Adding them back once the parser decodes them is a purely **additive** schema
change — a new column at the end of the table — which is the cheap direction.
The README says so under *Columns* so that a reader is not left wondering
whether their absence means the data does not exist.

Types the writers accept
------------------------

The domain hands out `Decimal` coordinates and a `RecordType` **enum**, neither
of which a serialiser may guess at:

* `Decimal` -> `float`, by `_as_double`, here, once, for both formats. The
  schema declares `double`; the narrowing therefore belongs to the schema and
  not to whichever writer happens to run. Doing it per-writer is what let CSV
  write `str(Decimal("142.93183333333333"))` while Parquet stored the nearest
  double, `142.93183333333334` — the two formats disagreeing about a coordinate,
  with no error from either.
* `RecordType` -> its `.value`, by `_record_type_code`. `str()` on an enum
  member is `"RecordType.JMA"`, which is a perfectly valid string and would have
  gone into the CSV column unremarked.

Both conversions are explicit and total. What a writer must never do is fall
back to `str()` on a type it has no rule for; `csv_event_writer._render` raises
instead, so an unhandled type is loud in both formats rather than in neither.

Time zone
---------

JMA's catalog records origin times in **Japan Standard Time (UTC+9)**; the
specification says so in the description of the Year field, and the project's
format document quotes it under *Time zone — JST, not UTC*. Two columns are
emitted rather than one:

* `origin_time_utc` — the instant, in UTC. This is the join key. Any external
  catalog worth joining against (USGS, ISC) publishes UTC, and a researcher who
  joins on a JST column without noticing is off by nine hours with no error.
* `origin_time_jst` — the same instant with a +09:00 offset attached. Kept
  because every JMA-published figure, every Japanese news report and every
  aftershock sequence discussed in the literature is described in local time,
  and recovering it from UTC requires knowing the rule. Japan has observed no
  daylight saving since 1951, so the offset is a constant +09:00 and the two
  columns are the same instant in two calendars, never two different instants.

Neither column is naive. In Parquet both are `timestamp[ms]` with a time zone in
the field metadata; in CSV both are ISO 8601 strings carrying an explicit offset
(`Z` and `+09:00`). A reader that ignores the time zone still cannot mistake one
for the other, because the two columns disagree by nine hours in the text.

Millisecond precision is deliberate: the catalog's second field is `F4.2`,
hundredths of a second (format document, field 7), so milliseconds represent it
exactly with room to spare, and microsecond timestamps would imply a precision
the source does not have.

Nulls
-----

Blank is not zero (*Traps* 6). Every optional column is nullable and a missing
value stays null through both formats: a magnitude that JMA did not determine
must never read back as M0.0, which is a real and quite different measurement.
`null_meaning` on each column records what the absence actually means, because
"no magnitude was determined" and "this record type never carries one" are
different facts and a bare NULL cannot tell them apart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from jmacat.infrastructure.event_protocol import HypocenterEventLike


@dataclass(frozen=True)
class Column:
    """One output column: its name, physical meaning, type and null handling.

    `arrow_type_name` is the *string* spelling of the pyarrow type rather than a
    `pa.DataType`. Keeping it a string lets this module stay importable — and
    the schema stay assertable in a test — without pyarrow, which matters
    because the CSV writer needs the same table and has no reason to pull in
    Arrow. `parquet_event_writer.py` turns these names into real Arrow types in
    one place.
    """

    name: str
    arrow_type_name: str
    unit: str
    null_meaning: str
    #: Reads the value off an event. Returns `None` for an absent value.
    extract: Callable[[HypocenterEventLike], object]


def _as_double(value: Decimal | None) -> float | None:
    """A domain `Decimal` as the `double` this schema declares, or `None`.

    The single place the narrowing happens, so both writers serialise the
    identical IEEE-754 value. `float(Decimal)` is correctly rounded to the
    nearest double, and CSV then writes that double's `repr` — the shortest
    text that reads back as the same double — so the two formats agree bit for
    bit.

    The alternative, letting each writer handle `Decimal` its own way, is what
    the review found: CSV rendered `str(Decimal("142.93183333333333"))` and
    Parquet stored `142.93183333333334`, and the two files disagreed about
    where the epicentre was.

    Precision is not lost that a `double` could have held: the record's
    coordinates are decoded from fixed-point fields of at most six significant
    digits, and a double carries fifteen. What is lost is the *exactness* of the
    decimal representation, which no `double` column can carry by definition —
    that is what declaring the column `double` means, and it is stated here
    rather than discovered from a diff of the two outputs.
    """
    return None if value is None else float(value)


def _record_type_code(event: HypocenterEventLike) -> str:
    """The record type as its published one-character code.

    `.value`, never `str()`. `str(RecordType.JMA)` is `"RecordType.JMA"`, a
    valid string that CSV would write into the column without complaint — the
    member *name* is a Python identifier, while `.value` is what the record
    contains and what a researcher joins against.
    """
    return event.record_type.value


#: The output columns, in order.
#:
#: Order is part of the contract. Parquet carries its schema in the footer and
#: could survive a reordering, but CSV has nothing but the header row, and a
#: consumer that reads by position would silently transpose two float columns.
#: So the order is pinned here and asserted in a test.
#:
#: Every column below maps to a field of the 96-byte record that the parser
#: decodes; the field numbers in the comments are those of the field table in
#: `docs/jma-hypocenter-format.md`.
COLUMNS: Final[tuple[Column, ...]] = (
    Column(
        name="record_type",
        arrow_type_name="string",
        unit="code: J=JMA, U=USGS, I=another international agency",
        null_meaning="never null; the record type identifier is always present",
        extract=_record_type_code,
    ),
    Column(
        name="origin_time_utc",
        arrow_type_name="timestamp[ms, tz=UTC]",
        unit="UTC instant, millisecond precision",
        null_meaning="never null; every record carries an origin time",
        extract=lambda event: event.origin_time,
    ),
    Column(
        name="origin_time_jst",
        arrow_type_name="timestamp[ms, tz=+09:00]",
        unit="the same instant as origin_time_utc, expressed at UTC+09:00",
        null_meaning="never null; the same instant as origin_time_utc",
        extract=lambda event: event.origin_time,
    ),
    Column(
        name="second_is_known",
        arrow_type_name="bool",
        unit=(
            "true when the record determined the second; false when it located "
            "the event only to the minute"
        ),
        null_meaning=(
            "never null; false is a determination about the record, not a missing value"
        ),
        extract=lambda event: event.second_is_known,
    ),
    Column(
        name="latitude_deg",
        arrow_type_name="double",
        unit="decimal degrees",
        null_meaning="never null; positive north, negative south",
        extract=lambda event: _as_double(event.latitude),
    ),
    Column(
        name="latitude_minutes_are_known",
        arrow_type_name="bool",
        unit=(
            "true when the latitude was published to decimal minutes; false "
            "when only the whole degree was given"
        ),
        null_meaning="never null; false is a statement about the record's precision",
        extract=lambda event: event.latitude_minutes_are_known,
    ),
    Column(
        name="longitude_deg",
        arrow_type_name="double",
        unit="decimal degrees",
        null_meaning="never null; positive east, negative west",
        extract=lambda event: _as_double(event.longitude),
    ),
    Column(
        name="longitude_minutes_are_known",
        arrow_type_name="bool",
        unit=(
            "true when the longitude was published to decimal minutes; false "
            "when only the whole degree was given"
        ),
        null_meaning="never null; false is a statement about the record's precision",
        extract=lambda event: event.longitude_minutes_are_known,
    ),
    Column(
        name="depth_km",
        arrow_type_name="double",
        unit="kilometres below the surface, positive downward",
        null_meaning=(
            "depth not determined. Never 0.0, which is a real and common "
            "shallow depth (*Traps* 6)"
        ),
        extract=lambda event: _as_double(event.depth_km),
    ),
    Column(
        name="magnitude",
        arrow_type_name="double",
        unit="magnitude (dimensionless), on the scale named by magnitude_type",
        null_meaning=(
            "no magnitude determined (9,973 records in h2023). Never 0.0: "
            "micro-earthquakes are routinely negative, so 0.0 is a plausible "
            "measured value and would not look wrong"
        ),
        extract=lambda event: _as_double(event.magnitude),
    ),
    Column(
        name="magnitude_type",
        arrow_type_name="string",
        unit=(
            "code: J=MJ, D=MD, d=MD 2 stations, V=MV, v=MV 2-3 stations, "
            "W=MW, B=mb, S=MS"
        ),
        null_meaning="undetermined; null on exactly the rows where magnitude is null",
        extract=lambda event: event.magnitude_type,
    ),
    Column(
        name="magnitude_2",
        arrow_type_name="double",
        unit="magnitude (dimensionless), on the scale named by magnitude_type_2",
        null_meaning="no second magnitude determined (blank on 256,259 of h2023)",
        extract=lambda event: _as_double(event.magnitude_2),
    ),
    Column(
        name="magnitude_type_2",
        arrow_type_name="string",
        unit="code, on the same table as magnitude_type",
        null_meaning="undetermined",
        extract=lambda event: event.magnitude_type_2,
    ),
    Column(
        name="district",
        arrow_type_name="int32",
        unit="JMA geographical district number (Appendix 1.A.3)",
        null_meaning="not assigned (field 27)",
        extract=lambda event: event.district,
    ),
    Column(
        name="region_number",
        arrow_type_name="int32",
        unit="JMA epicentre region within the district (Appendix 1.A.3)",
        null_meaning="not assigned (field 28)",
        extract=lambda event: event.region_number,
    ),
    Column(
        name="region_name",
        arrow_type_name="string",
        unit="ASCII epicentre region name as published in the record",
        null_meaning=(
            "blank in the record (553 records in h1919). The name text is not "
            "byte-stable across years; key on district and region_number, not "
            "on this string"
        ),
        extract=lambda event: event.region_name,
    ),
    Column(
        name="station_count",
        arrow_type_name="int32",
        unit="count of stations contributing to the determination",
        null_meaning=(
            "not published. Never 0, which would assert a determination made "
            "from no stations at all"
        ),
        extract=lambda event: event.station_count,
    ),
)


def column_names() -> list[str]:
    """The output column names, in order — the CSV header row."""
    return [column.name for column in COLUMNS]
