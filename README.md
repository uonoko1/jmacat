# jmacat

[English] | [日本語](README.ja.md)

**The JMA earthquake catalog, decoded into a table you can actually analyse.**

One command turns a year of the Japan Meteorological Agency's Seismological
Bulletin into Parquet or CSV, with the coordinates, depths, magnitudes and time
zone converted correctly. For **research and education**.

```sh
uv run jmacat fetch --year 2023 --output events.parquet
```

## The problem this solves

JMA publishes its hypocenter catalog as a ZIP of 96-byte fixed-width records.
To get a table out of it today, you download the archive and write the decoder
yourself:

**Before** — one record, exactly as JMA ships it:

```
J2023010100080150 012 354059 100 1403927 136 50     03v   721   3110NEAR CHOSHI CITY          9A
```

Now convert degrees-and-decimal-minutes to decimal degrees, handle negative
latitudes and negative magnitudes, resolve the two depth encodings, work out
that the times are JST, and assemble a CSV.

**After** — the same record, as the first data row of `events.csv`:

```csv
record_type,origin_time_utc,origin_time_jst,second_is_known,latitude_deg,latitude_minutes_are_known,longitude_deg,longitude_minutes_are_known,depth_km,magnitude,magnitude_type,magnitude_2,magnitude_type_2,district,region_number,region_name,station_count
J,2022-12-31T15:08:01.500Z,2023-01-01T00:08:01.500+09:00,True,35.6765,True,140.6545,True,50.0,0.3,v,,,3,110,NEAR CHOSHI CITY,9
```

`354059` became **35.6765** degrees north, not 35.4059. `1403927` became
**140.6545** degrees east. ` 50  ` became **50.0 km**, not 0.50. And the JST
origin time carries a UTC twin, so the row joins against USGS or ISC without
anyone having to remember the nine hours.

That conversion is the whole of what this tool is. It is not much code — but it
is code that is easy to get quietly wrong, which is the next section.

## Why not a fifty-line script

Every trap below fails **silently**. There is no exception and no warning: you
get a plausible number that is wrong, and it survives into your figures.

- **Coordinates are degrees + decimal minutes.** Read `354059` as 35.4059
  decimal degrees and the epicentre moves about **27 km**.
- **The sign sits in the leading column of the degree field.** Truncate that
  column and `KERMADEC ISL., N.Z.L.` at longitude `-178` reads as 178°E instead
  of 178°W — the other side of the world. 45 records in `h2023` carry a minus in
  the latitude degree field and 18 in the longitude degree field.
- **Old records leave the minutes' decimals blank.** In the 1923 Sagami Bay
  record, latitude minutes are `06  ` — that is 6.00 minutes, not 0.06.
  `int(s.strip())/100` gives 0.06 and an error of about **11 km**.
- **Depth carries two encodings in one field.** ` 50  ` is 50 km (whole km,
  two trailing blanks); ` 2645` is 26.45 km. Read the first as the second and
  you get 0.50 km. Read `h1919`'s one-trailing-blank shape as whole kilometres
  and 297 records land up to **5,400 km deep** — inside the outer core.
- **Magnitudes can be negative.** `-6` is M-0.6, and `A0`/`B0`/`C0` are
  M-1.0/-2.0/-3.0. A naive `int(field)/10` gives M-6.0 for the first and raises
  on the second. 24,882 records in `h2023` — nearly one in ten — are negative.
- **Times are JST, not UTC.** The specification says so only on the *English*
  layout page; the Japanese page omits the time zone entirely. Any comparison
  against USGS or ISC needs a nine-hour shift.

None of these produces an error, so a test suite that only checks "it ran" will
not catch any of them. Each is documented, with the real records that exercise
it, in [`docs/jma-hypocenter-format.md`](docs/jma-hypocenter-format.md) — the
source of truth for this project — and each is covered by tests whose expected
values are traceable to the specification or to a cited record.

