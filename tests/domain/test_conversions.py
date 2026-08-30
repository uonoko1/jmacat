"""Unit conversions that can silently corrupt a scientific result (issue #4).

Sources for every expectation are cited per test. `format doc` means
`docs/jma-hypocenter-format.md`; `h2023`/`h1919` line numbers identify a
verbatim record in the published catalog, which is not committed here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from jmacat.domain.hypocenter import (
    FieldError,
    decimal_degrees,
    depth_km,
    magnitude,
    origin_time,
)


def test_degrees_and_decimal_minutes_are_not_decimal_degrees() -> None:
    """Format doc, Traps 1 and Example A: ` 35` + `4059` is 35.6765 deg.

    35 deg 40.59 min = 35 + 40.59/60 = 35.6765 deg. Reading `354059` as
    35.4059 deg moves the epicentre by roughly 27 km with no error raised.
    """
    assert decimal_degrees(" 35", "4059", field="latitude") == Decimal("35.6765")


def test_the_worked_longitude_of_example_a_decodes_to_the_documented_value() -> None:
    """Format doc, Example A: ` 140` + `3927` is 140.654500 degE."""
    assert decimal_degrees(" 140", "3927", field="longitude") == Decimal("140.6545")


def test_a_minutes_value_below_one_is_not_confused_with_the_degrees() -> None:
    """Format doc, Example E: ` 130` + `0054` is 0.54 min, i.e. 130.009 degE."""
    assert decimal_degrees(" 130", "0054", field="longitude") == Decimal("130.009")


def test_zero_minutes_leave_the_degrees_untouched() -> None:
    """Boundary from issue #4: 0 min contributes exactly nothing."""
    assert decimal_degrees(" 35", "0000", field="latitude") == Decimal("35")


def test_the_largest_minutes_value_in_the_catalog_is_accepted() -> None:
    """59.99 min is the maximum a sexagesimal field can hold.

    Format doc, Traps 4: latitude minutes c25-28 reach exactly 5999 in h2023
    and never 6000, which is what a hundredths-of-a-minute field pinned to a
    60-minute wheel must do. 59.99/60 = 0.999833... so the test states the
    exact rational rather than a rounded decimal.
    """
    assert decimal_degrees(" 35", "5999", field="latitude") == Decimal("35") + Decimal(
        "59.99"
    ) / Decimal(60)


def test_exactly_sixty_minutes_is_rejected_as_out_of_range() -> None:
    """Format doc, Traps 4: no correct slice can reach 60.00 min.

    Issue #4 requires this boundary be rejected or documented. It is rejected:
    a minutes field at or above 60 means the slice is wrong (the doc measures
    124,383 such values one column to the left), and returning
    `35 + 60/60 = 36` would be exactly the plausible wrong answer this project
    exists to prevent.
    """
    with pytest.raises(FieldError) as caught:
        decimal_degrees(" 35", "6000", field="latitude")
    assert caught.value.field == "latitude"


def test_southern_hemisphere_latitude_is_negative() -> None:
    """Format doc, Example E (h2023 line 5901, TANIMBAR IS., INDONESIA).

    Latitude degrees c22-24 are `- 7` - the sign in c22, the digit right
    aligned in c24, a space between them - and minutes c25-28 are `0352`.
    The documented value is -7.058667 deg, i.e. 7.06 degS. 45 records in h2023
    carry a `-` in the latitude degree field.
    """
    assert decimal_degrees("- 7", "0352", field="latitude") == -(
        Decimal(7) + Decimal("3.52") / Decimal(60)
    )


def test_a_sign_separated_from_its_digits_by_a_space_still_parses() -> None:
    """Format doc, Traps 2: `int("- 7")` raises; interior spaces must go first.

    Stated as its own test because the failure mode is an exception on a
    perfectly valid record, not a wrong number.
    """
    assert decimal_degrees("- 7", "0000", field="latitude") == Decimal(-7)


def test_western_hemisphere_longitude_is_negative() -> None:
    """Format doc, Example F (h2023 line 15160, KERMADEC ISL., N.Z.L.).

    Longitude degrees c33-36 are `-178`, minutes c37-40 `3969`, giving
    -178.661500 deg. Truncating the sign column yields +178.6615 - the same
    place mirrored to the far side of the Pacific, with no error raised.
    18 records in h2023 carry a `-` in the longitude degree field.
    """
    assert decimal_degrees("-178", "3969", field="longitude") == Decimal("-178.6615")


