"""The JMA hypocenter record: layout, decoding and physical units.

Standard library only (see CONTRIBUTING.md). Every column constant and every
conversion here traces to `docs/jma-hypocenter-format.md`, which reproduces
JMA's own layout table at
<https://www.data.jma.go.jp/eqev/data/bulletin/data/format/hypfmt_e.html>.

The governing rule for this module is CONTRIBUTING's "prefer failing loudly
over returning a value that might be wrong". Every field that cannot be decoded
raises a typed error naming the field; nothing falls back to a plausible value.
"""

from __future__ import annotations

from decimal import Decimal

RECORD_LENGTH = 96
"""Bytes per record, excluding the LF terminator (format doc, field table)."""


class RecordError(Exception):
    """Base class for every failure to decode a hypocenter record."""


class RecordLengthError(RecordError):
    """The line is not exactly `RECORD_LENGTH` bytes.

    Kept distinct from `FieldError`: the line never reached field decoding, so
    no field can be blamed. The format doc's "Record width is stable across
    eras" section requires rejecting such a line rather than slicing it, since
    a short line would otherwise silently yield blank - and therefore `None` -
    for every field past its end.
    """

    def __init__(self, length: int) -> None:
        self.length = length
        super().__init__(
            f"A hypocenter record must be {RECORD_LENGTH} bytes, got {length}."
        )


class FieldError(RecordError):
    """A single field could not be decoded. Names the offending field."""

    def __init__(self, field: str, columns: str, raw: str, reason: str) -> None:
        self.field = field
        self.columns = columns
        self.raw = raw
        self.reason = reason
        super().__init__(f"{field} (columns {columns}) is {raw!r}: {reason}")


MINUTES_PER_DEGREE = Decimal(60)
"""Sexagesimal wheel. A minutes field reaching 60 means the slice is wrong."""


def _signed_degrees(raw: str, *, field: str) -> tuple[int, Decimal]:
    """Split a degree field into its sign and magnitude.

    Format doc, Traps 2: the sign lives in the leftmost column of the *degree*
    field and the digits are right-aligned, so a one-digit southern latitude
    reads `- 7` - a space *between* the sign and the digit. `int("- 7")`
    raises, so interior spaces are removed before converting. The minutes field
    is always unsigned and inherits this sign.
    """
    sign = -1 if "-" in raw else 1
    digits = raw.replace("-", "").replace(" ", "")
    if not digits.isdigit():
        raise FieldError(field, "degrees", raw, "not an integer number of degrees")
    return sign, Decimal(digits)


def _fixed_point(raw: str, *, field: str, columns: str) -> Decimal | None:
    """Decode a JMA fixed-point field (`F4.2`, `F5.2`, `F3.2`).

    Format doc, Traps 9: these fields are *fixed-position*. The last two
    columns hold the two decimal places and the leading columns the integer
    part. JMA blanks the decimal columns when the hypocenter is fixed while
    keeping the integer part in place, so `.strip()` on the whole field deletes
    the decimals rather than the padding and the surviving digits are then read
    as if they had been decimals - `int("06  ".strip()) / 100` gives 0.06 min
    where the truth is 6.00 min, an 11 km error that raises nothing.

    So the two parts are sliced separately. Blank decimals mean *unknown
    decimals* on a value that is present; a wholly blank field means *no value*
    and returns `None` (Traps 6).
    """
    integer_part, decimal_part = raw[:-2].strip(), raw[-2:].strip()
    if not integer_part and not decimal_part:
        return None
    if integer_part and not integer_part.isdigit():
        raise FieldError(field, columns, raw, "integer part is not a number")
    if decimal_part and not decimal_part.isdigit():
        raise FieldError(field, columns, raw, "decimal part is not a number")
    # A blank decimal part contributes 0 to the arithmetic; the value is the
    # integer part at reduced precision, not an absent value.
    return Decimal(integer_part or 0) + Decimal(decimal_part or 0) / 100


