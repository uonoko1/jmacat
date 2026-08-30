# JMA Hypocenter Record Format (96-byte fixed-width)

Authoritative reference for the JMA Seismological Bulletin hypocenter file layout.
**This document is the source of truth for every parser test expectation in this project.**

## Sources

| What | URL |
| --- | --- |
| Format overview (EN) | <https://www.data.jma.go.jp/eqev/data/bulletin/data/format/fmthyp_e.html> |
| Format overview (JA) | <https://www.data.jma.go.jp/eqev/data/bulletin/data/format/fmthyp_j.html> |
| **Record layout table (EN)** | <https://www.data.jma.go.jp/eqev/data/bulletin/data/format/hypfmt_e.html> |
| **Record layout table (JA)** | <https://www.data.jma.go.jp/eqev/data/bulletin/data/format/hypfmt_j.html> |
| Hypocenter file index | <https://www.data.jma.go.jp/eqev/data/bulletin/hypo_e.html> |
| **Appendix index (1.A.3 震央地名表)** | <https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix/appendixj.html> (anchor `#REGION`) |
| **Region name tables, districts 1-8** | <https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix/regname1.html> … `regname8.html` |
| Catalog used for cross-check | <https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h2023.zip> |
| Historical catalog used for cross-check | <https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h1919.zip> |

The specification is a **plain HTML `<table>`**, not an image and not a PDF. It lives on
`hypfmt_e.html` / `hypfmt_j.html`, which the overview pages `fmthyp_*.html` merely link to.
Extracting text from `fmthyp_j.html` yields almost nothing precisely because that page is only
a table of contents. The English and Japanese layout tables were compared field by field and
agree on every offset, type and code value; the English table carries one extra sentence the
Japanese one lacks (see *Time zone* below).

The appendix tables are **not** under `data/format/`; they live under `catalog/appendix/`, one
directory level up from the format pages, and are reached from the bulletin index rather than
from `hypfmt_*.html`. That is why an earlier search of the format pages alone did not find them.

Cross-check corpora: `h2023` (year 2023) and `h1919` (years 1919-1950), extracted from the
corresponding zips. Two eras are used deliberately: several fields and code values that never
occur in 2023 are common in the historical file, and some of them are traps (see *Traps* 9).

- `h2023.zip` — 6,977,812 bytes, `sha256:e5ced2bf7275825ba75405b071bb54e9d4c2a5eb55aa6bc9b8d670de1f58b98f`
- `h2023` — 24,930,940 bytes, `sha256:9f9d0d230e65858388393691fe2f4a445641cab06266f943d03927627fa4d4d4`
- 257,020 records; every line is exactly 96 bytes of ASCII, each terminated by a single
  `\n` (LF, no CR). Verified: 257,020 x 97 = 24,930,940 = the file size exactly, and the
  file contains zero bytes above 0x7F. The 96 bytes in the field table exclude the terminator.
- `h1919.zip` — 799,597 bytes, `sha256:c32a531c7ee1e860cd74a3a1ce178f899f2c7553a508025681a7a74a30c0e01b`
- `h1919` — 2,738,795 bytes, `sha256:03a935d6cde3c5571bec03a7f65adf84ea9f25f0a54550eaf4534ac72b219b48`
- 28,235 records spanning 1919-1950; same encoding, 28,235 x 97 = 2,738,795 = the file size,
  again pure ASCII with no CR.

### Record width is stable across eras

Every line is exactly 96 bytes in all four years checked — 1919 (the file covering 1919-1950),
1995, 2019 and 2023 — with no trailing partial line and no byte above 0x7F:

| File | Records | Bytes | records x 97 = bytes | Distinct line lengths |
| --- | --- | --- | --- | --- |
| `h1919` (1919-1950) | 28,235 | 2,738,795 | yes | {96} |
| `h1995` | 56,250 | 5,456,250 | yes | {96} |
| `h2019` | 223,367 | 21,666,599 | yes | {96} |
| `h2023` | 257,020 | 24,930,940 | yes | {96} |

The layout is therefore stable back to the start of the published record. This does not prove
every unchecked year conforms, so a parser should still reject a line whose length is not 96
rather than slicing blindly.

Catalog data is **not** committed to this repository (JMA terms: fetch at run time, do not
redistribute). `.gitignore` excludes `*.zip` and `h[0-9][0-9][0-9][0-9]`.

## Time zone — JST, not UTC

**Origin times are Japan Standard Time (UTC+9).** This is stated in the specification itself,
in the description of the Year field (columns 02-05) of `hypfmt_e.html`:

> Year of origin time (**Japan Standard Time = UTC + 9 h; the same applies below.**)

"the same applies below" extends JST to every subsequent time field: month, day, hour, minute,
second. The Japanese table (`hypfmt_j.html`) says only "オリジンタイムの西暦" and does **not**
mention the time zone at all — the English table is the only place JMA states it. Do not assume
UTC; converting requires subtracting 9 hours.

