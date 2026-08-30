# jmacat

Preprocessing tool for the JMA seismic catalog, for **research and education**.

It fetches the published JMA Seismological Bulletin hypocenter files, decodes the
96-byte fixed-width records into physical quantities, and writes them as Parquet
or CSV.

> **Not for operational use.** This is not a substitute for official disaster
> information and must not be used for evacuation decisions or real-time
> alerting. Catalog data is fetched at run time under the JMA site terms
> (Public Data License 1.0, attribution required) and is never redistributed
> from this repository.

The record layout, its traps and every offset are documented in
[`docs/jma-hypocenter-format.md`](docs/jma-hypocenter-format.md), which is the
source of truth for this project. Contribution rules are in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Output format

Both writers emit the **same columns, in the same order**. The schema is
declared once, in `src/jmacat/infrastructure/event_schema.py`, and the table
below is checked against it by a test — so it cannot drift.

### Time zone

**The JMA catalog records origin times in Japan Standard Time (UTC+9).** The
specification states this in the description of the Year field; see *Time zone —
JST, not UTC* in the format document. It is easy to miss, because the Japanese
version of the layout table does not mention the time zone at all.

Rather than choose for you, the output carries **both**:

| Column | What it is |
| --- | --- |
| `origin_time_utc` | The instant in UTC. **Use this to join.** USGS, ISC and every other international catalog publish UTC. |
| `origin_time_jst` | The same instant at +09:00, the local time in which JMA, Japanese news reports and the literature describe every event. |

They are the same instant in two calendars, never two different instants. Japan
has observed no daylight saving since 1951, so the offset is a constant +09:00.

**No column is ever naive.** In Parquet the zone is part of the column type
(`timestamp[ms, tz=UTC]` and `timestamp[ms, tz=+09:00]`). In CSV both are ISO
8601 with an explicit offset — `2022-12-31T15:08:01.500Z` and
`2023-01-01T00:08:01.500+09:00`. Even a reader that ignores time zones cannot
confuse the two, because they differ by nine hours in the text itself.

Precision is milliseconds. The catalog's second field holds hundredths of a
second, so milliseconds are exact; microseconds would imply precision the
source does not have.

### Nulls

**A missing value is null, never zero.** This is the difference between "JMA
did not determine a magnitude" and "JMA measured M0.0", and both occur: 9,973
records in `h2023` carry no magnitude at all, while negative and near-zero
magnitudes are routine for micro-earthquakes. Depth 0 km is likewise a real,
common, shallow value. A null-to-zero collapse would not raise an error and
would not look wrong.

- **Parquet** stores nulls natively; `depth_km` reads back as `None`.
- **CSV** writes a null as an empty, unquoted field. `,,` is a null; `,0.0,` is
  a measured zero.

One documented CSV limitation: a null string and a zero-length string both
become an empty field, because CSV has one empty field and two things to say
with it (`csv.QUOTE_NOTNULL` would separate them but needs Python 3.12, and the
baseline here is 3.11). This is lossless for this catalog — no field of the
96-byte record can hold a zero-length string meaning anything other than
"blank". Parquet keeps the two apart.

### Floating point

Coordinates are **float64 decimal degrees**, signed: positive north and east.
The catalog stores degrees and decimal *minutes*, which is [trap 1] of the
format document — 35 deg 40.59 min is 35.6765 deg, not 35.4059 deg, and the two
are about 27 km apart.

In CSV, floats are written with Python's `repr`, the shortest decimal string
that reads back as the identical double. A fixed format such as `%.6f` looks
tidier and silently moves the epicentre, so it is not used.

[trap 1]: docs/jma-hypocenter-format.md

### Columns

