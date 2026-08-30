"""Verify the batching claim instead of restating it.

`ParquetEventWriter` claims to flush a row group every `batch_size` events and
to hold no more than that in memory. Both halves are checked against something
external to the writer: the row-group structure is read out of the finished
file's own footer, and the buffer occupancy is observed while events are being
written, not inferred from the code.

The distinction matters because a writer that buffered the whole year and wrote
it as one row group at close would pass every round-trip and record-count test
in this suite. Only the footer says which of the two actually happened.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq

from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from tests.infrastructure.events import SampleEvent

JST = timezone(timedelta(hours=9), "JST")


def event(index: int) -> SampleEvent:
    return SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST) + timedelta(seconds=index),
        latitude_deg=35.0 + index / 100_000,
        longitude_deg=140.0 + index / 100_000,
        depth_km=10.0,
        magnitude1=1.0,
    )


def events(count: int) -> Iterator[SampleEvent]:
    for index in range(count):
        yield event(index)


def row_group_sizes(path: Path) -> list[int]:
    """Rows in each row group, read from the finished file's footer."""
    metadata = pq.ParquetFile(path).metadata
    return [
        metadata.row_group(index).num_rows for index in range(metadata.num_row_groups)
    ]


def test_an_exact_multiple_of_the_batch_size_gives_equal_row_groups(
    tmp_path: Path,
) -> None:
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path, batch_size=100) as writer:
        writer.write_many(events(500))

    assert row_group_sizes(path) == [100, 100, 100, 100, 100]


def test_a_remainder_becomes_a_final_short_row_group(tmp_path: Path) -> None:
    """The tail must be flushed by `close`, not dropped."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path, batch_size=100) as writer:
        writer.write_many(events(250))

    assert row_group_sizes(path) == [100, 100, 50]
    assert sum(row_group_sizes(path)) == 250


def test_fewer_events_than_one_batch_still_produce_one_row_group(
    tmp_path: Path,
) -> None:
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path, batch_size=100) as writer:
        writer.write_many(events(7))

    assert row_group_sizes(path) == [7]


def test_writing_no_events_produces_a_valid_empty_file(tmp_path: Path) -> None:
    """An empty year is a real answer and must not be an unreadable file.

    Distinct from an unavailable year, which `CatalogYearUnavailableError`
    reports upstream. The schema is still written, so a reader gets an empty
    table with the right columns rather than a parse failure.
    """
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path, batch_size=100):
        pass

    table = pq.read_table(path)
    assert table.num_rows == 0
    assert len(table.schema) == 25


def test_the_batch_size_bounds_what_is_held_in_memory(tmp_path: Path) -> None:
    """Observed while writing: the buffer never exceeds one batch.

    This is the claim that matters for a full year. A writer accumulating
    everything until close would show a buffer growing to 500 here.
    """
    path = tmp_path / "out.parquet"
    observed: list[int] = []
    with ParquetEventWriter(path, batch_size=100) as writer:
        for index in range(500):
            writer.write(event(index))
            observed.append(writer.rows_buffered)

    assert max(observed) < 100, f"buffer reached {max(observed)} rows"
    assert observed[:3] == [1, 2, 3]
    # Every 100th write flushes, so the buffer returns to empty there.
    assert observed[99] == 0
    assert observed[199] == 0
    assert observed[100] == 1


def test_row_groups_are_flushed_before_close_not_at_close(tmp_path: Path) -> None:
    """The staging file grows during the run, so bytes really are leaving memory.

    Reading the row-group count from the *finished* file cannot distinguish a
    writer that flushed as it went from one that wrote every group at close.
    The staging file's size during the run can.
    """
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path, batch_size=100) as writer:
        writer.write_many(events(100))
        after_first_group = _staging_size(tmp_path)
        writer.write_many(events(400))
        after_five_groups = _staging_size(tmp_path)

    assert after_first_group > 0, "nothing had been written to disk after 100 events"
    assert after_five_groups > after_first_group, (
        "the staging file did not grow between the first row group and the "
        "fifth, so the writer is buffering rather than streaming"
    )


def _staging_size(directory: Path) -> int:
    """Size of the in-progress staging file, which has not been published yet."""
    (staging,) = [path for path in directory.iterdir() if path.suffix == ".partial"]
    return staging.stat().st_size


def test_the_default_batch_size_puts_a_full_year_in_several_row_groups() -> None:
    """A single row group for 257,020 events would defeat the point.

    Not a file test — this pins the constant, so a later change to it is a
    deliberate edit here rather than a silent regression in write behaviour.
    """
    from jmacat.infrastructure.parquet_event_writer import _DEFAULT_BATCH_SIZE

    full_year = 257_020  # h2023, per docs/jma-hypocenter-format.md
    groups = -(-full_year // _DEFAULT_BATCH_SIZE)
    assert 2 <= groups <= 50, f"a full year would be {groups} row groups"