ObsPy does not read this format; its event readers cover QuakeML, NDK, ZMAP,
CMTSOLUTION, Nordic, PDE and others, but not the JMA bulletin. Independent
one-off converters for it do exist on GitHub, in several languages, each
written from scratch and each with no users to speak of.

## Install

Requires Python 3.11 or newer.

**jmacat is not on PyPI yet**, so install it from a clone. Both a uv and a
pip workflow are given; either produces the same `jmacat` command.

```sh
git clone https://github.com/uonoko1/jmacat && cd jmacat

# with uv (recommended: it resolves and creates the environment for you)
uv sync
uv run jmacat --version

# with pip
python -m venv .venv && . .venv/bin/activate
pip install -e .
jmacat --version
```

Once it is published, `uv tool install jmacat` and `pip install jmacat` will be
the whole of it.

```console
$ uv run jmacat --version
jmacat 0.1.0
```

## A minimal example

Fetch one year and write it to Parquet. The archive (~7 MB) is downloaded once
and cached, so a second run does no network I/O:

```console
$ jmacat fetch --year 2023 --output events.parquet
Wrote 257,020 events to events.parquet (parquet).
Read 257,020 records from the 2023 catalog.
```

That is a full year of Japanese seismicity — 257,020 events — in about eleven
seconds on a laptop, in a file of 8.1 MB. `--format csv` writes CSV instead.

Filter while fetching:

```sh
jmacat fetch --year 2023 --area ishikawa --min-magnitude 3.0 --format csv --output noto.csv
```

`--version` and `--help` do what you expect, and any failure exits non-zero
with a message rather than a traceback.

## What this tool does not do

- **It does not give you recent earthquakes.** The finalized catalog lags the
  present by years; as of 2026-08-30 the newest published year is 2023.
- **It does not do seismology.** No declustering, no b-value fitting, no
  magnitude-of-completeness estimation, no relocation. It hands you a clean
  table; the analysis is yours.
- **It does not read the other JMA formats** — no deck files, no arrival-time
  or phase data, no moment tensors. The hypocenter catalog only.
- **It does not do point-in-polygon geography.** `--area` is a bounding box.
- **It does not decode all 31 record fields.** 16 are decoded; the other 11 are
  absent from the output rather than emitted empty. See *Record fields not yet
  in the output*.
- **It does not redistribute JMA data.** You fetch it yourself, into your own
  environment.

## Scope and safety

jmacat exists to turn a published, finalized seismic catalog into a table you can
analyse. The intended uses are retrospective: computing a Gutenberg-Richter
b-value, building a declustered catalog, teaching a seismology class how the
record layout encodes a hypocentre, preparing an input file for a hazard model.
Everything in the design serves that — the catalog it reads lags the present by
years, the archives are cached on disk rather than polled, and the output is a
static file.

That is also the whole of what it is fit for. **This tool is not a substitute for
official disaster information, and must not be used for evacuation decisions,
real-time alerting, or any automated decision affecting human safety.**

This is not a disclaimer added for form. The data itself cannot support such a
use: the finalized catalog is published with a delay of years, so the most recent
event it contains is old news before this tool ever sees it — as of 2026-08-30 the
newest available year is 2023, and the 2024 Noto Peninsula earthquake is not in
this dataset at all. A pipeline built on jmacat that appeared to be watching for
earthquakes would be watching a file that cannot change in response to one.

For anything operational — warnings, current seismicity, evacuation guidance — use
the official channels:

- **Japan Meteorological Agency** — earthquake and tsunami information, warnings:
  <https://www.jma.go.jp/bosai/map.html>
- **Your local government (自治体)** — evacuation advisories and shelter information
  for your area.
- **Cabinet Office, Disaster Management (内閣府 防災情報)** —
  <https://www.bousai.go.jp/>

The project is also **experimental**. It is being built to find out whether a tool
of this shape is useful to researchers in Japan, not because a need for it has
been established. The output format may change, and the accuracy claims it makes
are the ones its tests cover — no more.

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

## Using it

Beyond the minimal example, three things are worth knowing: what a filter did
to your data, how to call the same operation from Python, and what `--area`
actually selects.

### What a filter dropped, and why