def test_a_southern_latitude_is_not_merely_the_positive_value() -> None:
    """Guards the sign explicitly: issue #3 wants negative, not positive."""
    assert decimal_degrees("-30", "1269", field="latitude") < 0


def test_the_sign_applies_to_the_minutes_as_well_as_the_degrees() -> None:
    """Format doc, Traps 2: the minutes field is unsigned and inherits the sign.

    -30 deg 12.69 min is -30.2115 deg (Example F), not -30 + 0.2115 = -29.7885.
    That mistake would move the epicentre by about 47 km while keeping the
    hemisphere right, so it survives any sign-only assertion.
    """
    assert decimal_degrees("-30", "1269", field="latitude") == Decimal("-30.2115")


def test_blank_decimal_minutes_mean_unknown_decimals_not_zero_hundredths() -> None:
    """Format doc, Example I and Traps 9 (h1919 line 1130, the 1923 Kanto event).

    Latitude minutes c25-28 are `06  `: integer part 6, decimals unknown. The
    value is 6.00 min and the latitude 35.100000 degN. The naive
    `int("06  ".strip()) / 100` gives 0.06 min and 35.001000 degN - wrong by
    about 11 km, with no exception raised.
    """
    assert decimal_degrees(" 35", "06  ", field="latitude") == Decimal("35.1")


def test_blank_decimal_longitude_minutes_decode_the_same_way() -> None:
    """Same record: longitude minutes c37-40 are `30  ` = 30.00 min.

    139 deg 30.00 min = 139.500000 degE per Example I.
    """
    assert decimal_degrees(" 139", "30  ", field="longitude") == Decimal("139.5")




def test_a_non_numeric_degree_field_names_the_field() -> None:
    """Issue #3: a non-numeric value in a numeric field is a typed error."""
    with pytest.raises(FieldError) as caught:
        decimal_degrees(" 3X", "0000", field="latitude")
    assert caught.value.field == "latitude"


def test_depth_with_two_trailing_blanks_is_whole_kilometres() -> None:
    """Format doc, Depth and Example A (h2023 line 1, NEAR CHOSHI CITY).

    Field 15 c45-49 has two encodings discriminated by the two trailing blanks
    at c48-49. ` 50  ` is the `I3,2X` depth-slice form: 50 km. Reading it as
    F5.2 gives 0.50 km - a hundredfold error on a field where nothing looks
    wrong (Traps 5). 18,203 records in h2023 use this form.
    """
    assert depth_km(" 50  ") == Decimal(50)


def test_depth_without_trailing_blanks_is_hundredths_of_a_kilometre() -> None:
    """Format doc, Example B: ` 2645` is the depth-free F5.2 form, 26.45 km.

    238,817 records in h2023 use this form.
    """
    assert depth_km(" 2645") == Decimal("26.45")


def test_a_deep_event_decodes_to_hundreds_of_kilometres() -> None:
    """h2023 line 15161-ish, NEAR TORISHIMA IS (verbatim line in the parse tests).

    Depth c45-49 is `40973`, F5.2 (c48-49 not blank), giving 409.73 km. Issue
    #4 asks for at least one deep and one shallow event from real data.
    """
    assert depth_km("40973") == Decimal("409.73")


def test_a_shallow_event_keeps_its_hundredths() -> None:
    """The smallest non-zero F5.2 depth observed in h2023 is `  001` = 0.01 km."""
    assert depth_km("  001") == Decimal("0.01")


def test_a_zero_depth_slice_is_zero_kilometres_not_absent() -> None:
    """Format doc, Example I (h1919 line 1130): depth c45-49 is `  0  ` = 0 km.

    The depth-slice form with an explicit 0; distinct from a blank field.
    """
    assert depth_km("  0  ") == Decimal(0)


def test_a_depth_with_a_blank_final_decimal_keeps_its_tenths() -> None:
    """h1919: 297 records carry one trailing blank, e.g. ` 150 ` on the 1920
    Haiyuan `I` record (h1919 line 383).

    This is the F5.2 branch meeting Traps 9: the integer part is c45-47 and the
    decimals c48-49, of which only the last is blank, so ` 150 ` is 15.0 km -
    the value the format doc itself decodes for that record. Reading the field
    as four whole kilometres digits instead would give 1500 km; across those
    297 records that reading produces depths up to 5400 km, deeper than the
    Earth's radius, while this one tops out at a physically possible 540 km.
    """
    assert depth_km(" 150 ") == Decimal("15.0")


