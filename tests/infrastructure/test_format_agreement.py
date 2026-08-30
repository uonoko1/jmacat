"""The two writers must never disagree about the same event.

Both adapters read one schema, so their *columns* cannot drift. Their *values*
could, and did: the schema handed each writer whatever the domain held, and the
two formats then serialised it independently. Review found the consequence —
`Decimal("142.93183333333333")` reached Parquet as the float64
142.93183333333334 and CSV as the text 142.93183333333333, so the two files
disagreed about where an epicentre was, with no error from either.

The rule that fixes it is that every conversion the domain's types need happens
**in `event_schema`, once**, before either writer sees the value. This file
pins that rule from the outside, by writing one event both ways and comparing
the files.

It also pins the other half: a type the schema has *not* converted must fail in
both formats. Arrow rejects it already; `csv.writer` would have called `str()`
on it and written something plausible. That was the one place the two formats
disagreed about whether a thing was an error at all.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.event_schema import COLUMNS, column_names
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from jmacat.usecase.errors import EventWriterError
from tests.infrastructure.events import RecordType, SampleEvent

JST = timezone(timedelta(hours=9), "JST")

#: Example B of the format document: 41 deg 10.23 min N, 142 deg 55.91 min E.
#:
#: This longitude is the value the divergence was found on. In exact decimal it
#: is 142.931833333333333... recurring, which no binary double can hold, so the
#: two formats have to agree on *which* double before they can agree at all.
LONGITUDE = 142 + Decimal("55.91") / 60
LATITUDE = 41 + Decimal("10.23") / 60


def example_b() -> SampleEvent:
    return SampleEvent(
        record_type=RecordType.JMA,
        origin_time=datetime(2023, 1, 1, 0, 10, 22, 710_000, tzinfo=JST),
        latitude=LATITUDE,
        longitude=LONGITUDE,
        depth_km=Decimal("26.45"),
        magnitude=Decimal("-0.6"),
        magnitude_type="v",
        district=3,
        region_number=110,
        region_name="NEAR CHOSHI CITY",
        station_count=9,
    )


def write_both(
    event: SampleEvent, directory: Path
) -> tuple[dict[str, str], dict[str, object]]:
    """One event through both writers; the CSV row and the Parquet row."""
    csv_path = directory / "out.csv"
    parquet_path = directory / "out.parquet"
    with CsvEventWriter(csv_path) as writer:
        writer.write(event)
    with ParquetEventWriter(parquet_path) as writer:
        writer.write(event)
    with csv_path.open(encoding="utf-8", newline="") as handle:
        (csv_row,) = list(csv.DictReader(handle))
    (parquet_row,) = pq.read_table(parquet_path).to_pylist()
    return csv_row, parquet_row


def test_a_decimal_coordinate_reaches_both_formats_as_the_same_value(
    tmp_path: Path,
) -> None:
    """The regression this file exists for, on the value that exposed it.

    `float(Decimal)` is correctly rounded to the nearest double, and CSV writes
    that double's `repr` — the shortest text that reads back as the identical
    double. So the CSV text parses to exactly the float64 Parquet stored, and
    the comparison is an equality rather than a tolerance.
    """
    csv_row, parquet_row = write_both(example_b(), tmp_path)

    assert float(csv_row["longitude_deg"]) == parquet_row["longitude_deg"]
    assert float(csv_row["latitude_deg"]) == parquet_row["latitude_deg"]
    # And both are the double the schema's narrowing produces, not some other
    # rounding either writer invented on its own.
    assert parquet_row["longitude_deg"] == float(LONGITUDE)
    assert csv_row["longitude_deg"] == repr(float(LONGITUDE))


def test_the_decimal_that_first_showed_the_two_formats_disagreeing(
    tmp_path: Path,
) -> None:
    """Named separately because it is the exact reproduction from review.

    Before the fix: Parquet float64 142.93183333333334 against CSV text
    142.93183333333333. The two files put the epicentre in different places and
    neither raised.
    """
    exact = Decimal("142.93183333333333")
    csv_row, parquet_row = write_both(replace(example_b(), longitude=exact), tmp_path)

    assert csv_row["longitude_deg"] == "142.93183333333334"
    assert parquet_row["longitude_deg"] == 142.93183333333334
    assert float(csv_row["longitude_deg"]) == parquet_row["longitude_deg"]


def test_every_column_agrees_between_the_two_formats(tmp_path: Path) -> None:
    """Not only the coordinates: each column, compared after parsing.

    A column-by-column sweep, so a future column that needs a conversion cannot
    be added to only one of the two paths.
    """
    csv_row, parquet_row = write_both(example_b(), tmp_path)
    by_name = {column.name: column for column in COLUMNS}

    for name in column_names():
        text = csv_row[name]
        stored = parquet_row[name]
        arrow_type = by_name[name].arrow_type_name
        if stored is None:
            # A null in Parquet must be an empty field in CSV, and nothing else.
            # This is the *Traps* 6 guarantee checked across both formats at once.
            assert text == "", name
            continue
        if arrow_type == "double":
            assert float(text) == stored, name
        elif arrow_type == "int32":
            assert int(text) == stored, name
        elif arrow_type == "bool":
            assert (text == "True") == stored, name
        elif arrow_type.startswith("timestamp"):
            assert datetime.fromisoformat(text.replace("Z", "+00:00")) == stored, name
        else:
            assert text == (stored or ""), name


def test_a_record_type_enum_is_written_as_its_code_not_its_repr(
    tmp_path: Path,
) -> None:
    """`str(RecordType.JMA)` is the text `RecordType.JMA`, and CSV accepted it.

    This was the silent one. Parquet raised ("Expected bytes, got a
    'RecordType' object"), but `csv.writer` calls `str()`, which never fails, so
    the CSV column filled up with the enum's `repr` and nothing anywhere
    complained. The schema now reads `.value`, which is the published code.
    """
    csv_row, parquet_row = write_both(example_b(), tmp_path)

    assert csv_row["record_type"] == "J"
    assert parquet_row["record_type"] == "J"
    assert "RecordType" not in csv_row["record_type"]


@dataclass(frozen=True)
class _Unrenderable:
    """A type no writer has a rule for. Its `str()` is deliberately plausible."""

    def __str__(self) -> str:
        return "35.0"


def _event_with_an_unrenderable_region_name() -> SampleEvent:
    """An event whose `region_name` is a type the schema never converts.

    `region_name` is a string column, so a bare `str()` fallback would put
    "35.0" in it and no format check anywhere would notice.
    """
    return replace(example_b(), region_name=_Unrenderable())  # type: ignore[arg-type]


def test_csv_refuses_a_type_it_has_no_rule_for(tmp_path: Path) -> None:
    """The fix for the divergence: CSV raises rather than falling back to str().

    Without this, the object above would have been written as the text "35.0" —
    a valid-looking value in a string column, produced by a `str()` nobody
    asked for. CONTRIBUTING's "prefer failing loudly over returning a value
    that might be wrong" makes that an exception.
    """
    with pytest.raises(EventWriterError) as caught:
        with CsvEventWriter(tmp_path / "out.csv") as writer:
            writer.write(_event_with_an_unrenderable_region_name())

    message = str(caught.value)
    assert "region_name" in message, "the error must name the column"
    assert "_Unrenderable" in message, "the error must name the offending type"
    # And nothing was published: the staging file was discarded.
    assert not (tmp_path / "out.csv").exists()


def test_parquet_refuses_the_same_type(tmp_path: Path) -> None:
    """Arrow already rejected it; asserted so the two stay symmetrical.

    The point of the pair is that neither format is now the lenient one. Before
    the fix this test passed and its CSV twin did not exist, which is exactly
    how a wrong value ships in one format only.
    """
    with pytest.raises(EventWriterError):
        with ParquetEventWriter(tmp_path / "out.parquet") as writer:
            writer.write(_event_with_an_unrenderable_region_name())

    assert not (tmp_path / "out.parquet").exists()


def test_a_bare_decimal_reaching_a_writer_would_be_refused(tmp_path: Path) -> None:
    """The narrowing is not optional, and skipping it is not silent.

    `Decimal` is deliberately *not* in the CSV writer's renderable types. If a
    future column forgets `_as_double`, the value does not quietly serialise at
    a precision Parquet does not share — it raises here, naming the column.
    """
    from jmacat.infrastructure.csv_event_writer import _render

    with pytest.raises(EventWriterError) as caught:
        _render("depth_km", Decimal("26.45"))
    assert "depth_km" in str(caught.value)
    assert "Decimal" in str(caught.value)