The specification does not scope the time zone by record type, so JST is taken to apply to `U`
and `I` records too. Example G below is consistent with that reading. This is an inference from
the note's placement, not an explicit JMA statement — see *Unresolved* item 1.

## Field table

Offsets are **1-indexed and inclusive**, matching the specification's own "Col." column.
The "Type" column reproduces the specification's Fortran-style declaration.

| # | Field | Cols | Width | Type | Unit | Null / missing | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Record type identifier | 01 | 1 | A1 | — | never blank | `J` JMA, `U` USGS, `I` other international (ISC, IASPEI, …) |
| 2 | Year | 02-05 | 4 | I4 | year (JST) | never blank | |
| 3 | Month | 06-07 | 2 | I2 | month (JST) | never blank | |
| 4 | Day | 08-09 | 2 | I2 | day (JST) | never blank | |
| 5 | Hour | 10-11 | 2 | I2 | hour (JST) | never blank | |
| 6 | Minute | 12-13 | 2 | I2 | minute (JST) | never blank | |
| 7 | Second | 14-17 | 4 | F4.2 | s ×100 | decimals blank if hypocenter fixed | integer field; divide by 100 |
| 8 | Standard error of origin time | 18-21 | 4 | F4.2 | s ×100 | all blank | blank if hypocenter fixed, or if a Matched-filter template hypocenter was adopted |
| 9 | Latitude, degrees | 22-24 | 3 | I3 | deg | never blank | signed; see *Traps* |
| 10 | Latitude, minutes | 25-28 | 4 | F4.2 | min ×100 | decimals blank if hypocenter fixed | unsigned; sign lives in field 9 |
| 11 | Standard error of latitude | 29-32 | 4 | F4.2 | min ×100 | all blank | same blanking rule as field 8 |
| 12 | Longitude, degrees | 33-36 | 4 | I4 | deg | never blank | signed; see *Traps* |
| 13 | Longitude, minutes | 37-40 | 4 | F4.2 | min ×100 | decimals blank if hypocenter fixed | unsigned; sign lives in field 12 |
| 14 | Standard error of longitude | 41-44 | 4 | F4.2 | min ×100 | all blank | same blanking rule as field 8 |
| 15 | Depth | 45-49 | 5 | F5.2 **or** I3,2X | km ×100 **or** km | — | **two mutually exclusive encodings**; see *Depth* |
| 16 | Standard error of depth | 50-52 | 3 | F3.2 | km ×100 | all blank | blank unless the depth-free method was used; also blank for Matched-filter template hypocenters |
| 17 | Magnitude 1 | 53-54 | 2 | F2.1 | mag ×10 | 2 blanks | negative values use a letter/sign code; see *Magnitude* |
| 18 | Magnitude type 1 | 55 | 1 | A1 | — | blank | see *Magnitude type codes* |
| 19 | Magnitude 2 | 56-57 | 2 | F2.1 | mag ×10 | 2 blanks | same encoding as field 17 |
| 20 | Magnitude type 2 | 58 | 1 | A1 | — | blank | same codes as field 18 |
| 21 | Travel time table | 59 | 1 | A1 | — | blank | blank when determined by another agency; see *Travel time table codes* |
| 22 | Hypocenter location precision | 60 | 1 | A1 | — | blank if unknown | see *Location precision codes* |
| 23 | Subsidiary information | 61 | 1 | A1 | — | blank for non-JMA | `1` natural, `2` insufficient JMA stations / agency-dependent, `3` artificial, `4` eruption-related, `5` low-frequency event |
| 24 | Maximum intensity | 62 | 1 | A1 | JMA shindo | blank | see *Maximum intensity codes* |
| 25 | Damage class | 63 | 1 | A1 | — | blank | Utsu scale; see *Damage and tsunami classes* |
| 26 | Tsunami class | 64 | 1 | A1 | — | blank | see *Damage and tsunami classes* |
| 27 | District number | 65 | 1 | I1 | — | — | geographical district, JMA Appendix 1.A.3 |
| 28 | Region number | 66-68 | 3 | I3 | — | blank | epicentre region number |
| 29 | Region name | 69-92 | 24 | A24 | — | (always populated in h2023) | ASCII, right-padded with spaces |
| 30 | Number of stations | 93-95 | 3 | I3 | count | blank | stations contributing to the determination |
| 31 | Hypocenter determination flag | 96 | 1 | A1 | — | blank for non-JMA | see *Determination flag codes* |

### Correction to the previously assumed offsets

Earlier empirical work in issue #1 recorded latitude at c23-28 and longitude at c34-40. **The
specification disagrees and the specification wins.** Latitude is two fields, degrees at c22-24
and minutes at c25-28; longitude is degrees at c33-36 and minutes at c37-40. The earlier
ranges happened to decode positive northern-hemisphere Japanese records correctly because
c22 and c33 hold a space there, but they truncate the sign column and break on every
southern-hemisphere and western-hemisphere record. Verified on real data below.

## Worked examples from `h2023`

Column ruler for reference:

```
         1         2         3         4         5         6         7         8         9
1234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890
```

### Example A — ordinary domestic event, depth-slice encoding