def test_a_wholly_blank_depth_is_absent_rather_than_zero() -> None:
    """Format doc, Traps 6: blank maps to None, never to 0.0.

    No record in either corpus has a blank depth, but a parser must not turn
    an unknown depth into a sea-level one if a future year carries it.
    """
    assert depth_km("     ") is None


def test_an_ordinary_magnitude_is_tenths() -> None:
    """Format doc, Magnitude (`F2.1`) and Example A: `03` is M0.3."""
    assert magnitude("03") == Decimal("0.3")


def test_a_whole_magnitude_keeps_its_scale() -> None:
    """Format doc, Example E (h2023 line 5901): `71` with type `B` is mb 7.1."""
    assert magnitude("71") == Decimal("7.1")


def test_a_negative_magnitude_stays_negative() -> None:
    """Format doc, Example C (h2023 line 4, NE EHIME PREF): `-6` is M-0.6.

    Not M-6.0: the `-` occupies the first character and the tenths digit the
    second. A naive `int("-6") / 10` gives -0.6 here by luck, but see the `A0`
    case below, which the same code cannot decode at all. 24,882 records in
    h2023 - nearly one in ten - carry a negative magnitude 1.
    """
    assert magnitude("-6") == Decimal("-0.6")


def test_the_letter_a_encodes_a_whole_negative_unit() -> None:
    """Format doc, Magnitude and Example D (h2023, SW EHIME PREF): `A0` is M-1.0.

    `A` = -1 whole unit, the second character the tenths. `int("A0")` raises.
    64 records in h2023 carry `A0`.
    """
    assert magnitude("A0") == Decimal("-1.0")


def test_the_letter_a_carries_its_tenths_digit() -> None:
    """Format doc: `A1` … `A9` are M-1.1 … M-1.9. 12 records in h2023 are `A1`.

    Distinguishes the whole-unit offset from the tenths: a decoder that read
    `A` as a flat -1.0 would pass the `A0` case and fail here.
    """
    assert magnitude("A1") == Decimal("-1.1")


def test_the_letters_b_and_c_encode_two_and_three_negative_units() -> None:
    """Format doc, Magnitude: `B0` is M-2.0 and `C0` M-3.0.

    Neither occurs in h2023 or h1919 (the doc lists them under Unresolved 6 as
    documented but unobserved), so these expectations come from the
    specification's own table rather than from a record.
    """
    assert magnitude("B0") == Decimal("-2.0")
    assert magnitude("C9") == Decimal("-3.9")


def test_a_blank_magnitude_is_absent_rather_than_zero() -> None:
    """Format doc, Magnitude: two blanks mean no magnitude was determined.

    9,973 records in h2023. M0.0 is a real, different statement from "not
    determined", and Traps 6 forbids collapsing the two.
    """
    assert magnitude("  ") is None


def test_an_undocumented_magnitude_letter_is_rejected() -> None:
    """Only `-`, `A`, `B` and `C` are documented in the leading position.

    Anything else is an unknown encoding, and CONTRIBUTING's "fail loudly"
    rule prefers an error over a guess at what a future JMA code might mean.
    """
    with pytest.raises(FieldError) as caught:
        magnitude("Z0")
    assert caught.value.field == "magnitude"


def test_the_origin_time_is_returned_in_japan_standard_time() -> None:
    """Format doc, *Time zone*: origin times are JST (UTC+9), not UTC.

    JMA states this only on the English layout table, in the Year field:
    "Year of origin time (Japan Standard Time = UTC + 9 h; the same applies
    below.)". The Japanese table does not mention a time zone at all. A naive
    datetime would let a caller compare it against a UTC catalog and be nine
    hours out with nothing raised, so the offset is carried explicitly.

    Fields from Example A (h2023 line 1): 2023-01-01 00:08 with seconds `0150`.
    """
    when = origin_time("2023", "01", "01", "00", "08", "0150")
    assert when == datetime(
        2023, 1, 1, 0, 8, 1, 500000, tzinfo=timezone(timedelta(hours=9))
    )


