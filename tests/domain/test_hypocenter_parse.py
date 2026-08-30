"""Parsing a 96-byte JMA hypocenter record into a typed value object.

Every expectation here traces to `docs/jma-hypocenter-format.md` or to a
verbatim line from the published catalog, cited per test. No expected value in
this file was invented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from jmacat.domain.hypocenter import (
    JST,
    FieldError,
    RecordLengthError,
    RecordType,
    parse_record,
)

# Verbatim records from the published catalog, each 96 bytes. The catalog
# itself is not committed (JMA terms; see docs/jma-hypocenter-format.md), so
# the lines used as expectations are pasted here with their provenance.

NEAR_CHOSHI = (
    "J2023010100080150 012 354059 100 1403927 136 50     03v   721   3110"
    "NEAR CHOSHI CITY          9A"
)
"""h2023 line 1. Format doc, Example A: an ordinary domestic event."""

NE_EHIME = (
    "J2023010100195595     340134     1333676     3427   -6v   5M5   6236"
    "NE EHIME PREF             3a"
)
"""h2023 line 4. Format doc, Example C: magnitude 1 is `-6`, i.e. M-0.6."""

TANIMBAR = (
    "U2023011002473504    - 70352     1300054    105     71B       219   "
    "TANIMBAR IS., INDONESIA     "
)
"""h2023 line 5901. Format doc, Example E: a `U` record at 7.06 degS."""

KERMADEC = (
    "U2023012619455283    -301269    -1783969    131     56B         9   "
    "KERMADEC ISL., N.Z.L.       "
)
"""h2023 line 15160. Format doc, Example F: longitude 178.66 degW."""

TORISHIMA = (
    "J2023011513421290 031 295568 114 1392858 1704097344154D52W7111  8331"
    "NEAR TORISHIMA IS        25K"
)
"""h2023: a deep event, depth c45-49 `40973` = 409.73 km in the F5.2 form."""

SAGAMI_BAY = (
    "J192309011203         3506       13930        0     73J    325Y     "
    "SAGAMI BAY ?               K"
)
"""h1919 line 1130. Format doc, Example I: the 1923 Great Kanto earthquake.