def decimal_degrees(degrees: str, minutes: str, *, field: str) -> Decimal:
    """Degrees plus decimal minutes -> decimal degrees, sign included.

    Format doc, Traps 1: `354059` in c22-28 is 35 deg 40.59 min = 35.6765 deg,
    not 35.4059 deg - the two differ by roughly 27 km. Traps 2: the sign from
    the degree field applies to the minutes as well.
    """
    sign, whole = _signed_degrees(degrees, field=field)
    fraction = _fixed_point(minutes, field=field, columns="minutes")
    if fraction is None:
        raise FieldError(field, "minutes", minutes, "minutes are blank")
    if fraction >= MINUTES_PER_DEGREE:
        raise FieldError(
            field,
            "minutes",
            minutes,
            f"{fraction} minutes is not below {MINUTES_PER_DEGREE}; "
            "a sexagesimal field can never reach 60, so the slice is wrong",
        )
    return sign * (whole + fraction / MINUTES_PER_DEGREE)


NEGATIVE_MAGNITUDE_UNITS = {"-": 0, "A": 1, "B": 2, "C": 3}
"""Leading character -> whole magnitude units to subtract (format doc).

`-1`…`-9` are M-0.1…M-0.9, `A0`…`A9` M-1.0…M-1.9, `B*` M-2.x and `C*` M-3.x.
`B` and `C` occur in neither corpus but are specified, so they are handled.
"""


def magnitude(raw: str) -> Decimal | None:
    """Field 17 or 19 (`F2.1`) -> a signed magnitude.

    Format doc, *Magnitude* and Traps 3: micro-earthquakes go below zero and
    JMA writes the sign into the first character. `-6` is M-0.6, not M-6.0,
    and `A0` is M-1.0, which `int(raw) / 10` cannot decode at all. Nearly one
    in ten h2023 records carries a negative magnitude 1.

    Two blanks mean no magnitude was determined, which returns `None` rather
    than M0.0 (Traps 6).
    """
    if not raw.strip():
        return None
    head, tenths = raw[0], raw[1:]
    if not tenths.isdigit():
        raise FieldError("magnitude", "53-54/56-57", raw, "tenths digit is not a digit")
    if head.isdigit():
        return Decimal(f"{head}.{tenths}")
    units = NEGATIVE_MAGNITUDE_UNITS.get(head)
    if units is None:
        raise FieldError(
            "magnitude", "53-54/56-57", raw, f"unknown magnitude sign code {head!r}"
        )
    return -(Decimal(units) + Decimal(tenths) / 10)


def depth_km(raw: str) -> Decimal | None:
    """Field 15 (c45-49) -> kilometres, honouring both of its encodings.

    Format doc, *Depth*: this is the only field with two meanings, and the
    reliable discriminator is the two trailing blanks at c48-49.

    * `c48-49` both blank - the `I3,2X` depth-slice/fixed form. The three
      digits at c45-47 are whole kilometres: ` 50  ` is 50 km. Reading it as
      F5.2 would give 0.50 km, a hundredfold error (Traps 5).
    * otherwise - the `F5.2` depth-free form, hundredths of a km. The integer
      part is c45-47 and the decimals c48-49, so ` 2645` is 26.45 km.

    The F5.2 branch goes through the same fixed-point decoding as the minutes
    fields, because it meets Traps 9 too: h1919 holds 297 records whose final
    decimal column alone is blank (` 150 ` = 15.0 km). Taking such a field as
    four digits of whole kilometres instead yields depths up to 5400 km,
    deeper than the Earth; the fixed-point reading tops out at 540 km.
    """
    if raw[3:5] == "  ":
        whole = raw[:3].strip()
        if not whole:
            return None
        if not whole.isdigit():
            raise FieldError("depth", "45-49", raw, "not an integer number of km")
        return Decimal(whole)
    return _fixed_point(raw, field="depth", columns="45-49")


def parse_record(line: str) -> None:
    """Decode one 96-byte hypocenter record."""
    if len(line) != RECORD_LENGTH:
        raise RecordLengthError(len(line))
    return None
