"""Unit conversions that can silently corrupt a scientific result (issue #4).

Sources for every expectation are cited per test. `format doc` means
`docs/jma-hypocenter-format.md`; `h2023`/`h1919` line numbers identify a
verbatim record in the published catalog, which is not committed here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jmacat.domain.hypocenter import FieldError, decimal_degrees


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