```
J2023010100080150 012 354059 100 1403927 136 50     03v   721   3110NEAR CHOSHI CITY          9A
```

| Field | Cols | Substring | Decoded |
| --- | --- | --- | --- |
| Record type | 01 | `J` | JMA |
| Year/Mon/Day | 02-09 | `2023` `01` `01` | 2023-01-01 (JST) |
| Hour/Min | 10-13 | `00` `08` | 00:08 (JST) |
| Second | 14-17 | `0150` | 1.50 s |
| Origin time s.e. | 18-21 | ` 012` | 0.12 s |
| Latitude deg | 22-24 | ` 35` | 35 |
| Latitude min | 25-28 | `4059` | 40.59 min → **35.676500 degN** |
| Latitude s.e. | 29-32 | ` 100` | 1.00 min |
| Longitude deg | 33-36 | ` 140` | 140 |
| Longitude min | 37-40 | `3927` | 39.27 min → **140.654500 degE** |
| Longitude s.e. | 41-44 | ` 136` | 1.36 min |
| Depth | 45-49 | ` 50  ` | **50 km** (depth-slice: trailing `2X` blanks) |
| Depth s.e. | 50-52 | `   ` | blank — consistent with non-depth-free method |
| Magnitude 1 | 53-54 | `03` | M0.3 |
| Magnitude type 1 | 55 | `v` | MV, two or three stations |
| Magnitude 2 | 56-57 | `  ` | absent |
| Travel time table | 59 | `7` | JMA2001A/JMA2020A/B/C per station |
| Location precision | 60 | `2` | depth-slice method |
| Subsidiary info | 61 | `1` | natural earthquake |
| District | 65 | `3` | |
| Region number | 66-68 | `110` | |
| Region name | 69-92 | `NEAR CHOSHI CITY        ` | |
| Stations | 93-95 | `  9` | 9 |
| Determination flag | 96 | `A` | middle precision, automatic |

### Example B — depth-free encoding, depth standard error present

```
J2023010100102271 017 411023 059 1425591 068 264521812v   711   2 60E OFF AOMORI PREF         8A
```

| Field | Cols | Substring | Decoded |
| --- | --- | --- | --- |
| Depth | 45-49 | ` 2645` | **26.45 km** (depth-free, F5.2) |
| Depth s.e. | 50-52 | `218` | 2.18 km |
| Magnitude 1 | 53-54 | `12` | M1.2 |
| Location precision | 60 | `1` | depth-free method |
| Latitude | 22-28 | ` 41` `1023` | 41 deg 10.23 min = 41.170500 degN |
| Longitude | 33-40 | ` 142` `5591` | 142 deg 55.91 min = 142.931833 degE |

### Example C — negative magnitude, `-n` form

```
J2023010100195595     340134     1333676     3427   -6v   5M5   6236NE EHIME PREF             3a
```

- Magnitude 1, c53-54 = `-6` → **M-0.6**
- Location precision, c60 = `M` → Matched-filter method
- Origin-time s.e. c18-21 and latitude s.e. c29-32 are blank, matching the spec's
  "blank … when hypocenter of template event is adopted in the Matched filter method".
- Travel time table c59 = `5` (JMA2001)

### Example D — negative magnitude, `A0` form

```
J2023010404233323 036 332702 037 1324517 036 3172211A0v   5M5   6235SW EHIME PREF             9a
```

- Magnitude 1, c53-54 = `A0` → **M-1.0**

### Example E — southern hemisphere, `U` (USGS) record

```
U2023011002473504    - 70352     1300054    105     71B       219   TANIMBAR IS., INDONESIA     
```

| Field | Cols | Substring | Decoded |
| --- | --- | --- | --- |
| Record type | 01 | `U` | USGS-determined |
| Latitude deg | 22-24 | `- 7` | **-7** (sign in c22, digit right-aligned in c24) |
| Latitude min | 25-28 | `0352` | 3.52 min → **-7.058667 deg** (i.e. 7.06 degS) |
| Longitude deg | 33-36 | ` 130` | 130 |
| Longitude min | 37-40 | `0054` | 0.54 min → 130.009000 degE |
| Depth | 45-49 | `105  ` | **105 km** (I3,2X form) |
| Magnitude 1 | 53-54 | `71` | M7.1 |
| Magnitude type 1 | 55 | `B` | mb, USGS body-wave magnitude |
| Damage class | 63 | `2` | light damage |
| Tsunami class | 64 | `1` | 50 cm / no damage |
| District | 65 | `9` | |
| Region name | 69-92 | `TANIMBAR IS., INDONESIA ` | |
| Stations / flag | 93-96 | `    ` | blank |

### Example F — negative longitude (western hemisphere)

```
U2023012619455283    -301269    -1783969    131     56B         9   KERMADEC ISL., N.Z.L.       
```

- Latitude deg c22-24 = `-30`, minutes c25-28 = `1269` → **-30.211500 deg**
- Longitude deg c33-36 = `-178`, minutes c37-40 = `3969` → **-178.661500 deg**
- Confirms the sign column applies to longitude as well as latitude. 18 records in `h2023`
  carry a `-` in c33-36.