A filtered run reports three numbers, not one. **A record excluded because its
magnitude is below the bound and a record excluded because it has no magnitude
at all mean opposite things**, and collapsing them lets a silently shrunken
dataset pass as a complete one.

The effect is largest on the pre-war catalog. `h1919` covers 1919-1950, and
11,621 of its 28,235 records carry no magnitude:

```console
$ jmacat fetch --year 1919 --output h1919_m3.csv --format csv --min-magnitude 3.0
Wrote 15,874 events to h1919_m3.csv (csv).
Read 28,235 records from the 1919 catalog.
15,874 selected after filtering:
  740 excluded by magnitude (of the 28,235 parsed records)
  11,621 excluded for a missing magnitude — 41.2% of the 28,235 parsed records. These records carry no magnitude at all, so the filter could not judge them
  (15,874 + 12,361 excluded + 0 unparsed = 28,235 read)
```

Two fifths of the era is dropped for want of a magnitude rather than for being
too small, and the run says so. A researcher who needs those rows keeps them by
not applying the filter.

#### Every count says what it was counted over

Each exclusion line names its own denominator, because with more than one
filter the counts are **not** independent facts about the whole catalog. A
record is attributed to the first filter that rejects it, so every filter after
the first judged only what its predecessors admitted.

**The geographic filter therefore runs first**, deliberately and as part of the
contract, so that the magnitude and depth counts describe the area you asked
about:

```console
$ jmacat fetch --year 1919 --area ishikawa --min-magnitude 3.0 --output noto.parquet
Wrote 49 events to noto.parquet (parquet).
Read 28,235 records from the 1919 catalog.
49 selected after filtering:
  28,149 excluded by area (of the 28,235 parsed records)
  37 excluded for a missing magnitude — 43.0% of the 86 that reached it. These records carry no magnitude at all, so the filter could not judge them
  (49 + 28,186 excluded + 0 unparsed = 28,235 read)
```

Read that as it is written: of the **86** records inside the Ishikawa box, 37
carry no magnitude — **43 per cent of your own data** — and none of the rest
falls below M3.0, leaving 49. The catalog-wide figures for the same query, 740
below the bound and 11,621 blank, are about Japan and would answer a question
you did not ask.

"Parsed records" is not the same as the header's "read" whenever a line fails to
parse: an unparsable line reaches no filter, so it is excluded from every
filter's denominator and appears only in the unparsed count.

The exclusion policy itself lives in `domain/filters.py` and is unchanged: a
range filter is a claim about a value, and a record with no value supports no
claim. The **counting** is in the interactor, because a predicate that
accumulated state would no longer be a pure function.

Records that fail to parse are counted and reported the same way, never
silently dropped. The bracketed identity closes: every record read is written,
excluded, or unparsed, exactly once.

### The same operation from Python

The CLI is a thin wrapper over one function, so the command line and the SDK
cannot drift into different behaviour:

```python
from pathlib import Path

from jmacat.controller.cli import fetch
from jmacat.usecase.export import OutputFormat

result = fetch(
    year=1919,
    output=Path("h1919_m3.csv"),
    output_format=OutputFormat.CSV,
    min_magnitude=3.0,
)
result.records_written  # 15874
result.records_excluded_for_a_missing_value  # 11621
result.reconciles()  # True
```

Every command-line option is a parameter of that function; a test reads the
signature and requires `--help` to advertise each one.

**There is deliberately no example notebook.** A notebook would have to earn
its place against the snippet above, and it cannot: the output is an ordinary
Parquet or CSV file, so the moment jmacat's job ends is the moment a reader's
own tools take over. A notebook demonstrating `pandas.read_parquet` would be
teaching pandas, not this tool, while adding pandas, matplotlib and a Jupyter
kernel — none of which this project depends on — to what a contributor must
install to reproduce the docs, plus committed cell outputs that no gate checks
and that go stale silently. The four commands in this README are executed and
pasted verbatim, and the schema table is verified against the code by a test;
a notebook would be the one artefact here that nothing keeps honest.

