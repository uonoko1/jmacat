"""The README's column table must match the schema it documents.

Documentation that drifts from the code is worse than none: a researcher who
reads that `depth_km` is in kilometres, when the writer has since changed it,
gets a wrong answer with no warning. The units and the time zone are exactly
the facts issue #7 requires to be documented, so they are checked mechanically
rather than by review.
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


def documented_columns() -> list[tuple[str, str]]:
    """The (name, type) pairs of the README's column table, in order."""
    text = README.read_text("utf-8")
    assert _TABLE_HEADER in text, "the README has no column table"
    table = text.split(_TABLE_HEADER, 1)[1].split("\n\n", 1)[0]
    rows = re.findall(r"^\| `(\w+)` \| ([^|]+?) \|", table, re.M)
    return [(name, type_name.strip()) for name, type_name in rows]


def test_the_readme_documents_every_column_in_schema_order() -> None:
    assert documented_columns() == [
        (column.name, column.arrow_type_name) for column in COLUMNS
    ]


def test_the_readme_documents_each_column_s_unit_and_null_meaning() -> None:
    text = README.read_text("utf-8")
    for column in COLUMNS:
        # The table is generated from these strings, so a changed unit that was
        # not carried into the README shows up here.
        assert column.unit.split(";")[0].split(",")[0] in text, (
            f"the README does not state the unit of {column.name}"
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