### Example G — damage class 7 (2023 Turkey earthquake)

```
U2023020610173434     371354      370086     10     68B80S    719   TURKEY                      
```

- Magnitude 1 c53-54 = `68`, type `B` → mb 6.8; Magnitude 2 c56-57 = `80`, type `S` → MS 8.0
- Damage class c63 = `7` → 20,000+ fatalities or 1,000,000+ houses destroyed
- Origin time c02-17 = `2023` `02` `06` `10` `17` `3434` → **2023-02-06 10:17:34.34 JST**.
  This is the Kahramanmaras, Turkey M7.8 mainshock, whose USGS origin time is
  2023-02-06 01:17:34 UTC. Subtracting 9 h from the record reproduces the UTC time exactly,
  which independently confirms the JST reading against an external catalog.

### Example H — maximum intensity code and CMT moment magnitude

```
J2023050514420410 005 373234 019 1371827 025 121404165D62W711D314135NOTO PENINSULA REGION    40K
```

- Magnitude 1 c53-54 = `65`, type `D` → MD 6.5
- Magnitude 2 c56-57 = `62`, type `W` → MW 6.2 (JMA CMT, since record type is `J`)
- Maximum intensity c62 = `D` → shindo 6-upper
- Damage class c63 = `3`, tsunami class c64 = `1`
- Determination flag c96 = `K` → high precision, manual, closely examined

### Example I — blank decimal places (1923 Great Kanto earthquake, from `h1919`)

The `F4.2` time and minute fields may carry an integer part with a **blank decimal part**. No
record in `h2023` does this, but `h1919` does. Verbatim (96 bytes, `h1919` line 1130):

```
J192309011203         3506       13930        0     73J    325Y     SAGAMI BAY ?               K
```

| Field | Cols | Substring | Decoded |
| --- | --- | --- | --- |
| Record type | 01 | `J` | JMA |
| Year/Mon/Day | 02-09 | `1923` `09` `01` | 1923-09-01 (JST) |
| Hour/Min | 10-13 | `12` `03` | 12:03 (JST) |
| Second | 14-17 | `    ` | **entirely blank — seconds unknown**, not 0 |
| Latitude deg | 22-24 | ` 35` | 35 |
| Latitude min | 25-28 | `06  ` | **6.00 min** (integer `06`, decimals unknown) → 35.100000 degN |
| Longitude deg | 33-36 | ` 139` | 139 |
| Longitude min | 37-40 | `30  ` | **30.00 min** (integer `30`, decimals unknown) → 139.500000 degE |
| Depth | 45-49 | `  0  ` | 0 km (depth-slice form, c48-49 blank) |
| Magnitude 1 | 53-54 | `73` | M7.3 |
| Magnitude type 1 | 55 | `J` | MJ — Tsuboi displacement magnitude, old network |
| Location precision | 60 | `3` | fixed depth (human judgement) |
| Subsidiary info | 61 | `2` | insufficient JMA stations / agency-dependent |
| Maximum intensity | 62 | `5` | shindo 5 (pre-1996, before the lower/upper split) |
| Damage class | 63 | `Y` | damage merged into the adjacent event's grade |
| Region name | 69-92 | `SAGAMI BAY ?            ` | the `?` is part of the 24-byte name text |
| Determination flag | 96 | `K` | high precision (manual, closely examined) |

This single record exercises six things absent from 2023: blank decimals in two fields, a fully
blank second field, magnitude type `J`, subsidiary information `2`, maximum intensity `5`, and
damage class `Y`.

**The decoding that matters.** Latitude minutes are `06  `. The integer part is 6 and the two
decimal places are unknown, so the value is **6.00 min** and the latitude is 35.100000 degN. A
naive `int(field.strip()) / 100` yields `6 / 100` = 0.06 min and a latitude of 35.001000 degN —
wrong by about 11 km, with no exception raised. See *Traps* 9.

Counts in `h1919` for the partially blank case — integer part present, decimal part blank:
5 records in latitude minutes (c27-28), 9 in longitude minutes (c39-40), 3 in seconds (c16-17).
Small numbers, but they include the most significant earthquake in the catalog.

## Depth — the two encodings

Field 15 (c45-49) is the only field with two different meanings. The specification gives it
two type declarations on the same row:

| Method | Type | Encoding | Decode |
| --- | --- | --- | --- |
| Depth-free | `F5.2` | 5 digits, hundredths of a km | `int(field) / 100` |
| Depth-slice / fixed | `I3, 2X` | 3 digits in c45-47, **c48-49 blank** | `int(field[0:3])` |

The reliable discriminator is the two trailing blanks at c48-49, and it is corroborated by
field 22 (location precision, c60):

| c48-49 | Count in h2023 | c60 values observed |
| --- | --- | --- |
| not blank (depth-free) | 238,817 | `1` (depth-free), `M` (Matched filter) |
| blank (depth-slice/fixed) | 18,203 | `2` (depth-slice), `3` (fixed depth), blank (non-JMA) |

