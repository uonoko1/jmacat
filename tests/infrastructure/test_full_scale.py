"""A full year through both writers, with the record count asserted.

`h2023` holds **257,020 records** (`docs/jma-hypocenter-format.md`, *Record
width is stable across eras*), so that is the count used here rather than a
round number. The events are synthetic — this is a writer test, not a parser
test — but the *scale* is the real one, because the requirement being checked
is that a year's worth of events can pass through without being held in memory.

Marked `slow` and deselected by default (`addopts` in `pyproject.toml`), so the
ordinary `uv run pytest` stays fast. CI runs the whole suite including these:

    uv run pytest -m slow          # these tests only
    uv run pytest -m ""            # everything, as CI does

Measured on the development machine (WSL2, Python 3.11, pyarrow 25.0.1):
Parquet 6.5 s, CSV 10.0 s, four tests 30 s in total. Most of that is
constructing 257,020 Python objects, not the writers: the same generator
consumed into a bare loop, writing nothing, costs 2.0 s.
"""

from __future__ import annotations

import resource
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from tests.infrastructure.events import SampleEvent

pytestmark = pytest.mark.slow

JST = timezone(timedelta(hours=9), "JST")

#: Records in h2023, from the format document's own byte-count table.
FULL_YEAR = 257_020

#: The 2023 proportion with no magnitude at all, so the run exercises nulls at
#: scale rather than only on a hand-picked row.
EVENTS_WITHOUT_MAGNITUDE = 9_973


def year_of_events(count: int = FULL_YEAR) -> Iterator[SampleEvent]:
    """A year's events as a generator, so nothing is ever materialised.

    Passing a generator is the point: a writer that listed its input would
    hold the whole year, and this test would then measure that instead.
    """
    start = datetime(2023, 1, 1, tzinfo=JST)
    for index in range(count):
        yield SampleEvent(
            record_type="J",
            origin_time=start + timedelta(seconds=index * 2),
            latitude_deg=30.0 + (index % 100_000) / 10_000,
            longitude_deg=130.0 + (index % 150_000) / 10_000,
            depth_km=None if index % 1_000 == 0 else 10.0 + (index % 500) / 10,
            magnitude1=(
                None if index < EVENTS_WITHOUT_MAGNITUDE else -0.6 + (index % 80) / 10
            ),
            magnitude1_type=None if index < EVENTS_WITHOUT_MAGNITUDE else "v",
            region_name="NEAR CHOSHI CITY",
            station_count=index % 40,
        )


def peak_memory_mib() -> float:
    """Peak resident set size of this process, in MiB.

    `ru_maxrss` is in kilobytes on Linux. It is a **high-water mark**, which is
    why the memory test below runs each case in its own subprocess: within one
    process the first case's peak would be attributed to the second, and the
    comparison would be meaningless.
    """
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


#: Writes a full year at a given batch size and prints the peak memory growth.
#: Run as a subprocess so each measurement gets a fresh high-water mark.
_MEASURE = """
import pathlib, resource, sys, tempfile
sys.path[:0] = ["src", "."]
from tests.infrastructure.test_full_scale import year_of_events
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter

def mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

directory = pathlib.Path(tempfile.mkdtemp())
before = mib()
with ParquetEventWriter(directory / "out.parquet", batch_size=int(sys.argv[1])) as w:
    w.write_many(year_of_events())
print(mib() - before)
"""


def peak_growth_writing_a_year(batch_size: int) -> float:
    """MiB of peak-memory growth from writing a full year at `batch_size`."""
    result = subprocess.run(
        [sys.executable, "-c", _MEASURE, str(batch_size)],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    return float(result.stdout.strip())


def test_a_full_year_writes_to_parquet_with_every_record_present(
    tmp_path: Path,
) -> None:
    path = tmp_path / "h2023.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write_many(year_of_events())

    metadata = pq.ParquetFile(path).metadata
    assert metadata.num_rows == FULL_YEAR
    # Six row groups at the default 50,000 batch size, the last one short.
    assert metadata.num_row_groups == 6
    sizes = [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)]
    assert sizes == [50_000, 50_000, 50_000, 50_000, 50_000, 7_020]
    assert sum(sizes) == FULL_YEAR


def test_a_full_year_writes_to_csv_with_every_record_present(tmp_path: Path) -> None:
    path = tmp_path / "h2023.csv"
    with CsvEventWriter(path) as writer:
        writer.write_many(year_of_events())

    with path.open(encoding="utf-8", newline="") as handle:
        lines = sum(1 for _ in handle)
    assert lines == FULL_YEAR + 1  # the header row


def test_a_full_year_keeps_its_nulls_at_scale(tmp_path: Path) -> None:
    """The null count survives 257,020 rows and six row groups.

    A per-row test cannot catch a null lost at a row-group boundary, or a
    column whose Arrow array quietly acquired a default on a later batch.
    """
    path = tmp_path / "h2023.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write_many(year_of_events())

    table = pq.read_table(path, columns=["magnitude1", "depth_km"])
    assert table.column("magnitude1").null_count == EVENTS_WITHOUT_MAGNITUDE
    # depth is null on every thousandth event: indices 0, 1000, ... < 257,020.
    assert table.column("depth_km").null_count == 258


def test_batching_is_what_keeps_a_full_year_out_of_memory() -> None:
    """Streaming a year costs materially less memory than buffering it.

    Stated as a *comparison* rather than an absolute threshold, and that is the
    point. An absolute bound — "peak growth under 200 MiB" — passes whether or
    not the writer batches, because a buffered year on this machine costs about
    206 MiB and lands on either side of any round number depending on the
    interpreter, the pyarrow build and what else the process has touched. It
    would be a test that never fails, which proves nothing.

    Running the writer at a batch size larger than the year turns batching off
    through the public API, so the two arms differ in exactly one thing. On the
    development machine: 71 MiB batched against 206 MiB buffered.

    Both arms run in their own subprocess because `ru_maxrss` is a high-water
    mark; measuring them in one process would report the larger for both.
    """
    batched = peak_growth_writing_a_year(50_000)
    buffered = peak_growth_writing_a_year(FULL_YEAR + 1)

    assert batched < buffered / 2, (
        f"batched writing peaked at {batched:.0f} MiB against {buffered:.0f} MiB "
        "when buffering the year, which is not the separation batching should give"
    )