### Named areas

`--area` selects an **approximate bounding box**, not a prefecture boundary.
`--area ishikawa` also covers parts of Toyama, Gifu and Fukui and a stretch of
the Sea of Japan; see `NAMED_AREAS` in `domain/filters.py` for the extent and
its provenance. An unknown name lists the ones that work rather than returning
zero events.

## Known limitations

These are the limitations found in this project's own data work, not a generic
list. Each is documented at greater length where it is implemented.

### The catalog lags the present by years

**This is the limitation that surprises people, so it comes first.** JMA
publishes the *finalized* catalog, which is reviewed before release. As of
2026-08-30, `h2023.zip` is the newest year that exists; `h2024.zip` and
`h2025.zip` both return HTTP 404.

The practical consequence: **the 2024 Noto Peninsula earthquake is not in this
dataset**, and neither is anything else after 2023. A request for an unpublished
year is reported as such rather than returning an empty result, so the tool will
not silently tell you a year had no earthquakes.

If you need recent or provisional events, this catalog is the wrong source.

### One archive can hold more than one year

The early era is not one file per year. `h1919.zip` contains a single member
covering **1919-1950** (28,235 records). The adapter reads the archive's one
member whatever it is named, rather than assuming the name matches the year you
asked for.

### Whole-degree coordinates carry precision the number cannot express

Some historical records publish an epicentre only to the whole degree, leaving the
decimal-minutes field blank. A latitude published that way decodes to exactly
`35` — indistinguishable, by value and by representation, from a determination of
35° 00.00′. The difference is roughly 100 km of uncertainty against roughly 15 m.

The output therefore carries `latitude_minutes_are_known` and
`longitude_minutes_are_known` as separate boolean columns. **A caller who ignores
them has a silently over-precise coordinate.** The two flags are independent — a
record can publish one coordinate to minutes and the other only to the degree.

### A filter drops records that have no value for the field it filters on

`--min-magnitude 3.0` selects records whose magnitude is at least 3.0. A record
with **no magnitude at all** does not satisfy that claim and is excluded.

Blank magnitude is common, so this materially changes a result set. On `h1919`
(1919-1950), a magnitude filter of 3.0 returns 15,874 of 28,235 records; of the
12,361 excluded, **11,621 — 41.2 per cent of the corpus — are excluded for
carrying no magnitude, not for being too small.** On `h2023` the same field is
blank on 9,973 of 257,020 records (3.9 per cent).

The same rule applies to depth, although the depth field is blank on no record of
either corpus. A filter that is not applied excludes nothing, so records with a
missing value are kept by simply not filtering on that field.

A minimum above a maximum is refused before anything is fetched, rather than
returning the empty result it would produce. An empty file is indistinguishable
from a legitimate finding of no events, and a mistyped bound should not be able
to look like one:

```console
$ jmacat fetch --year 1919 --min-magnitude 5.0 --max-magnitude 3.0 --output out.parquet
error: The magnitude range is empty: minimum 5.0 is above maximum 3.0, so no record could match. Did you mean --min-magnitude 3.0 --max-magnitude 5.0?
```

Equal bounds are accepted: the ranges are closed, so `--min-magnitude 6.1
--max-magnitude 6.1` selects the records sitting exactly on M6.1.

### Named areas are rectangles, not boundaries