Carries blank decimal parts in latitude minutes (`06  `) and longitude minutes
(`30  `), and a wholly blank second field.
"""

HAIYUAN = (
    "I1920121621055446     365220     1053714     150    83W             "
    "W NEI MONGOL, CHINA         "
)
"""h1919 line 383. The 1920 Haiyuan M8.3 - the only `I` record the format doc
decodes, at *Unresolved* item 1. This fixture is byte-identical to the line
quoted there, and both are byte-identical to the file: an earlier revision of
the doc quoted it with a spurious `9` in the district column and four bytes
too many, which this PR corrects. The decoded values were never affected -
36.870 degN, 105.619 degE, 15 km, M8.3 - and are what this fixture asserts.
"""


def test_the_fixtures_are_all_96_bytes() -> None:
    """A fixture mistyped to the wrong width would test the wrong columns.

    Every line above is a real record, and the format doc's record-width
    section establishes that every record in both corpora is exactly 96 bytes.
    A fixture that is not is a transcription error, not a finding.
    """
    for line in (
        NEAR_CHOSHI,
        NE_EHIME,
        TANIMBAR,
        KERMADEC,
        TORISHIMA,
        SAGAMI_BAY,
        HAIYUAN,
        CENTRAL_KURILE,
        OFF_SHIKOTAN_PRECISE_LATITUDE,
        OFF_SHIKOTAN_PRECISE_LONGITUDE,
    ):
        assert len(line) == 96, line


def test_a_line_that_is_not_96_bytes_is_rejected() -> None:
    """Field table: the record is 96 bytes; the terminator is not part of it.

    A short line must fail loudly rather than be sliced blindly - the format
    doc's "Record width is stable across eras" says a parser should reject a
    line whose length is not 96 instead of slicing it.
    """
    with pytest.raises(RecordLengthError) as caught:
        parse_record("J2023")
    assert caught.value.length == 5


def test_the_length_error_is_not_a_field_error() -> None:
    """A malformed *line* is a different failure from a malformed *field*."""
    assert not issubclass(RecordLengthError, FieldError)


def test_a_nominal_domestic_event_decodes_to_the_documented_values() -> None:
    """Format doc, Example A (h2023 line 1, NEAR CHOSHI CITY).

    Every field below is the doc's own decoded value for that record:
    2023-01-01 00:08:01.50 JST, 35.676500 degN, 140.654500 degE, 50 km
    (depth-slice form), M0.3 of type `v`.
    """
    event = parse_record(NEAR_CHOSHI)
    assert event.record_type is RecordType.JMA
    assert event.origin_time == datetime(2023, 1, 1, 0, 8, 1, 500000, tzinfo=JST)
    assert event.latitude == Decimal("35.6765")
    assert event.longitude == Decimal("140.6545")
    assert event.depth_km == Decimal(50)
    assert event.magnitude == Decimal("0.3")
    assert event.magnitude_type == "v"
    assert event.region_name == "NEAR CHOSHI CITY"
    assert event.station_count == 9


def test_a_southern_hemisphere_record_yields_a_negative_latitude() -> None:
    """Format doc, Example E (h2023 line 5901, TANIMBAR IS., INDONESIA).

    Latitude degrees c22-24 are `- 7`, minutes `0352`, giving -7.058667 deg -
    not a positive value, and not an exception (issue #3). Depth c45-49 is
    `105  `, the I3,2X form, so 105 km. Magnitude `71` type `B` is mb 7.1.
    """
    event = parse_record(TANIMBAR)
    assert event.record_type is RecordType.USGS
    assert event.latitude == -(Decimal(7) + Decimal("3.52") / 60)
    assert event.latitude < 0
    assert event.longitude == Decimal("130.009")
    assert event.depth_km == Decimal(105)
    assert event.magnitude == Decimal("7.1")
    assert event.magnitude_type == "B"


def test_a_western_hemisphere_record_yields_a_negative_longitude() -> None:
    """Format doc, Example F (h2023 line 15160, KERMADEC ISL., N.Z.L.).

    Longitude degrees c33-36 are `-178`. Truncating the sign column - the error
    the format doc records as having been made once already - gives +178.6615,
    the same latitude half a world away, with nothing raised.
    """
    event = parse_record(KERMADEC)
    assert event.longitude == Decimal("-178.6615")
    assert event.longitude < 0
    assert event.latitude == Decimal("-30.2115")


def test_a_negative_magnitude_survives_the_parse() -> None:
    """Format doc, Example C (h2023 line 4, NE EHIME PREF): `-6` is M-0.6."""
    event = parse_record(NE_EHIME)
    assert event.magnitude == Decimal("-0.6")
    assert event.depth_km == Decimal("34.27")


def test_a_deep_event_keeps_its_hundredths_of_a_kilometre() -> None:
    """h2023, NEAR TORISHIMA IS: depth c45-49 `40973` is F5.2, 409.73 km.

    Also carries a second magnitude: c56-57 `52` with type `W` is MW 5.2, the
    JMA CMT solution for a `J` record (format doc, Magnitude type codes).
    """
    event = parse_record(TORISHIMA)
    assert event.depth_km == Decimal("409.73")
    assert event.magnitude == Decimal("5.4")
    assert event.magnitude_type == "D"
    assert event.magnitude_2 == Decimal("5.2")
    assert event.magnitude_type_2 == "W"


def test_blank_decimal_minutes_decode_to_the_documented_coordinate() -> None:
    """Format doc, Example I (h1919 line 1130, the 1923 Great Kanto earthquake).

    Latitude minutes c25-28 are `06  ` and longitude minutes c37-40 `30  `:
    integer part present, decimals blank. The doc decodes them as 35.100000
    degN and 139.500000 degE. The naive strip-and-divide gives 35.001 degN,
    about 11 km away, and raises nothing.
    """
    event = parse_record(SAGAMI_BAY)
    assert event.latitude == Decimal("35.1")
    assert event.longitude == Decimal("139.5")
    assert event.magnitude == Decimal("7.3")
    assert event.magnitude_type == "J"
    assert event.depth_km == Decimal(0)


def test_a_blank_second_field_is_reported_as_absent() -> None:
    """Same record: seconds c14-17 are wholly blank - unknown, not 00.00 s.

    Format doc, Traps 6 and 9 distinguish "integer present, decimals blank" (a
    real value at lower precision, as the minutes above) from "wholly blank"
    (no value). The datetime still has to render some second, so the flag is
    what keeps the two apart for a caller.
    """
    event = parse_record(SAGAMI_BAY)
    assert event.second_is_known is False
    assert event.origin_time == datetime(1923, 9, 1, 12, 3, tzinfo=JST)


def test_a_known_second_of_zero_is_distinguishable_from_an_unknown_second() -> None:
    """The flag must not merely restate `second == 0` (Traps 6).

    Built from the Kanto record by writing an explicit `0000` into c14-17, so
    the two cases differ in exactly the one field under test.
    """
    explicit_zero = SAGAMI_BAY[:13] + "0000" + SAGAMI_BAY[17:]
    event = parse_record(explicit_zero)
    assert event.origin_time.second == 0
    assert event.second_is_known is True


def test_an_international_record_parses_as_its_own_type() -> None:
    """h1919 line 383, the 1920 Haiyuan M8.3 - an `I` record.

    Format doc, Unresolved 1 decodes it as 1920-12-16 21:05:54.46 JST,
    36.870 degN, 105.619 degE, 15 km, M8.3, and confirms the JST reading by
    subtracting 9 h to reach the conventional 12:05 UTC.
    """
    event = parse_record(HAIYUAN)
    assert event.record_type is RecordType.INTERNATIONAL
    assert event.latitude == Decimal("36.87")
    assert event.longitude == Decimal("105.619")
    assert event.magnitude == Decimal("8.3")
    assert event.origin_time.astimezone(UTC).hour == 12


def test_an_international_record_carries_the_documented_depth() -> None:
    """Same record: depth c45-49 is ` 150 `, one trailing blank only.

    Not the I3,2X form (which needs both c48-49 blank), so it is F5.2 with a
    blank final decimal: 15.0 km, which is the depth the format doc states.
    """
    event = parse_record(HAIYUAN)
    assert event.depth_km == Decimal("15.0")


def test_a_blank_region_block_is_absent_rather_than_empty_or_zero() -> None:
    """Format doc, Unresolved 4: the region name can be blank on `I` records.

    On the Haiyuan record the district (c65), region number (c66-68) and
    station count (c93-95) are all blank as well. Traps 6: blank is `None`.
    """
    event = parse_record(HAIYUAN)
    assert event.district is None
    assert event.region_number is None
    assert event.station_count is None
    assert event.magnitude_2 is None


def test_the_district_number_may_lie_outside_the_appendix() -> None:
    """Format doc, Unresolved 3: district `9` has no `regname9.html` page.

    73 of the 87 `U` records in h2023 use it. A parser must not assume the
    appendix's districts 1-8 are exhaustive, so the number is carried as a
    number and not validated against the table.
    """
    event = parse_record(TANIMBAR)
    assert event.district == 9
    assert event.region_number is None


def test_the_numeric_region_pair_is_kept_alongside_the_name() -> None:
    """Format doc, District and region numbers: the pair is the stable key.

    Region name text is not byte-stable across years - the doc finds district
    8 / region 324 written two ways - so the numbers are what a caller should
    key on. Example A gives district 3, region 110, NEAR CHOSHI CITY.
    """
    event = parse_record(NEAR_CHOSHI)
    assert (event.district, event.region_number) == (3, 110)


def test_a_hypocenter_is_immutable() -> None:
    """Issue #3 asks for an immutable value object."""
    event = parse_record(NEAR_CHOSHI)
    with pytest.raises(Exception):  # noqa: B017 - dataclass raises FrozenInstanceError
        event.latitude = Decimal(0)  # type: ignore[misc]


def test_two_parses_of_the_same_line_are_equal() -> None:
    """A value object compares by value, not identity."""
    assert parse_record(NEAR_CHOSHI) == parse_record(NEAR_CHOSHI)


def test_a_non_numeric_latitude_is_rejected_naming_the_field() -> None:
    """Issue #3: a typed error that names the offending field.

    Built by corrupting c25-28 of the Example A record, so the line stays 96
    bytes and only the field under test is invalid.
    """
    corrupt = NEAR_CHOSHI[:24] + "4O59" + NEAR_CHOSHI[28:]
    with pytest.raises(FieldError) as caught:
        parse_record(corrupt)
    assert caught.value.field == "latitude"
    assert "latitude" in str(caught.value)


def test_a_non_numeric_depth_is_rejected_naming_the_field() -> None:
    """Corrupting c45-49 of Example A, keeping the two trailing blanks."""
    corrupt = NEAR_CHOSHI[:44] + " 5O  " + NEAR_CHOSHI[49:]
    with pytest.raises(FieldError) as caught:
        parse_record(corrupt)
    assert caught.value.field == "depth"


def test_an_unknown_record_type_is_rejected() -> None:
    """Format doc, field 1: only `J`, `U` and `I` are defined.

    An unrecognised type may well mean a layout this parser does not know, so
    CONTRIBUTING's "fail loudly" rule prefers an error to a guess.
    """
    with pytest.raises(FieldError) as caught:
        parse_record("X" + NEAR_CHOSHI[1:])
    assert caught.value.field == "record type"


def test_a_line_one_byte_too_long_is_rejected() -> None:
    """Format doc, Traps 4: a one-column shift produces a plausible value.

    A 97-byte line would silently shift every field past the inserted byte, so
    the length is checked before any slice.
    """
    with pytest.raises(RecordLengthError):
        parse_record(NEAR_CHOSHI + " ")


def test_a_trailing_newline_is_not_silently_accepted() -> None:
    """The 96 bytes exclude the terminator (format doc, Sources).

    A caller that forgets to strip the newline must be told, not given a record
    parsed from 96 of its 97 bytes.
    """
    with pytest.raises(RecordLengthError):
        parse_record(NEAR_CHOSHI + "\n")


CENTRAL_KURILE = (
    "J192501182105         47         154         60     74J    322      "
    "CENTRAL KURILE IS          K"
)
"""h1919 line 2263. Both minutes fields wholly blank: 47 degN, 154 degE.

One of the 4 h1919 records whose *longitude* minutes c37-40 are wholly blank,
and one of the 7 whose latitude minutes c25-28 are. All 4 and all 7 carry
location precision `3` (fixed depth, human judgement) in c60.
"""

OFF_SHIKOTAN_PRECISE_LATITUDE = (
    "J192502011424         4330       148         60     64J    32       "
    "OFF SHIKOTAN IS            K"
)
"""h1919 line 2284. Latitude minutes `30  ` present, longitude minutes blank.

The two flags move independently, and this record is what proves it: latitude
is determined to 43 deg 30.00 min while longitude is published only as the
whole 148 degE. A parser that derived one flag from the other - or held either
constant - would decode this record with a precision claim JMA did not make.
"""

OFF_SHIKOTAN_PRECISE_LONGITUDE = (
    "J192502030712         43         14730       60     63J    321      "
    "OFF SHIKOTAN IS            K"
)
"""h1919 line 2292. The mirror of the previous record: latitude minutes c25-28
wholly blank at 43 degN, longitude minutes c37-40 `30  ` giving 147.5 degE.

Together the two records exercise both flags in both states, so neither can be
satisfied by a constant.
"""


def test_a_whole_degree_epicentre_is_flagged_as_reduced_precision() -> None:
    """h1919, a 1923 Kanto aftershock. Verbatim, 96 bytes:

        J192309011201         35         13930        0     65J    325Y     ...

    Latitude minutes c25-28 are wholly blank, so the epicentre is known only to
    the whole degree, 35 degN. 7 records in h1919 do this and none in h2023.
    The format doc does not describe the case (see the conversion test of the
    same name), so the flag exists to stop a decoded 35.000000 from reading as
    a determination to the hundredth of a minute.
    """
    aftershock = (
        "J192309011201         35         13930        0     65J    325Y     "
        "SAGAMI BAY ?              5K"
    )
    assert len(aftershock) == 96
    event = parse_record(aftershock)
    assert event.latitude == Decimal(35)
    assert event.latitude_minutes_are_known is False
    assert event.longitude == Decimal("139.5")
    assert event.longitude_minutes_are_known is True


def test_an_ordinary_record_is_not_flagged_as_reduced_precision() -> None:
    """The flags must not be constant: Example A has both minutes fields."""
    event = parse_record(NEAR_CHOSHI)
    assert event.latitude_minutes_are_known is True
    assert event.longitude_minutes_are_known is True


def test_a_whole_degree_longitude_is_flagged_as_reduced_precision() -> None:
    """h1919 line 2263, CENTRAL KURILE IS - both minutes fields wholly blank.

    4 records in h1919 have longitude minutes c37-40 wholly blank, against 7
    for latitude; the counts differ because the two fields are blanked
    independently. Longitude degrees c33-36 are ` 154`, so the epicentre is
    published as the whole 154 degE.

    Without the flag, a decoded 154 is indistinguishable from a determination
    of 154 deg 00.00 min - a claim of precision to the hundredth of a minute,
    about 15 m, that JMA never made for this 1925 record.
    """
    event = parse_record(CENTRAL_KURILE)
    assert event.latitude == Decimal(47)
    assert event.latitude_minutes_are_known is False
    assert event.longitude == Decimal(154)
    assert event.longitude_minutes_are_known is False


def test_the_two_minute_flags_are_independent_of_each_other() -> None:
    """h1919 lines 2284 and 2292: each field blank while the other is present.

    These two OFF SHIKOTAN IS records are mirror images. Line 2284 has latitude
    minutes `30  ` with longitude minutes blank; line 2292 has latitude minutes
    blank with longitude minutes `30  `. So each flag is observed True while
    the other is False, in real data.

    This is what a constant cannot satisfy: hard-wiring either flag to `True`
    or deriving longitude's from latitude's passes any single-record test but
    fails one of these two.
    """
    precise_latitude = parse_record(OFF_SHIKOTAN_PRECISE_LATITUDE)
    assert precise_latitude.latitude == Decimal("43.5")
    assert precise_latitude.latitude_minutes_are_known is True
    assert precise_latitude.longitude == Decimal(148)
    assert precise_latitude.longitude_minutes_are_known is False

    precise_longitude = parse_record(OFF_SHIKOTAN_PRECISE_LONGITUDE)
    assert precise_longitude.latitude == Decimal(43)
    assert precise_longitude.latitude_minutes_are_known is False
    assert precise_longitude.longitude == Decimal("147.5")
    assert precise_longitude.longitude_minutes_are_known is True


def test_a_whole_degree_epicentre_south_and_west_keeps_its_signs() -> None:
    """The whole-degree branch must carry the sign through, in a full record.

    **The input line is constructed, not sampled.** Neither corpus holds a
    record combining a negative degree field with wholly blank minutes, so
    CONTRIBUTING's preference for verbatim lines cannot be honoured here and
    the case would otherwise go untested: with the sign dropped from that
    branch, every test in this suite still passes.

    The line is the Kermadec record above (h2023 line 15160, format doc
    Example F) with only its two minutes fields blanked, so every other column
    remains a real record's bytes and the degree fields `-30` and `-178` are
    JMA's own. Only the combination is synthetic.

    It is a combination the catalog can produce: `h1919` holds 344 records with
    a negative latitude degree field and 170 with a negative longitude one, and
    separately 7 and 4 records with the corresponding minutes field blank. A
    year not yet sampled may hold a record in both sets, and reading it without
    the sign would place the epicentre in the wrong hemisphere - 30 degN 178
    degE instead of 30 degS 178 degW, roughly 13,000 km away - with nothing
    raised. The format doc's Traps 2 records that exact mistake being made once
    already on this very record.
    """
    southwest_whole_degree = (
        "U2023012619455283    -30        -178        131     56B         9   "
        "KERMADEC ISL., N.Z.L.       "
    )
    assert len(southwest_whole_degree) == 96
    event = parse_record(southwest_whole_degree)
    assert event.latitude == Decimal(-30)
    assert event.longitude == Decimal(-178)
    assert event.latitude_minutes_are_known is False
    assert event.longitude_minutes_are_known is False


def test_a_sign_in_the_second_column_of_the_degree_field_still_parses() -> None:
    """h1919 lines 50 and 74, verbatim. The sign is not always in column 1.

    h2023 writes the minus in the leftmost column of the degree field, which
    is what the format doc's Traps 2 describes. h1919 does not: 148 latitude
    fields and 79 longitude fields there carry the sign in the *second*
    column - ` -5`, ` -4` - with the digit right-aligned after it.

    So a `raw.startswith("-")` reading of the sign, which looks like a
    tightening of the loose `"-" in raw` check the parser uses, would decode
    227 real records into the northern hemisphere with nothing raised. These
    two pin the looseness: S Sumatera is 5.49 degS and New Ireland 4.81 degS,
    both several hundred km from their mirrored positive values.
    """
    sumatera = (
        "I1919040209345958     -52958     1042934     200    64W             "
        "S SUMATERA, INDONESIA       "
    )
    new_ireland = (
        "I1919050704411301     -44836     1535154     350    82W             "
        "NEW IRELAND, P.N.G.         "
    )
    assert len(sumatera) == 96
    assert len(new_ireland) == 96

    event = parse_record(sumatera)
    assert event.latitude == Decimal("-5.493")
    assert event.longitude == Decimal("104.489")

    event = parse_record(new_ireland)
    assert event.latitude == Decimal("-4.806")
    assert event.longitude == Decimal("153.859")


def test_a_written_zero_station_count_is_zero_not_absent() -> None:
    """h1919 carries 247 records whose station count c93-95 is written `  0`.

    Traps 6 runs in both directions. A blank field must not become 0, and an
    explicitly written 0 must not become None: JMA distinguishes "no station
    count published" from "zero stations contributed", and h2023 contains no
    written zero at all, so only the historical file exercises this.
    """
    gunma = (
        "J1922011412085902     362422     1383157      0           574   3 81"
        "NW GUNMA PREF             0S"
    )
    assert len(gunma) == 96
    event = parse_record(gunma)
    assert event.station_count == 0
    assert event.station_count is not None
    # The same record has no magnitude at all (c53-57 blank), so the two
    # readings of an empty field sit side by side in one record: a blank
    # magnitude is None while a written-zero station count is 0.
    assert event.magnitude is None
    assert event.magnitude_type is None
    assert event.magnitude_2 is None
    assert event.district == 3
    assert event.region_number == 81


def test_a_field_error_reports_the_columns_it_could_not_decode() -> None:
    """The error must locate the bytes, not just name the field.

    A record is 96 undelimited characters, so "latitude" alone leaves an
    operator counting columns by hand against the specification. Latitude
    minutes are c25-28 (format doc, field 10).
    """
    corrupt = NEAR_CHOSHI[:24] + "4O59" + NEAR_CHOSHI[28:]
    with pytest.raises(FieldError) as caught:
        parse_record(corrupt)
    assert caught.value.columns == "25-28"
    assert "25-28" in str(caught.value)


def test_a_longitude_error_reports_the_longitude_columns() -> None:
    """Triangulates the previous test: the columns must track the field.

    Longitude minutes are c37-40, a different span from latitude's c25-28, so
    a hardcoded string cannot satisfy both.
    """
    corrupt = NEAR_CHOSHI[:36] + "39X7" + NEAR_CHOSHI[40:]
    with pytest.raises(FieldError) as caught:
        parse_record(corrupt)
    assert caught.value.columns == "37-40"
