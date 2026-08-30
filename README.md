# jmacat

Preprocessing tool for the JMA seismic catalog, for **research and education**.

It fetches the published JMA Seismological Bulletin hypocenter files, decodes the
96-byte fixed-width records into physical quantities, and writes them as Parquet
or CSV.

The record layout, its traps and every offset are documented in
[`docs/jma-hypocenter-format.md`](docs/jma-hypocenter-format.md), which is the
source of truth for this project. Contribution rules are in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Usage

Install, then fetch a year:

```sh
uv run jmacat fetch --year 2023 --output events.parquet
uv run jmacat fetch --year 2023 --area ishikawa --min-magnitude 3.0 --format csv
```

`--version` and `--help` do what you expect, and any failure exits non-zero
with a message rather than a traceback.

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
  740 excluded by magnitude
  11,621 excluded for a missing magnitude (41.2% of the records read) — these records carry no magnitude at all, so the filter could not judge them
  (15,874 + 12,361 excluded + 0 unparsed = 28,235 read)
```

Two fifths of the era is dropped for want of a magnitude rather than for being
too small, and the run says so. A researcher who needs those rows keeps them by
not applying the filter.

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

### Named areas

`--area` selects an **approximate bounding box**, not a prefecture boundary.
`--area ishikawa` also covers parts of Toyama, Gifu and Fukui and a stretch of
the Sea of Japan; see `NAMED_AREAS` in `domain/filters.py` for the extent and
its provenance. An unknown name lists the ones that work rather than returning
zero events.

## What this tool is for, and what it is not for

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

# One end-to-end run against the real published catalog. Downloads h1919 to a
# temporary cache and discards it; no catalog data is ever committed.
JMACAT_INTEGRATION=1 uv run pytest -m integration
uv run mypy
uv run ruff check
uv run ruff format --check
```

The full-scale tests write 257,020 records through each writer and take about
30 s in total, so they are marked `slow` and left out of the default run.