`ishikawa` is a bounding box drawn around the prefecture's four extreme points
[as published by the prefecture](https://www.pref.ishikawa.lg.jp/kensei/koho/gaiyo/p0.html)
(source: GSI, World Geodetic System). It is **not a prefecture boundary**, and no
point-in-polygon test is performed.

A rectangle around Ishikawa also covers parts of Toyama, Gifu and Fukui and a
large area of the Sea of Japan. Measured on `h2023`, the box selects 31,954
records, of which 30,986 carry one of the two Noto region names it is aimed at
and **968 — about 3 per cent — do not.** If you need the real boundary you need a
polygon dataset and a point-in-polygon test, which this tool does not provide.

### CSV cannot distinguish a null string from an empty string

On Python 3.11, which is this project's baseline, CSV writes both a null and a
zero-length string as an empty field. This is lossless for this catalog — no
field of the 96-byte record can hold a zero-length string meaning anything other
than "blank" — but it is a real limit of the format. **Parquet keeps the two
apart**, and is the better choice if you are handing the output to another tool.

Numeric nulls are unambiguous in both: `,,` is a null and `,0.0,` is a measured
zero. See *Nulls* below.

### Eleven record fields are not decoded yet

The record has 31 fields and the parser decodes 16. The undecoded eleven —
including `maximum_intensity`, `damage_class` and `tsunami_class` — are **absent
from the output rather than emitted as empty columns**, so their absence is
visible. See *Record fields not yet in the output* below.

### Codes the specification documents but no sampled year exhibits

The parser accepts every code the specification defines, but some have no worked
example in this project's corpora, because they occur in years nobody has
sampled. `docs/jma-hypocenter-format.md` lists them in its *Unresolved* section;
they include magnitude forms `B*`/`C*` (M-2.x, M-3.x), travel-time tables
`2`/`3`/`4`/`6`, location precisions `4`/`8`/`9`, maximum intensities `7`, `C`,
`R`, `M`, `S`, `L`, `F`, damage class `X`, and tsunami classes `3`-`6`. The years
1951-1994 and 1996-2018 remain unsampled.

Two further gaps are recorded there rather than guessed at: district `9` and
district `8` / region `400` (`FAR FIELD`) are used by the catalog but appear in no
appendix table, so the 269-entry region mapping must not be treated as
exhaustive; and the region *name* text is not byte-stable across years, so
`region_name` should never be used as a key — key on `district` and
`region_number` instead.

### Region names are ASCII in every year checked, but only four were checked

The specification declares the region name field `A24` without naming an
encoding. `h1919`, `h1995`, `h2019` and `h2023` contain no byte above 0x7F. The
intervening years were not checked.

## Data provenance and attribution

### Where the data comes from

All seismic data handled by this tool is published by the **Japan Meteorological
Agency (気象庁)** as part of the Seismological Bulletin of Japan (地震月報（カタログ編）):

| What | URL |
| --- | --- |
| Hypocenter file index | <https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html> |
| Yearly hypocenter archives | `https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h{year}.zip` |
| Record format specification | <https://www.data.jma.go.jp/eqev/data/bulletin/data/format/hypfmt_e.html> |
| Epicentre region name appendix (1.A.3) | <https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix/appendixj.html> |

### This repository redistributes no catalog data

The archives are fetched at run time into **your own environment** and cached
there (see [`docs/catalog-cache.md`](docs/catalog-cache.md)). Nothing under
`h{year}.zip` is committed here; `.gitignore` excludes `*.zip` and
`h[0-9][0-9][0-9][0-9]` so it cannot be committed by accident.

There are exactly two exceptions, both tiny recorded test fixtures with their
provenance and attribution stated in
[`tests/infrastructure/fixtures/README.md`](tests/infrastructure/fixtures/README.md):
`h1919_sample.zip` (651 bytes, the first 12 record lines of `h1919`) and
`h2024_404.html` (2,203 bytes, JMA's 404 page, which carries no catalog data).

### The terms the data is under

JMA's site terms page, [気象庁ホームページについて](https://www.jma.go.jp/jma/kishou/info/coment.html)
(read 2026-08-30), states:

> 気象庁ホームページで公開している情報（以下「コンテンツ」といいます。）は、権利表記の記載がない限り「公共データ利用規約（第1.0版）」に準拠した利用条件の下で、利用することができます。

That is: unless a page carries its own rights notice, the content is available
under the **Public Data License (Version 1.0)** — 公共データ利用規約（第1.0版）,
abbreviated **PDL1.0** — published by the Digital Agency at
<https://www.digital.go.jp/resources/open_data/public_data_license_v1.0>.

Two points worth stating precisely, because both are easy to get wrong:

- PDL1.0 (established 2024-07-05) is the **successor** to the older 政府標準利用規約.
  It is not the same document, and it is the one JMA's page names today.
- PDL1.0 states explicitly that it is compatible with CC BY 4.0, and that the
  State permits use under CC BY: 「クリエイティブ・コモンズ・ライセンスの表示4.0 国際
  ライセンスに規定される著作権利用許諾条件（以下「CC BY」といいます。）と互換性が
  あります。」 So a CC BY 4.0 attribution satisfies it, but the citation forms
  below are what JMA's own page asks for.

### What the terms actually require

JMA's terms page gives the required forms verbatim. Quoting them rather than
paraphrasing, since a paraphrase of an attribution requirement is not an
attribution requirement:

> (1)　出典の記載について
>
> コンテンツを利用する際は出典を記載してください。出典の記載方法は以下のとおりです。
>
> （出典記載例）
>
> 出典：気象庁ホームページ　（当該ページのURL）
>
> 出典：○○気象台ホームページ （当該ページのURL）
>
> 「図・写真等の名称」（気象庁ホームページより）
>
> コンテンツを編集・加工等して利用する場合は、上記出典とは別に、編集・加工等を行ったことを記載してください。
> また編集・加工した情報を、あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません。
>
> （コンテンツを編集・加工等して利用する場合の記載例）
>
> 気象庁「図・写真等の名称」 （当該ページのURL）を加工して作成
>
> 気象庁「○○調査」をもとに△△株式会社作成

In English, the three obligations are:

1. **Cite the source.** Give the source and the URL of the page you took it from.
2. **If you edited or processed it, say so** — as a statement *separate from* the
   source citation. PDL1.0 additionally requires naming who did the processing
   （「編集・加工等を行ったこと及びその主体を記載してください」）.
3. **Do not present processed information as though the State produced it.**
   Publishing a derived dataset in a form that makes it look like an unmodified
   government product is prohibited outright.

### What this means for you

Anything jmacat writes is **processed** JMA data — it is decoded from a
fixed-width record into physical quantities, filtered, and re-serialised.
Obligation 2 therefore always applies to jmacat output. This is the part most
easily got wrong: citing the source alone is not enough.

**If you publish results derived from jmacat output** (a paper, a figure, a
poster, a thesis), cite the catalog and state that it was processed. For example:

> Hypocenter data: Japan Meteorological Agency, Seismological Bulletin of Japan
> (<https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html>), processed by the
> authors using jmacat.
>
> 出典：気象庁ホームページ（https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html）
> を加工して作成。

**If you redistribute the output itself** (a derived CSV or Parquet file, a
release asset, a dataset deposit), the same citation must travel *with the file*
— in a README, a data descriptor or a metadata field — not only in a paper that
cites it. State that it is processed JMA data and who processed it, and do not
present it as an official JMA product.

**Note on wording.** The example sentences above are ours; JMA's page gives the
example forms quoted in full in the previous section, and it does not prescribe
an English rendering. If you need certainty for a formal publication, follow the
Japanese forms verbatim from JMA's own page.

Also note PDL1.0's disclaimer: the State accepts no responsibility for anything a
user does with the content, including with processed derivatives. That is
independent of this project's own no-warranty terms in [`LICENSE`](LICENSE).

### The code

The code in this repository is MIT-licensed; see [`LICENSE`](LICENSE). The MIT
licence covers the code alone and says nothing about the data, which stays under
PDL1.0 wherever it goes.

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

Contribution rules — the architecture, the TDD cycle and the traceability rule
for numeric test expectations — are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

```sh
uv sync
uv run pytest          # fast suite; full-scale tests are deselected
uv run pytest -m ""    # everything, as CI runs it

# One end-to-end run against the real published catalog. Downloads h1919 to a
# temporary cache and discards it; no catalog data is ever committed.
JMACAT_INTEGRATION=1 uv run pytest -m integration
uv run mypy
uv run ruff check
uv run ruff format --check
```

The full-scale tests write 257,020 records through each writer and take about
30 s in total, so they are marked `slow` and left out of the default run.
