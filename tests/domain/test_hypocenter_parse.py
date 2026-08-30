"""Parsing a 96-byte JMA hypocenter record into a typed value object.

Every expectation here traces to `docs/jma-hypocenter-format.md` or to a
verbatim line from the published catalog, cited per test. No expected value in
this file was invented.
"""

from __future__ import annotations

import pytest

from jmacat.domain.hypocenter import FieldError, RecordLengthError, parse_record


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