| Column | Type | Unit | Null means |
| --- | --- | --- | --- |
| `record_type` | string | code: J=JMA, U=USGS, I=another international agency | never null; the record type identifier is always present |
| `origin_time_utc` | timestamp[ms, tz=UTC] | UTC instant, millisecond precision | never null; every record carries an origin time |
| `origin_time_jst` | timestamp[ms, tz=+09:00] | the same instant as origin_time_utc, expressed at UTC+09:00 | never null; the same instant as origin_time_utc |
| `second_is_known` | bool | true when the record determined the second; false when it located the event only to the minute | never null; false is a determination about the record, not a missing value |
| `latitude_deg` | double | decimal degrees | never null; positive north, negative south |
| `latitude_minutes_are_known` | bool | true when the latitude was published to decimal minutes; false when only the whole degree was given | never null; false is a statement about the record's precision |
| `longitude_deg` | double | decimal degrees | never null; positive east, negative west |
| `longitude_minutes_are_known` | bool | true when the longitude was published to decimal minutes; false when only the whole degree was given | never null; false is a statement about the record's precision |
| `depth_km` | double | kilometres below the surface, positive downward | depth not determined. Never 0.0, which is a real and common shallow depth (*Traps* 6) |
| `magnitude` | double | magnitude (dimensionless), on the scale named by magnitude_type | no magnitude determined (9,973 records in h2023). Never 0.0: micro-earthquakes are routinely negative, so 0.0 is a plausible measured value and would not look wrong |
| `magnitude_type` | string | code: J=MJ, D=MD, d=MD 2 stations, V=MV, v=MV 2-3 stations, W=MW, B=mb, S=MS | undetermined; null on exactly the rows where magnitude is null |
| `magnitude_2` | double | magnitude (dimensionless), on the scale named by magnitude_type_2 | no second magnitude determined (blank on 256,259 of h2023) |
| `magnitude_type_2` | string | code, on the same table as magnitude_type | undetermined |
| `district` | int32 | JMA geographical district number (Appendix 1.A.3) | not assigned (field 27) |
| `region_number` | int32 | JMA epicentre region within the district (Appendix 1.A.3) | not assigned (field 28) |
| `region_name` | string | ASCII epicentre region name as published in the record | blank in the record (553 records in h1919). The name text is not byte-stable across years; key on district and region_number, not on this string |
| `station_count` | int32 | count of stations contributing to the determination | not published. Never 0, which would assert a determination made from no stations at all |

The `unit` and `null_meaning` of every column are also attached as Arrow field
metadata, so a Parquet file passed on without this README still states what
`depth_km` is measured in.

#### Record fields not yet in the output

The record has 31 fields; the parser decodes 16 of them, and the table above is
exactly those. **Eleven fields are absent because nothing decodes them yet**,
not because the catalog does not carry them:

`origin_time_error_s`, `latitude_error_min`, `longitude_error_min`,
`depth_error_km`, `travel_time_table`, `location_precision`,
`subsidiary_information`, `maximum_intensity`, `damage_class`, `tsunami_class`
and `determination_flag`.

They are left out rather than emitted as always-null columns, because an
always-null column *looks like data*: a reader who finds `maximum_intensity` in
the schema and empty on every row would reasonably conclude that no event was
ever felt. An absent column asks a question; an always-null one answers it
wrongly.

When the parser decodes them, adding them back is an **additive** schema
change — new columns appended to the table — so nothing that reads the columns
above by name or by position breaks.

## Partial output

**A run that fails part-way leaves no file at the destination.** Both writers
stage to a temporary file beside the destination and publish it by an atomic
rename only once `close` succeeds; the context manager deletes the staging file
on the error path.

This matters because the alternative failure is invisible. A CSV truncated at
200,000 of 257,020 rows is a valid CSV. A Parquet file whose footer was written
after a partial run is a valid Parquet file. Neither would be flagged by any
tool downstream — the catalog would simply be short, and the rate computed from
it wrong. An existing complete output from an earlier run also survives a failed
re-run untouched, because the rename never happens.

## Scale

A full year is about 257,000 records (`h2023` has 257,020). Neither writer holds
a year in memory: CSV hands each row straight to the file, and Parquet buffers
50,000 events at a time and flushes each batch as a **row group**, so peak
memory follows the batch size rather than the year length. A year is six row
groups, which also lets a reader filtering by time skip most of the file.

These claims are tested rather than asserted — the row-group structure is read
back out of the finished file's footer, and the memory behaviour is measured by
comparing batched against unbatched writing in separate processes.

## Development

```sh
uv sync
uv run pytest          # fast suite; full-scale tests are deselected
uv run pytest -m ""    # everything, as CI runs it
uv run mypy
uv run ruff check
uv run ruff format --check
```

The full-scale tests write 257,020 records through each writer and take about
30 s in total, so they are marked `slow` and left out of the default run.
