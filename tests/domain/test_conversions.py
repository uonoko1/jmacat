"""Unit conversions that can silently corrupt a scientific result (issue #4).

Sources for every expectation are cited per test. `format doc` means
`docs/jma-hypocenter-format.md`; `h2023`/`h1919` line numbers identify a
verbatim record in the published catalog, which is not committed here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jmacat.domain.hypocenter import FieldError, decimal_degrees, depth_km


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
    assert decimal_degrees(" 35", "5999", field="latitude") == Decimal(
        "35"
    ) + Decimal("59.99") / Decimal(60)


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


def test_wholly_blank_minutes_are_rejected_rather_than_read_as_zero() -> None:
    """Format doc, Traps 6 and 9: a wholly blank field is absent, not zero.

    Distinguished from the blank-*decimals* case above. A coordinate needs its
    minutes, so absence here is an error rather than a silent `35.000000`.
    """
    with pytest.raises(FieldError) as caught:
        decimal_degrees(" 35", "    ", field="latitude")
    assert caught.value.field == "latitude"


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