The partition is exact — no record contradicts it. Field 16 (depth standard error, c50-52)
is blank for every depth-slice/fixed record, as the specification states.

Depth-slice step widths per the specification: 10 km (1926-1960, 1967-1982), 20 km
(1961-1966), 1 km (1983-). Events before 1982 are progressively re-examined and replaced by
depth-free or 1 km-step solutions.

## Magnitude

Magnitude is `F2.1` — two characters holding the magnitude ×10. Two blanks mean no magnitude
was determined (9,973 records in `h2023`; magnitude type 1 is blank on exactly the same rows).

Negative magnitudes are encoded per the specification:

| Encoding | Meaning | Rule |
| --- | --- | --- |
| `-1` … `-9` | M-0.1 … M-0.9 | `-` in the first character, tenths digit second |
| `A0` … `A9` | M-1.0 … M-1.9 | `A` = -1 whole unit |
| `B0` … `B9` | M-2.0 … M-2.9 | `B` = -2 whole units |
| `C0` … `C9` | M-3.0 … M-3.9 | `C` = -3 whole units |

Observed in `h2023` for magnitude 1: `-1`(7,453) `-2`(5,793) `-3`(4,303) `-4`(2,971) `-5`(1,962)
`-6`(1,211) `-7`(664) `-8`(309) `-9`(134) `A0`(64) `A1`(12) `A2`(5) `A3`(1).
No `B*` or `C*` value occurs in 2023; the specification documents them and they must still be
handled.

### Magnitude type codes (fields 18 and 20)

JMA magnitudes:

| Code | Meaning |
| --- | --- |
| `J` | MJ — Local Meteorological Office magnitude (Tsuboi displacement magnitude, old network) |
| `D` | MD — displacement magnitude |
| `d` | as `D`, but determined from two stations |
| `V` | MV — velocity magnitude |
| `v` | as `V`, but determined from two or three stations |

Moment magnitude:

| Code | Meaning |
| --- | --- |
| `W` | MW — for record type `J`, the JMA CMT solution; otherwise determined by JMA or another organisation such as USGS |

Other organisations:

| Code | Meaning |
| --- | --- |
| `B` | mb — USGS body-wave magnitude |
| `S` | MS — USGS surface-wave magnitude |
| blank | undetermined |

Observed in `h2023` — type 1: `V`(157,682) `v`(88,616) blank(9,973) `D`(645) `B`(87) `d`(17).
Type 2: blank(256,259) `V`(463) `W`(184) `d`(76) `S`(36) `v`(2). `W` never appears as type 1
in this year.

## Code tables

### Travel time table codes (field 21, c59)

| Code | Table |
| --- | --- |
| `1` | Ichikawa and Mochizuki (1971), Hamada (1984) ("83A") and others |
| `2` | Ichikawa (1978) ("LL") — far east of Sanriku |
| `3` | Ichikawa and Mochizuki (1971) + LL, or 83A + LL — east of Hokkaido |
| `4` | Ichikawa and Mochizuki (1971) + LL, or 83A + LL — southern Kurile Islands |
| `5` | Ueno et al. (2002) ("JMA2001") |
| `6` | JMA2001 + LL (LL mesh matched to JMA2001) — southern Kurile Islands |
| `7` | JMA2001A inland, JMA2020A landward slopes, JMA2020B Japan Trench outer rise, JMA2020C Nankai Trough — selected per station |
| blank | determined by another agency |

Observed in `h2023`: `7`(242,448) `5`(14,485) blank(87). Blank occurs on exactly the 87 `U`
records.

### Location precision codes (field 22, c60)

| Code | Meaning |
| --- | --- |
| `1` | depth-free method |
| `2` | depth-slice method |
| `3` | fixed depth (human judgement) |
| `4` | based on depth phase |
| `5` | based on S-P time |
| `7` | poor / reference-only solution (until March 2016) |
| `8` | undetermined or not accepted |
| `9` | hypocenter fixed at the station that read the earliest phase |
| `M` | Matched-filter method |
| blank | unknown |

Observed in `h2023`: `1`(224,332) `2`(17,729) `M`(14,485) `3`(387) blank(87).

### Maximum intensity codes (field 24, c62)

| Code | Meaning |
| --- | --- |
| `1`-`4`, `7` | JMA shindo 1-4, 7 |
| `5`, `6` | shindo 5, 6 (until September 1996, before the lower/upper split) |
| `A` | shindo 5-lower |
| `B` | shindo 5-upper |
| `C` | shindo 6-lower |
| `D` | shindo 6-upper |
| `R` | remarkable earthquake, felt beyond 300 km (until 1977) |
| `M` | moderate, felt 200-300 km (until 1977) |
| `S` | small, felt 100-200 km (until 1977) |
| `L` | local, felt within 100 km (until 1977) |
| `F` | felt earthquake (until 1984) |
| `X` | felt by some people but not by JMA observers (until September 1996) |
| blank | not felt / not assigned |