def test_the_returned_datetime_is_never_naive() -> None:
    """Issue #4: state the time zone in code, do not leave it implicit."""
    when = origin_time("2023", "01", "01", "00", "08", "0150")
    assert when is not None
    assert when.utcoffset() == timedelta(hours=9)


def test_subtracting_nine_hours_reproduces_the_external_utc_catalogue() -> None:
    """Format doc, Example G (h2023): the 2023 Kahramanmaras, Turkey M7.8.

    The record reads 2023-02-06 10:17:34.34; USGS gives the origin time as
    2023-02-06 01:17:34 UTC. That the two agree after a 9 h shift confirms the
    JST reading against a catalog outside JMA, which is the only independent
    check available for the time zone.
    """
    when = origin_time("2023", "02", "06", "10", "17", "3434")
    assert when is not None
    assert when.astimezone(UTC) == datetime(2023, 2, 6, 1, 17, 34, 340000, tzinfo=UTC)


def test_the_fractional_second_is_hundredths_not_a_bare_integer() -> None:
    """Format doc, field 7: seconds are `F4.2`, i.e. seconds x 100.

    `5595` is 55.95 s (Example C). Reading the four digits as whole seconds
    would overflow the minute; reading them as milliseconds would give 5.595 s.
    """
    when = origin_time("2023", "01", "01", "00", "19", "5595")
    assert when is not None
    assert (when.second, when.microsecond) == (55, 950000)


def test_a_blank_second_field_leaves_the_time_at_the_minute() -> None:
    """Format doc, Example I (h1919 line 1130, the 1923 Kanto event).

    Seconds c14-17 are entirely blank - "seconds unknown", not zero. 18 records
    in h1919 do this. The event is still located to the minute, 12:03 JST, so
    the time is returned with second 0 and the *field* recorded as absent;
    see `test_a_blank_second_field_is_reported_as_absent` in the parse tests
    for the flag that keeps "unknown" distinguishable from "exactly 00.00 s".
    """
    when = origin_time("1923", "09", "01", "12", "03", "    ")
    assert when == datetime(1923, 9, 1, 12, 3, tzinfo=timezone(timedelta(hours=9)))


def test_a_second_field_with_blank_decimals_keeps_its_whole_seconds() -> None:
    """Format doc, Traps 9: 3 records in h1919 have blank second decimals.

    `54  ` is 54.00 s. The naive strip-and-divide reads it as 0.54 s.
    """
    when = origin_time("1923", "09", "01", "12", "03", "54  ")
    assert when is not None
    assert (when.second, when.microsecond) == (54, 0)


def test_a_non_numeric_time_field_names_the_field() -> None:
    """Issue #3: a typed error naming the offending field."""
    with pytest.raises(FieldError) as caught:
        origin_time("2O23", "01", "01", "00", "08", "0150")
    assert caught.value.field == "year"


def test_an_impossible_calendar_date_is_rejected() -> None:
    """A day of 32 is not a date. `datetime` would raise; the error is typed."""
    with pytest.raises(FieldError) as caught:
        origin_time("2023", "01", "32", "00", "08", "0150")
    assert caught.value.field == "origin time"


def test_blank_minutes_with_degrees_present_mean_whole_degree_precision() -> None:
    """h1919: 7 records have degrees present and minutes c25-28 wholly blank.

    Verbatim, the first of them (a 1923 Kanto aftershock, `SAGAMI BAY ?`):

        J192309011201         35         13930        0     65J    325Y     ...

    Latitude degrees c22-24 are ` 35` and minutes c25-28 `    `. All 7 carry
    location precision `3` (fixed depth, human judgement) in c60.

    The format doc does not describe this case: its Traps 9 contrasts "integer
    present, decimals blank" with "the field blank in its entirety", but for
    the *minutes* field it does not consider degrees present with minutes
    wholly absent. The reading taken here is that the epicentre is known to the
    whole degree - 35 degN - which is what the degree field says on its own.

    Rejecting the record instead would discard 7 real epicentres over a
    coarser precision, and substituting any non-zero minutes value would invent
    a position JMA did not publish. `minutes_are_known` carries the reduced
    precision so this does not masquerade as an exact 35.000000.
    """
    assert decimal_degrees(" 35", "    ", field="latitude") == Decimal(35)
