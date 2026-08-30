"""Proof that a year is streamed, not loaded into memory.

The port's central performance promise is that a ~25 MB expanded year is read
at constant memory. That is easy to assert and easy to break: `read().split()`
or a `list(...)` anywhere in the read path satisfies every other test in the
suite while quietly holding the whole year.

So it is *measured* rather than asserted, with `tracemalloc`, against an
archive built to be far larger than any plausible buffer. The archive is
generated in a temporary directory at test time, not committed — synthetic
bytes are the right choice here because this test is about memory, not about
record semantics, and the real 25 MB file must not enter the repository.

Measured against the real `h2023.zip` during development: 257,020 lines,
24,673,920 bytes of text traversed, peak traced memory 146,815 bytes — 0.6% of
the 24,930,940-byte expanded file.
"""

from __future__ import annotations

import tracemalloc
import zipfile
from pathlib import Path

from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource

#: Each JMA record is 96 bytes (docs/jma-hypocenter-format.md); the +1 is the
#: terminator. 200,000 records is ~19 MB expanded, the same order as a real
#: year, and two orders of magnitude above the 64 KiB read buffer — so a peak
#: anywhere near the file size is unmistakable.
RECORD_BYTES = 96
RECORD_COUNT = 200_000
EXPANDED_BYTES = RECORD_COUNT * (RECORD_BYTES + 1)

#: The ceiling peak memory must stay under. Generous next to the ~19 MB file
#: and still an order of magnitude below it, so the test states "constant
#: memory" without being brittle about allocator noise.
PEAK_CEILING_BYTES = 2 * 1024 * 1024


def build_large_archive(path: Path) -> None:
    """A one-member ZIP of `RECORD_COUNT` fixed-width lines, written streaming."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("h1919", "w") as member:
            for index in range(RECORD_COUNT):
                filler = str(index % 10) * (RECORD_BYTES - 1)
                member.write(b"J" + filler.encode("ascii") + b"\n")


def test_streaming_a_large_year_stays_far_below_its_expanded_size(
    tmp_path: Path,
) -> None:
    """Peak memory must not scale with the archive.

    Reading every line of a ~19 MB year is expected to peak in the tens of
    kilobytes — a read buffer plus one 96-byte line — not in the megabytes.
    """
    archive = tmp_path / "h1919.zip"
    build_large_archive(archive)
    source = JmaCatalogSource(cache_dir=tmp_path)

    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    count = 0
    for line in source.record_lines(1919):
        # Consumed and dropped, as a real pipeline does. Retaining the lines
        # would measure the caller's memory, not the adapter's.
        count += len(line)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert count == RECORD_COUNT * RECORD_BYTES  # every line really was read
    assert peak - baseline < PEAK_CEILING_BYTES, (
        f"peak {peak - baseline:,} bytes while streaming an "
        f"{EXPANDED_BYTES:,}-byte year; the read path is not streaming"
    )


def test_the_measurement_would_catch_a_non_streaming_implementation(
    tmp_path: Path,
) -> None:
    """A guard that cannot fail proves nothing.

    Materialising the same archive the way a naive implementation would must
    exceed the ceiling the streaming test passes under — otherwise that test
    is measuring nothing and would keep passing after a regression.
    """
    archive = tmp_path / "h1919.zip"
    build_large_archive(archive)

    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    with zipfile.ZipFile(archive) as opened:
        with opened.open("h1919") as member:
            eager = member.read().decode("ascii").splitlines()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(eager) == RECORD_COUNT
    assert peak - baseline > PEAK_CEILING_BYTES
