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


def parse_record(line: str) -> None:
    """Decode one 96-byte hypocenter record."""
    if len(line) != RECORD_LENGTH:
        raise RecordLengthError(len(line))
    return None
