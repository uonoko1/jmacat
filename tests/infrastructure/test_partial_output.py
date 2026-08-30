"""A run that fails mid-year must not leave a file that reads as complete.

This is the failure mode the port's context-manager shape exists to prevent,
and it is the one that cannot be caught by reading the output: a CSV truncated
at 200,000 of 257,000 rows is a perfectly valid CSV, and a Parquet file whose
footer was written after 200,000 rows is a perfectly valid Parquet file. Nothing
downstream would report an error; the catalog would simply be short, and a
researcher would publish a rate that is 22 per cent too low.

Both writers therefore stage to a temporary file and publish by rename, so the
destination path holds a complete catalog or nothing at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from tests.infrastructure.events import RecordType, SampleEvent

if TYPE_CHECKING:
    from jmacat.infrastructure.event_protocol import HypocenterEventLike

JST = timezone(timedelta(hours=9), "JST")


class ConversionFailedError(Exception):
    """A failure from *upstream* of the writer, as a real run would raise."""


def event(index: int) -> SampleEvent:
    return SampleEvent(
        record_type=RecordType.JMA,
        origin_time=datetime(2023, 1, 1, tzinfo=JST) + timedelta(seconds=index),
        latitude=Decimal(35) + Decimal(index) / 10_000,
        longitude=Decimal(140) + Decimal(index) / 10_000,
        depth_km=Decimal("10.0"),
        magnitude=Decimal("1.0"),
    )


def events_then_failure(count: int) -> Iterator[HypocenterEventLike]:
    """Yields `count` events and then raises, as a bad record mid-year would."""
    for index in range(count):
        yield event(index)
    raise ConversionFailedError("record 500 could not be converted")


WRITERS = [
    pytest.param(CsvEventWriter, "out.csv", id="csv"),
    pytest.param(ParquetEventWriter, "out.parquet", id="parquet"),
]


@pytest.mark.parametrize(("writer_class", "filename"), WRITERS)
def test_a_failure_inside_the_with_block_leaves_no_file_at_all(
    tmp_path: Path,
    writer_class: type[CsvEventWriter] | type[ParquetEventWriter],
    filename: str,
) -> None:
    """The destination must not exist, not merely be short."""
    path = tmp_path / filename
    with pytest.raises(ConversionFailedError):
        with writer_class(path) as writer:
            writer.write_many(events_then_failure(500))

    assert not path.exists(), (
        f"{path.name} was published despite the run failing; a short catalog "
        "that reads as complete is the failure this test exists to prevent"
    )


@pytest.mark.parametrize(("writer_class", "filename"), WRITERS)
def test_a_failure_leaves_no_partial_file_behind_either(
    tmp_path: Path,
    writer_class: type[CsvEventWriter] | type[ParquetEventWriter],
    filename: str,
) -> None:
    """Not even the staging file survives — an aborted run leaves no litter."""
    path = tmp_path / filename
    with pytest.raises(ConversionFailedError):
        with writer_class(path) as writer:
            writer.write_many(events_then_failure(500))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("writer_class", "filename"), WRITERS)
def test_a_failure_does_not_overwrite_an_existing_complete_file(
    tmp_path: Path,
    writer_class: type[CsvEventWriter] | type[ParquetEventWriter],
    filename: str,
) -> None:
    """Re-running a conversion that fails must not destroy the good output.

    The rename only happens on success, so yesterday's complete catalog is
    still there after today's run failed. Publishing in place would have
    truncated it at the first write.
    """
    path = tmp_path / filename
    with writer_class(path) as writer:
        writer.write_many(event(index) for index in range(10))
    good = path.read_bytes()

    with pytest.raises(ConversionFailedError):
        with writer_class(path) as writer:
            writer.write_many(events_then_failure(500))

    assert path.read_bytes() == good


@pytest.mark.parametrize(("writer_class", "filename"), WRITERS)
def test_a_successful_run_does_publish_the_file(
    tmp_path: Path,
    writer_class: type[CsvEventWriter] | type[ParquetEventWriter],
    filename: str,
) -> None:
    """The guard above would pass vacuously if nothing were ever published."""
    path = tmp_path / filename
    with writer_class(path) as writer:
        writer.write_many(event(index) for index in range(10))

    assert path.exists()
    assert path.stat().st_size > 0
    assert list(tmp_path.iterdir()) == [path]