Observed in `h2023`: blank(254,783) `1`(1,479) `2`(561) `3`(156) `4`(33) `A`(5) `B`(2) `D`(1).

Note the collision hazard: `M`, `S` and `X` mean intensity-related things here but mean
completely different things in other single-character fields (`M` = Matched filter in c60,
`S` = MS in the magnitude type fields). Decode each column against its own table.

### Damage and tsunami classes (fields 25-26, c63-64)

Damage class, after Utsu:

| Code | Meaning |
| --- | --- |
| `1` | slight — cracks in walls and ground |
| `2` | light — damage to houses, roads etc. |
| `3` | 2-19 fatalities or 2-999 houses destroyed |
| `4` | 20-199 fatalities or 1,000-9,999 houses destroyed |
| `5` | 200-1,999 fatalities or 10,000-99,999 houses destroyed |
| `6` | 2,000-19,999 fatalities or 100,000-999,999 houses destroyed |
| `7` | 20,000+ fatalities or 1,000,000+ houses destroyed |
| `X` | injury or damage of unclear scale (until 1988) |
| `Y` | damage merged into the adjacent event's grade (until 1988) |

Tsunami class — **the meaning depends on the year**:

- 1923-1988, after Utsu: `1` recorded by tide gauge, no damage; `T` tsunami generated.
- 1989-, after Imamura and Iida (1958): `1` 50 cm/none; `2` 1 m/very slight; `3` 2 m/slight
  damage to coast and vessels; `4` 4-6 m/human injury; `5` 10-20 m/damage over 400+ km of
  coastline; `6` 30 m+/damage over 500+ km of coastline.

A parser covering years before 1989 must switch tables on the record's year.

Observed in `h2023` — damage: blank(257,002) `2`(8) `3`(6) `1`(3) `7`(1);
tsunami: blank(257,008) `1`(10) `2`(2).

### District and region numbers (fields 27-28, c65-68)

These are JMA **Appendix 1.A.3 震央地名表**, reached from the bulletin appendix index at
`catalog/appendix/appendixj.html#REGION` and split across `regname1.html` … `regname8.html`,
one page per district. Each page is a plain HTML `<table>` with exactly the three columns
needed: 大地域区分番号 (district, c65), 小地域区分番号 (region, c66-68) and 震央地名
(region name, c69-92).

District numbers `1`-`8` are the geographical districts named on those pages:

| c65 | Page | District |
| --- | --- | --- |
| 1 | `regname1.html` | 北海道 — Hokkaido |
| 2 | `regname2.html` | 東北 — Tohoku |
| 3 | `regname3.html` | 関東 — Kanto |
| 4 | `regname4.html` | 中部 — Chubu |
| 5 | `regname5.html` | 近畿 — Kinki |
| 6 | `regname6.html` | 中国、四国 — Chugoku and Shikoku |
| 7 | `regname7.html` | 九州、沖縄 — Kyushu and Okinawa |
| 8 | `regname8.html` | 日本周辺 — around Japan |
| 9 | — | **not in the appendix**; see below |

The eight pages yield **269 (district, region) pairs**. Rather than reproduce 269 rows here,
where they would swamp a format reference that is otherwise read front to back, the mapping is
carried as a generated fixture — see *Where the region-name table lives* below.

**Validated against the data.** Building the mapping from the eight pages and comparing its
name against the record's own 24-byte region name field:

| Corpus | Matched | Mismatched | District or region blank | Unmapped |
| --- | --- | --- | --- | --- |
| `h2023` | 256,868 | 0 | 87 (the `U` records) | 65 |
| `h1919` | 27,536 | 1 | 667 | 31 |

Every unmapped record is district `8` / region `400` = `FAR FIELD`, a sentinel that does not
appear in the appendix table. The single `h1919` mismatch is district 8 / region 324, which the
appendix names `KURILE ISLANDS REGION` and one 1919 record writes as `KURILE ISLANDS`; across
both corpora that is the only (district, region) pair carrying more than one distinct name in
285,255 records. So the numeric pair determines the name, but the historical name *text* is not
byte-stable — key on the numbers, not the string.

District `9` occurs in `h2023` (73 of the 87 `U` records; `8` covers the other 14) and on 3
`h1919` records, yet has no `regname9.html` page. Combined with `8`/`400` = `FAR FIELD`, the
reading is that `8` and `9` are used for events outside the appendix's Japan-centred scheme;
the appendix does not say so. See *Unresolved* item 3.

#### Where the region-name table lives

The 269 rows are **not** inlined in this document, and are **not** a hand-maintained list. The
reasoning:

- This file is a format reference meant to be read end to end. A 269-row table in the middle of
  it costs far more readability than it buys, and nothing in it is needed to *parse* a record —
  the region name is already present verbatim in c69-92 of every record that has one.
- The mapping is a JMA-published dataset that can change when JMA revises the appendix. Copying
  it by hand into prose creates a second source of truth that will drift silently.
- Issues #3/#4 want it as a test fixture, which needs a machine-readable file, not a Markdown
  table.

