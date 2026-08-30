"""`EventWriter` writing events as Parquet, using pyarrow.

Design notes
------------

**Row groups, and why the batch size is what it is.** Events accumulate in
column-oriented Python lists until `batch_size` of them have arrived, at which
point one `pa.RecordBatch` is built and handed to `pq.ParquetWriter.write_table`
— which emits it as a **row group** and lets the buffers go. Peak memory is
therefore a function of `batch_size` alone, not of how many events pass through:
a full year of 257,020 events costs the same as a thousand.

`_DEFAULT_BATCH_SIZE` is 50,000, which puts a full year in six row groups. The
tension is that a row group is Parquet's unit of both compression and predicate
push-down: too small and the per-group footer metadata and the loss of
compression context dominate (a 1,000-row group buys nothing and costs a
statistics block per column per group); too large and the writer holds the whole
thing in memory, which is the problem being solved. Parquet's own guidance puts
the useful range in the hundreds of thousands of rows for wide tables; this
table is 25 narrow columns, so the row *count* can sit at the low end of that
and still produce groups worth reading selectively. 50,000 rows across these
columns is a few megabytes of buffered Python objects, which is bounded and
small, and six groups over a year is enough granularity for a reader filtering
by time to skip most of the file.

The claim is verified rather than asserted: `test_row_groups.py` writes a
known number of events and reads `num_row_groups` and each group's row count
back out of the finished file's metadata.

**Atomic publication.** As with CSV, the file is staged next to the destination
and renamed into place only when `close` succeeds. This matters more for Parquet
than for CSV, because Parquet's footer is written *at close*: a file whose
footer was written after a partial run is not corrupt, it is a valid Parquet
file that reads as a complete, short catalog. Nothing downstream would flag it.
So `__exit__` on the error path closes the underlying writer to release the
handle and then deletes the staging file without ever renaming it.

**Nulls.** Every optional column is a nullable Arrow field and `None` is passed
straight through to Arrow, which stores it in the definition levels rather than
as a sentinel value. A missing depth reads back as `None`, never `0.0`
(*Traps* 6). Unlike CSV, Parquet distinguishes a null string from an empty
string, and this writer preserves that distinction.

**Time zone.** `origin_time_utc` is `timestamp[ms, tz=UTC]` and
`origin_time_jst` is `timestamp[ms, tz=+09:00]`. Arrow stores both as the same
UTC-epoch integer and carries the zone in the field's type, so the two columns
are the same instant and neither is naive. A reader that ignores the zone still
gets the correct instant from either. See `event_schema` for why both exist.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from jmacat.infrastructure.event_protocol import HypocenterEventLike
from jmacat.infrastructure.event_schema import COLUMNS
from jmacat.usecase.errors import EventWriterError

#: Japan Standard Time; see the same constant in `csv_event_writer`.
JST: Final = timezone(timedelta(hours=9), "JST")

_TIMESTAMP_ZONES: Final = {"origin_time_utc": UTC, "origin_time_jst": JST}

#: Events buffered before a row group is flushed. See the module docstring.
_DEFAULT_BATCH_SIZE: Final = 50_000

#: Maps a `Column.arrow_type_name` to the Arrow type it denotes.
#:
#: The schema table keeps type *names* so it stays importable without pyarrow
#: (the CSV writer needs the same table). This is the single place those names
#: become Arrow types, so a name the table invents fails here, loudly, at import
#: of this module rather than at row 200,000.
_ARROW_TYPES: Final[dict[str, Any]] = {
    "string": pa.string(),
    "double": pa.float64(),
    "int32": pa.int32(),
    "timestamp[ms, tz=UTC]": pa.timestamp("ms", tz="UTC"),
    "timestamp[ms, tz=+09:00]": pa.timestamp("ms", tz="+09:00"),
}


def arrow_schema() -> Any:
    """The output schema as Arrow sees it.

    Every field is nullable, including the ones the catalog never omits.
    Declaring a field non-nullable would buy a validation this layer is the
    wrong place for — a missing latitude is a *parser* failure, which issues
    #3/#4 own and must raise there — while making the writer reject an
    otherwise-recoverable row with a message about Arrow rather than about the
    record. Each column's real null policy is documented in `Column.null_meaning`.

    The unit of every column is attached as Arrow field metadata, so the units
    travel *inside* the file. A researcher who receives only the Parquet, with
    no README, can still read what `depth_km` is measured in — which is the
    whole point of writing them down.
    """
    return pa.schema(
        [
            pa.field(
                column.name,
                _arrow_type(column.arrow_type_name),
                nullable=True,
                metadata={
                    b"unit": column.unit.encode("utf-8"),
                    b"null_meaning": column.null_meaning.encode("utf-8"),
                },
            )
            for column in COLUMNS
        ]
    )


def _arrow_type(name: str) -> Any:
    try:
        return _ARROW_TYPES[name]
    except KeyError:  # pragma: no cover - a schema typo, caught at import
        raise EventWriterError(
            f"The schema names an Arrow type this writer cannot build: {name!r}."
        ) from None


class ParquetEventWriter:
    """Writes events as Parquet. Satisfies `EventWriter[HypocenterEventLike]`."""

    def __init__(
        self,
        path: Path | str,
        *,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        compression: str = "snappy",
    ) -> None:
        if batch_size < 1:
            raise EventWriterError(f"batch_size must be at least 1, got {batch_size}.")
        self._path = Path(path)
        self._batch_size = batch_size
        self._closed = False
        self._rows_written = 0
        self._row_groups_flushed = 0
        self._schema = arrow_schema()
        # One list per column, filled in lockstep. Column-oriented from the
        # start, because that is the shape pa.RecordBatch.from_arrays wants and
        # building rows first would mean transposing them at every flush.
        self._buffers: list[list[object]] = [[] for _ in COLUMNS]
        self._temporary_path: Path | None = None
        self._writer: Any | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Staged beside the destination so the final rename is a
            # same-filesystem, atomic operation.
            handle = tempfile.NamedTemporaryFile(
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".partial",
                delete=False,
            )
            handle.close()
            self._temporary_path = Path(handle.name)
            self._writer = pq.ParquetWriter(
                self._temporary_path, self._schema, compression=compression
            )
        except (OSError, pa.ArrowException) as error:
            if self._temporary_path is not None:
                _unlink(self._temporary_path)
                self._temporary_path = None
            self._closed = True
            raise EventWriterError(
                f"Could not open {self._path} for writing: {error}"
            ) from error

    @property
    def rows_written(self) -> int:
        """Events accepted so far, buffered ones included."""
        return self._rows_written

    @property
    def rows_buffered(self) -> int:
        """Events held in memory, not yet written as a row group."""
        return self._rows_written - self._row_groups_flushed * self._batch_size

    @property
    def row_groups_flushed(self) -> int:
        """Row groups written so far, excluding the final partial one."""
        return self._row_groups_flushed

    def write(self, event: HypocenterEventLike) -> None:
        self._ensure_open()
        self._buffer(event)
        self._flush_if_full()

    def write_many(self, events: Iterable[HypocenterEventLike]) -> None:
        self._ensure_open()
        # Iterated, never listed: a generator of a year's events must stream.
        for event in events:
            self._ensure_open()
            self._buffer(event)
            self._flush_if_full()

    def _buffer(self, event: HypocenterEventLike) -> None:
        for buffer, column in zip(self._buffers, COLUMNS, strict=True):
            value = column.extract(event)
            if column.name in _TIMESTAMP_ZONES:
                value = _as_aware(column.name, value)
            buffer.append(value)
        self._rows_written += 1

    def _flush_if_full(self) -> None:
        if len(self._buffers[0]) >= self._batch_size:
            self._flush()
            self._row_groups_flushed += 1

    def _flush(self, writer: Any | None = None) -> None:
        """Write the buffered events as one row group and release the buffers.

        `writer` is passed explicitly by `close`, which has already taken the
        handle off the instance so that a second `close` cannot use it twice.
        """
        if not self._buffers[0]:
            return
        if writer is None:
            writer = self._writer
        if writer is None:  # pragma: no cover - guarded by _ensure_open
            raise EventWriterError(f"{self._path} is not open for writing.")
        try:
            batch = pa.RecordBatch.from_arrays(
                [
                    pa.array(buffer, type=field.type)
                    for buffer, field in zip(self._buffers, self._schema, strict=True)
                ],
                schema=self._schema,
            )
            # One write_table call per batch is one row group; that is the
            # property test_row_groups.py reads back out of the footer.
            writer.write_table(pa.Table.from_batches([batch], schema=self._schema))
        except (OSError, pa.ArrowException) as error:
            raise EventWriterError(
                f"Could not write a row group to {self._path}: {error}"
            ) from error
        finally:
            # Cleared even on failure: the buffers are large and the writer is
            # about to be discarded, so holding them would only waste memory
            # while the exception unwinds.
            for buffer in self._buffers:
                buffer.clear()

    def close(self) -> None:
        """Flush the last row group, write the footer and publish. Idempotent."""
        if self._closed:
            return
        self._closed = True
        writer, self._writer = self._writer, None
        temporary, self._temporary_path = self._temporary_path, None
        if writer is None or temporary is None:  # pragma: no cover - never opened
            return
        try:
            self._flush(writer)
        except EventWriterError:
            _close_quietly(writer)
            _unlink(temporary)
            raise
        try:
            # This writes the footer: schema, row-group index, statistics.
            # Until it returns there is no readable Parquet file at all.
            writer.close()
        except (OSError, pa.ArrowException) as error:
            _unlink(temporary)
            raise EventWriterError(
                f"Could not finalise {self._path}: {error}"
            ) from error
        try:
            temporary.replace(self._path)
        except OSError as error:
            _unlink(temporary)
            raise EventWriterError(
                f"Could not publish {self._path}: {error}"
            ) from error

    def _discard(self) -> None:
        """Release the handle and delete the staging file without publishing."""
        self._closed = True
        writer, self._writer = self._writer, None
        temporary, self._temporary_path = self._temporary_path, None
        for buffer in self._buffers:
            buffer.clear()
        if writer is not None:
            _close_quietly(writer)
        if temporary is not None:
            _unlink(temporary)

    def _ensure_open(self) -> None:
        if self._closed:
            raise EventWriterError(
                f"Cannot write to {self._path}: the writer is closed."
            )

    def __enter__(self) -> ParquetEventWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Publish on success; discard the staging file on the error path.

        Returns `None`, so the body's exception propagates. The staging file is
        deleted rather than finalised: a Parquet file whose footer was written
        after a partial run is *valid*, and would read as a complete catalog
        that happens to be short. That is the silent wrong answer this project
        refuses to produce.
        """
        if exc_type is not None:
            self._discard()
            return
        self.close()


def _as_aware(column_name: str, value: object) -> datetime:
    """Check the origin time carries a zone, and move it into the column's zone."""
    if not isinstance(value, datetime):
        raise EventWriterError(
            f"origin_time must be a datetime, got {type(value).__name__}."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventWriterError(
            "origin_time must be timezone-aware. The JMA catalog is JST "
            "(UTC+9); a naive value would be stored with a time zone this "
            "writer had to guess. See docs/jma-hypocenter-format.md."
        )
    return value.astimezone(_TIMESTAMP_ZONES[column_name])


def _close_quietly(writer: Any) -> None:
    """Release the handle while unwinding; its own failure is not the story."""
    try:
        writer.close()
    except (OSError, pa.ArrowException):  # pragma: no cover - file is discarded
        pass


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - nothing useful to do while unwinding
        pass
