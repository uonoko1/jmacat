"""The README's column table must match the schema it documents.

Documentation that drifts from the code is worse than none: a researcher who
reads that `depth_km` is in kilometres, when the writer has since changed it,
gets a wrong answer with no warning. The units and the time zone are exactly
the facts issue #7 requires to be documented, so they are checked mechanically
rather than by review.

Why the unit check parses the table
-----------------------------------

The first version of the unit check asked whether a *prefix* of each column's
unit appeared anywhere in the README, and it could not fail. Review mutated
`depth_km`'s unit from "kilometres below the surface" to "metres below the
surface" — a hundredfold error, the exact class this file's own docstring cites
*Traps* 5 and 9 about — and all four tests passed. Two independent reasons:

* it was a **substring** test, and "metres below the surface" is a substring of
  "kilometres below the surface", so the mutant matched the unmutated README;
* the probe was truncated at the first `;` or `,` and searched against the
  **whole file**, so `magnitude_type_2`, `record_type` and the rest reduced to
  the probe "code", which occurs throughout the prose and could never fail.

The check below therefore parses each row of the table and compares that row's
own unit cell to that column's `unit` for **equality**. A one-word change to
either side now fails, naming the column.
"""

from __future__ import annotations

import re
from pathlib import Path

from jmacat.infrastructure.event_schema import COLUMNS

README = Path(__file__).resolve().parents[2] / "README.md"


#: The header of the column table, which is what identifies it. The README has
#: a second table (the two timestamp columns), so matching bare table rows
#: anywhere in the file would pick that one up too.
_TABLE_HEADER = "| Column | Type | Unit | Null means |"

#: One documented column: name, type, unit, null meaning. Anchored on the four
#: cells of a row so a row with a missing cell fails to parse rather than
#: silently shifting the unit into the null-meaning position.
_ROW = re.compile(r"^\| `(\w+)` \| ([^|]*) \| ([^|]*) \| ([^|]*) \|$", re.M)


def documented_rows() -> list[tuple[str, str, str, str]]:
    """Every row of the README's column table, in order, cell by cell."""
    text = README.read_text("utf-8")
    assert _TABLE_HEADER in text, "the README has no column table"
    table = text.split(_TABLE_HEADER, 1)[1].split("\n\n", 1)[0]
    return [
        (name.strip(), type_name.strip(), unit.strip(), meaning.strip())
        for name, type_name, unit, meaning in _ROW.findall(table)
    ]


def test_the_readme_documents_every_column_in_schema_order() -> None:
    assert [(name, type_name) for name, type_name, _, _ in documented_rows()] == [
        (column.name, column.arrow_type_name) for column in COLUMNS
    ]


def test_the_readme_states_each_column_s_unit_exactly() -> None:
    """Equality, per row.

    A substring test here could not fail; see the module docstring.
    """
    documented = {name: unit for name, _, unit, _ in documented_rows()}
    for column in COLUMNS:
        assert documented.get(column.name) == column.unit, (
            f"the README's unit for {column.name} is "
            f"{documented.get(column.name)!r}, but the schema says {column.unit!r}"
        )


def test_the_readme_states_each_column_s_null_meaning_exactly() -> None:
    """The same equality check for what a null means, for the same reason."""
    documented = {name: meaning for name, _, _, meaning in documented_rows()}
    for column in COLUMNS:
        assert documented.get(column.name) == column.null_meaning, (
            f"the README's null meaning for {column.name} is "
            f"{documented.get(column.name)!r}, but the schema says "
            f"{column.null_meaning!r}"
        )


def test_the_readme_states_the_time_zone_decision() -> None:
    """The requirement is that a joiner cannot be left guessing."""
    text = README.read_text("utf-8")
    assert "UTC+9" in text
    assert "origin_time_utc" in text
    assert "origin_time_jst" in text
    assert "+09:00" in text


def test_the_readme_states_that_a_missing_value_is_not_zero() -> None:
    assert "never zero" in README.read_text("utf-8").lower()


def test_the_readme_says_which_record_fields_are_not_yet_decoded() -> None:
    """An absent column must be explained, or it reads as absent data.

    A researcher who does not find `maximum_intensity` needs to know the parser
    does not decode it yet, rather than concluding the catalog does not carry
    it. The note also records that their return is additive.
    """
    text = README.read_text("utf-8")
    for field in ("maximum_intensity", "tsunami_class", "determination_flag"):
        assert field in text, f"the README does not mention the undecoded {field}"
    assert "additive" in text