So the appendix URLs are cited here as the authority, and the mapping is *generated* from those
pages by `tools/build_region_names.py` (standard library only), which emits JSON keyed
`"district:region"` for use as a test fixture:

```
python3 tools/build_region_names.py > region_names.json   # 269 entries, districts 1-8
```

Regenerating it and re-running the comparison above is the check that the copy is still
faithful; the row counts in this section are the expected result of that check. The generated
file is not committed here — it belongs with the parser work in issues #3/#4, which is also
where it becomes a fixture.

### Determination flag codes (field 31, c96)

| Code | Meaning |
| --- | --- |
| `K` | high precision (manual, closely examined) |
| `S` | low precision (manual, closely examined) |
| `k` | middle precision (manual) |
| `s` | low precision (manual) |
| `A` | middle precision (automatic) |
| `a` | low precision (automatic) |
| `N` | undetermined, not accepted, or fixed hypocenter |
| `F` | far field |

Observed in `h2023`: `A`(145,330) `k`(52,535) `K`(29,075) `a`(21,571) `s`(6,661) `S`(1,761)
blank(87). Case is significant: `K` and `k` are different precisions, as are `S`/`s` and `A`/`a`.
Never upper-case this field.

## `J` versus `U` records

Record type (c01) is `J` for JMA-determined, `U` for USGS-determined and `I` for other
international agencies (ISC, IASPEI …). `h2023` contains 256,933 `J` and 87 `U`; **no `I`
record occurs in 2023**, but the specification documents `I` and a parser must accept it.

The layout is identical for all record types — no field moves. What differs is which fields
are populated. Across all 87 `U` records in `h2023`:

| Field | `U` behaviour |
| --- | --- |
| Origin time s.e. (18-21) | always blank |
| Latitude s.e. (29-32) | always blank |
| Longitude s.e. (41-44) | always blank |
| Depth (45-49) | always the `I3,2X` form (c48-49 blank) |
| Depth s.e. (50-52) | always blank |
| Magnitude type 1 (55) | always `B` (mb) in 2023 |
| Magnitude 2 (56-57) | present on 36 of 87 records, always type `S` (MS) in 2023 |
| Travel time table (59) | always blank — "determined by other agencies" |
| Location precision (60) | always blank |
| Subsidiary information (61) | always blank — "blank for non-JMA" per the JA spec |
| Region number (66-68) | always blank |
| Number of stations (93-95) | always blank |
| Determination flag (96) | always blank |

Distribution of the district number (c65) on `U` records is `9`(73) and `8`(14) — the overseas
districts. Damage and tsunami classes *are* populated on `U` records (Examples E and G).

These are empirical observations for the year 2023, not guarantees the specification makes.
The specification says only that the travel-time table and subsidiary information are blank
for non-JMA determinations. A parser should treat every `U`-blank above as *possible*, not
*certain*, and must not assume a `U` record can never carry, say, a station count.

## Traps

These are the ways a parser silently produces a plausible wrong answer instead of an error.

**1. Degrees plus decimal minutes, not decimal degrees.** `354059` in c22-28 is
35 deg 40.59 min = 35.6765 deg, not 35.4059 deg. The two differ by roughly 27 km — a
difference that no assertion catches unless you assert on it. Decode as
`degrees + minutes_hundredths / 100 / 60`.

**2. The sign lives in the degree field, and the field is space-padded.** Latitude degrees
occupy c22-24 and longitude degrees c33-36, both wide enough for a sign plus digits. In
`h2023`, 45 records carry `-` in the latitude degree field and 18 in the longitude degree
field. The sign is written in the leftmost column and the digits are right-aligned, so a
one-digit southern latitude appears as `- 7`, with a space *between* the sign and the digit.
`int("- 7")` raises `ValueError`; `int("- 7".replace(" ", ""))` gives `-7`. Strip interior
spaces before converting, and apply the degree field's sign to the minutes as well — the
minutes field is always unsigned (verified: c25-28 and c37-40 are 4 digits on every record in
`h2023`).

**3. Negative magnitudes.** Micro-earthquakes go below zero. `-6` is M-0.6, and `A0`/`B0`/`C0`
are M-1.0/-2.0/-3.0. A naive `int(field) / 10` gives M-6.0 for the first and raises on the
second. 24,882 records in `h2023` — nearly one in ten — carry a negative magnitude 1.

**4. A one-digit offset error produces a plausible value, not an error.** Every field is
numeric or a single letter, and the fields are adjacent with no delimiters, so reading c23-28
instead of c22-28 still yields a well-formed number. It decodes northern-hemisphere Japanese
records correctly and silently drops the sign on everything else. Slice by the constants in
the field table above; do not derive offsets by counting characters in a sample line.

**5. Depth has two encodings in one field.** See *Depth*. Reading ` 50  ` as F5.2 gives
0.50 km instead of 50 km — a hundredfold error on a field where nothing looks wrong.

**6. Blank is not zero.** Standard errors, magnitudes, region numbers and station counts are
blank when absent. `int("   ")` raises, but a `.strip() or "0"` fallback quietly converts
"unknown" into "exactly zero", which is worse. Map blank to `None`.

