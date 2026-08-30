"""The output column schema shared by every `EventWriter` adapter.

One declarative table, read by both the Parquet writer and the CSV writer, so
the two formats cannot drift apart. Column order, name, physical unit and the
meaning of a null are all stated here, because they are what a researcher joins
against — a column whose unit lives only in a developer's head is how a
hundredfold error ships unnoticed (see *Traps* 5 and 9 in
`docs/jma-hypocenter-format.md`).

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
from typing import Final

from jmacat.infrastructure.event_protocol import HypocenterEventLike


@dataclass(frozen=True)
class Column:
    """One output column: its name, physical meaning, type and null handling.

    `arrow_type_name` is the *string* spelling of the pyarrow type rather than a
    `pa.DataType`. Keeping it a string lets this module stay importable — and
    the schema stay assertable in a test — without pyarrow, which matters
    because the CSV writer needs the same table and has no reason to pull in
    Arrow. `event_parquet.py` turns these names into real Arrow types in one
    place.
    """

    name: str
    arrow_type_name: str
    unit: str
    null_meaning: str
    #: Reads the value off an event. Returns `None` for an absent value.
    extract: Callable[[HypocenterEventLike], object]


#: The output columns, in order.
#:
#: Order is part of the contract. Parquet carries its schema in the footer and
#: could survive a reordering, but CSV has nothing but the header row, and a
#: consumer that reads by position would silently transpose two float columns.
#: So the order is pinned here and asserted in a test.
#:
#: Every column below maps to a field of the 96-byte record; the field numbers
#: in the comments are those of the field table in `docs/jma-hypocenter-format.md`.
COLUMNS: Final[tuple[Column, ...]] = (
    Column(
        name="record_type",
        arrow_type_name="string",
        unit="code",
        null_meaning="never null; the record type identifier is always present",
        extract=lambda event: event.record_type,
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
        name="origin_time_second_error_s",
        arrow_type_name="double",
        unit="seconds",
        null_meaning=(
            "no standard error published: the hypocenter was fixed, or a "
            "Matched-filter template hypocenter was adopted (field 8)"
        ),
        extract=lambda event: event.origin_time_error_s,
    ),
    Column(
        name="latitude_deg",
        arrow_type_name="double",
        unit="decimal degrees",
        null_meaning="never null; positive north, negative south",
        extract=lambda event: event.latitude_deg,
    ),
    Column(
        name="latitude_error_min",
        arrow_type_name="double",
        unit="minutes of arc",
        null_meaning="no standard error published (field 11)",
        extract=lambda event: event.latitude_error_min,
    ),
    Column(
        name="longitude_deg",
        arrow_type_name="double",
        unit="decimal degrees",
        null_meaning="never null; positive east, negative west",
        extract=lambda event: event.longitude_deg,
    ),
    Column(
        name="longitude_error_min",
        arrow_type_name="double",
        unit="minutes of arc",
        null_meaning="no standard error published (field 14)",
        extract=lambda event: event.longitude_error_min,
    ),
    Column(
        name="depth_km",
        arrow_type_name="double",
        unit="kilometres below the surface, positive downward",
        null_meaning=(
            "depth not determined. Never 0.0, which is a real and common "
            "shallow depth (*Traps* 6)"
        ),
        extract=lambda event: event.depth_km,
    ),
    Column(
        name="depth_error_km",
        arrow_type_name="double",
        unit="kilometres",
        null_meaning=(
            "no standard error published: blank unless the depth-free method "
            "was used (field 16)"
        ),
        extract=lambda event: event.depth_error_km,
    ),
    Column(
        name="magnitude1",
        arrow_type_name="double",
        unit="magnitude (dimensionless), on the scale named by magnitude1_type",
        null_meaning=(
            "no magnitude determined (9,973 records in h2023). Never 0.0: "
            "micro-earthquakes are routinely negative, so 0.0 is a plausible "
            "measured value and would not look wrong"
        ),
        extract=lambda event: event.magnitude1,
    ),
    Column(
        name="magnitude1_type",
        arrow_type_name="string",
        unit="code: J=MJ, D=MD, d=MD 2 stations, V=MV, v=MV 2-3 stations, "
        "W=MW, B=mb, S=MS",
        null_meaning="undetermined; null on exactly the rows where magnitude1 is null",
        extract=lambda event: event.magnitude1_type,
    ),
    Column(
        name="magnitude2",
        arrow_type_name="double",
        unit="magnitude (dimensionless), on the scale named by magnitude2_type",
        null_meaning="no second magnitude determined (blank on 256,259 of h2023)",
        extract=lambda event: event.magnitude2,
    ),
    Column(
        name="magnitude2_type",
        arrow_type_name="string",
        unit="code; same table as magnitude1_type",
        null_meaning="undetermined",
        extract=lambda event: event.magnitude2_type,
    ),
    Column(
        name="travel_time_table",
        arrow_type_name="string",
        unit="code 1-7; see *Travel time table codes*",
        null_meaning="determined by another agency (field 21)",
        extract=lambda event: event.travel_time_table,
    ),
    Column(
        name="location_precision",
        arrow_type_name="string",
        unit="code 1-9 or M; see *Location precision codes*",
        null_meaning="unknown (field 22)",
        extract=lambda event: event.location_precision,
    ),
    Column(
        name="subsidiary_information",
        arrow_type_name="string",
        unit=(
            "code: 1=natural, 2=insufficient JMA stations, 3=artificial, "
            "4=eruption-related, 5=low-frequency event"
        ),
        null_meaning="blank for non-JMA determinations (field 23)",
        extract=lambda event: event.subsidiary_information,
    ),
    Column(
        name="maximum_intensity",
        arrow_type_name="string",
        unit=(
            "JMA shindo code; 1-4 and 7 are the shindo, A/B are 5-lower/upper, "
            "C/D are 6-lower/upper. Kept as a code, not a number: the scale is "
            "ordinal and 5-lower has no numeric spelling"
        ),
        null_meaning="not felt, or no intensity assigned (field 24)",
        extract=lambda event: event.maximum_intensity,
    ),
    Column(
        name="damage_class",
        arrow_type_name="string",
        unit="Utsu damage class code 1-7, X or Y",
        null_meaning="no damage recorded (field 25)",
        extract=lambda event: event.damage_class,
    ),
    Column(
        name="tsunami_class",
        arrow_type_name="string",
        unit=(
            "tsunami class code; the code table depends on the record's year "
            "(Utsu before 1989, Imamura-Iida from 1989)"
        ),
        null_meaning="no tsunami recorded (field 26)",
        extract=lambda event: event.tsunami_class,
    ),
    Column(
        name="district_number",
        arrow_type_name="int32",
        unit="JMA geographical district 1-9 (Appendix 1.A.3)",
        null_meaning="not assigned (field 27)",
        extract=lambda event: event.district_number,
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
            "byte-stable across years; key on district_number and "
            "region_number, not on this string"
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
    Column(
        name="determination_flag",
        arrow_type_name="string",
        unit="code; see *Determination flag codes*",
        null_meaning="blank for non-JMA determinations (field 31)",
        extract=lambda event: event.determination_flag,
    ),
)


def column_names() -> list[str]:
    """The output column names, in order — the CSV header row."""
    return [column.name for column in COLUMNS]