**7. Single-letter codes are case-sensitive and column-specific.** `V` and `v` are different
magnitude types (different station counts); `K` and `k` are different precisions. `M`, `S` and
`X` appear in several fields with unrelated meanings. Decode each column against its own table.

**8. Times are JST.** See *Time zone*. Any comparison against a UTC-based catalog (USGS,
ISC) needs a 9-hour shift.

**9. A blank decimal part means unknown decimals, not zero — and stripping it shifts the
value by a factor of 100.** This is the same class of silent hundredfold error as trap 5, and
it is easier to hit, because the obvious implementation is wrong.

The `F4.2`/`F5.2`/`F3.2` fields are *fixed-position*: the last two columns are the two decimal
places and the leading columns are the integer part. When a hypocenter is fixed, JMA leaves the
decimal columns blank while keeping the integer part in place. `.strip()` then deletes the
decimal columns rather than the padding, and the surviving digits get read as if they had been
in the decimal positions.

Latitude minutes `06  ` (c25-28) are **6.00 min**:

| Decoding | Result | Verdict |
| --- | --- | --- |
| `int("06  ".strip()) / 100` | 0.06 min | **wrong by 100x, raises nothing** |
| `int("06  ".replace(" ", "0")) / 100` | 6.00 min | numerically right, but it also silently turns a wholly blank field into `0` |
| slice the parts: `int("06  "[:-2])` + blank decimals | 6.00 min | correct, and keeps "unknown" distinguishable |

Decode by slicing the two parts separately: integer part `field[:-2]`, decimals `field[-2:]`;
treat blank decimals as unknown and use `0` only for the arithmetic, recording that the
precision is reduced. Do not `.strip()` the field as a whole and divide.

The distinct case is a field that is blank **in its entirety** (for example seconds `    ` on
the same 1923 record): that is a genuinely absent value and must map to `None`, per trap 6.
Distinguish "integer present, decimals blank" (a real value at lower precision) from "all
blank" (no value). See *Example I*, and note that zero records in `h2023` exercise either case,
so a test suite built only on 2023 data will not catch this.

## Unresolved

Items that could not be confirmed from the specification or the 2023 data, listed here rather
than guessed.

1. **Whether `U` and `I` origin times are also JST.** The specification's JST note is attached
   to the Year field with "the same applies below", which grammatically covers the remaining
   time fields, but no sentence scopes the time zone by record type. Example G corroborates JST
   for a `U` record against an external catalog (record 10:17:34 JST minus 9 h equals the USGS
   UTC origin time of 01:17:34 for the 2023 Turkey M7.8), so JST is well supported for `U`.
   No `I` record exists in `h2023`, so `I` is untested. Treat all record types as JST.

2. **The exact rounding/truncation JMA applies** when converting internal precision to the
   hundredths-of-a-minute and hundredths-of-a-km fields. Not stated. Round-tripping a decoded
   coordinate back to the file may differ in the last digit.

3. **District number (field 27) and region number (field 28) code lists.** The specification
   refers to "Appendix 1.A.3 Geographical region names", which is not on the format page and
   was not located. Nine district values (`1`-`9`) occur in `h2023`; the mapping from number
   to name is unknown. The 24-character region *name* (field 29) is present on every record, so
   this only blocks validating the numeric codes, not naming the region.

4. **Whether region name (field 29) can be blank.** It is populated on all 257,020 records in
   `h2023`. The specification gives no null representation. Do not assume it is never blank in
   other years.

5. **The "blank after the decimal point in case of fixed hypocenter" case for seconds and for
   latitude/longitude minutes** (fields 7, 10, 13). The specification documents it, but **zero
   records in `h2023` exhibit it** — c16-17, c27-28 and c39-40 are digits on every record.
   The encoding is therefore documented but not empirically confirmed here; it presumably
   appears in older years containing fixed hypocenters. A parser must handle a partially blank
   field without assuming what `h2023` shows.

6. **Codes documented but absent from `h2023`**, so their real-world formatting is unverified:
   record type `I`; magnitude type `J`; magnitudes `B*` and `C*`; travel-time tables `1`-`4`
   and `6`; location precision `4`, `5`, `7`, `8`, `9`; subsidiary information `2` and `3`;
   maximum intensity `5`, `6`, `7`, `C`, `R`, `M`, `S`, `L`, `F`, `X`; damage classes `4`, `5`,
   `6`, `X`, `Y`; tsunami classes `T`, `3`-`6`; determination flags `N` and `F`. All are taken
   from the specification and should be accepted by the parser, but no `h2023` example backs
   them.

7. **Character encoding of the region name in non-2023 years.** `h2023` is pure ASCII. The
   specification says `A24` without naming an encoding. Older files were not checked.

8. **Whether any year's file contains records that are not exactly 96 bytes** (for example a
   trailing partial line or a differing historical layout). Only `h2023` was verified.
   The specification's per-era notes on depth-slice widths imply the layout has been stable,
   but files back to 1919 are published and were not inspected.
