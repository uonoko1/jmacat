"""`EventWriter` writing events as CSV, using the standard library `csv` module.

Design notes
------------

**Atomic publication.** Events are written to a temporary file beside the
destination and the destination only appears, by `Path.replace`, when `close`
succeeds. A conversion that fails at record 200,000 of 257,000 therefore leaves
*no file at the destination path* rather than a 200,000-row file that reads as
a complete, short catalog — which is a valid CSV that no tool would flag and no
researcher would question. `Path.replace` is `os.replace`, atomic on POSIX and
both paths are on the same filesystem, which they are by construction (the
temporary file is created in the destination's own directory). This is the
error-path behaviour the port's context-manager shape exists to guarantee.

**Null representation, and its one documented limitation.** A null is an
*empty, unquoted* field. That keeps the distinction the requirement is actually
about: a missing depth or magnitude reads back as an empty field and never as
`0.0`, which is a real and scientifically different measurement (*Traps* 6).

What CSV cannot also express is a null against a zero-length *string*, because
it has one empty field and two things to say with it. `csv.QUOTE_NOTNULL` would
render the two differently, but it needs Python 3.12 and the project baseline is
3.11. So this writer normalises an empty string to a null, and states it here
rather than leaving a reader to discover it. That is lossless for this catalog:
no field of the 96-byte record can hold a zero-length string meaning anything
other than "blank" — a blank 24-byte region name *is* an absent name. Parquet
keeps the two apart, so a run that needs the distinction has a format that
offers it.

**Float formatting.** Floats are formatted with `repr`, not `str(round(...))`
and not an `f"{x:.6f}"` format. `repr` of a Python float is by definition the
shortest decimal string that reads back as the *identical* double, so a
coordinate survives the text round trip bit for bit. A fixed six-decimal format
looks tidier and quietly truncates: 142 deg 55.91 min is 142.93183333333333
degrees, and `%.6f` writes 142.931833, which is a different position — about
4 cm here, but the same class of silent loss that *Traps* 1 is about, and there
is no reason to accept any of it.

Because `event_schema` has already narrowed the domain's `Decimal` to the
`double` the column declares, `repr` here is the `repr` of the *same* double
Parquet stores. The two formats therefore agree on a coordinate exactly, and
`test_format_agreement.py` pins that against the value that first showed them
disagreeing.

**Unknown types are refused, not stringified.** `csv.writer` would call `str()`
on anything, and `str()` never raises: a `Decimal` would print at a precision
the Parquet column does not share, and an enum member would print as
`RecordType.JMA`. `_render` therefore accepts a closed list of types and raises
`EventWriterError` for everything else, so a type nobody wrote a rule for fails
in CSV exactly as loudly as Arrow already fails it in Parquet.

**Time zone.** Both timestamp columns are ISO 8601 with an explicit offset:
`...Z` for UTC and `...+09:00` for JST. No naive text is ever written. See
`event_schema` for why both columns exist.
"""

from __future__ import annotations

import csv
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Final

from jmacat.infrastructure.event_protocol import HypocenterEventLike
from jmacat.infrastructure.event_schema import COLUMNS, column_names
from jmacat.usecase.errors import EventWriterError

#: Japan Standard Time. A fixed offset, not a zoneinfo lookup: Japan has
#: observed no daylight saving since 1951, and every record in the catalog is
#: UTC+9 with no exception. A named zone would introduce a tzdata dependency
#: and a historical DST rule that would silently shift 1948-1951 records.
JST: Final = timezone(timedelta(hours=9), "JST")

#: The two timestamp columns and the zone each is rendered in.
_TIMESTAMP_ZONES: Final = {"origin_time_utc": UTC, "origin_time_jst": JST}


class CsvEventWriter:
    """Writes events as CSV. Satisfies `EventWriter[HypocenterEventLike]`.

    The `csv` module already buffers through the underlying text file object,
    so rows are handed over one at a time and the operating system decides when
    to flush. No row is ever held in a list, so memory is flat regardless of how
    many events pass through — see `test_full_scale.py`.
    """

    def __init__(self, path: Path | str, *, encoding: str = "utf-8") -> None:
        self._path = Path(path)
        self._closed = False
        self._rows_written = 0
        self._temporary_path: Path | None = None
        self._handle: IO[str] | None = None
        try:
            # `delete=False` because the file is handed to os.replace, not
            # discarded; the error paths below and `close` own its removal.
            # Created in the destination's own directory so the final replace
            # is a same-filesystem rename, and therefore atomic.
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding=encoding,
                newline="",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".partial",
                delete=False,
            )
        except OSError as error:
            raise EventWriterError(
                f"Could not open a temporary file beside {self._path}: {error}"
            ) from error
        self._handle = handle
        self._temporary_path = Path(handle.name)
        self._writer = csv.writer(handle, lineterminator="\n")
        try:
            self._writer.writerow(column_names())
        except OSError as error:
            self._discard()
            raise EventWriterError(
                f"Could not write the CSV header to {self._path}: {error}"
            ) from error

    @property
    def rows_written(self) -> int:
        """Data rows handed to the CSV writer so far, excluding the header."""
        return self._rows_written

    def write(self, event: HypocenterEventLike) -> None:
        self._ensure_open()
        self._write_row(event)

    def write_many(self, events: Iterable[HypocenterEventLike]) -> None:
        self._ensure_open()
        # Iterated, never listed: the port promises lazy consumption, and a
        # full year must not be materialised to be written.
        for event in events:
            self._ensure_open()
            self._write_row(event)

    def _write_row(self, event: HypocenterEventLike) -> None:
        row = [_render(column.name, column.extract(event)) for column in COLUMNS]
        try:
            self._writer.writerow(row)
        except OSError as error:
            raise EventWriterError(
                f"Could not write a row to {self._path}: {error}"
            ) from error
        self._rows_written += 1

    def close(self) -> None:
        """Flush, close and publish the destination. Idempotent."""
        if self._closed:
            return
        self._closed = True
        handle, self._handle = self._handle, None
        temporary, self._temporary_path = self._temporary_path, None
        if handle is None or temporary is None:  # pragma: no cover - constructor failed
            return
        try:
            handle.close()
        except OSError as error:
            _unlink(temporary)
            raise EventWriterError(f"Could not flush {self._path}: {error}") from error
        try:
            # The rename is what publishes the file. Until it runs, the
            # destination path does not exist, so a failed run cannot leave a
            # short catalog that reads as complete.
            temporary.replace(self._path)
        except OSError as error:
            _unlink(temporary)
            raise EventWriterError(
                f"Could not publish {self._path}: {error}"
            ) from error

    def _discard(self) -> None:
        """Close and remove the partial file without publishing it."""
        self._closed = True
        handle, self._handle = self._handle, None
        temporary, self._temporary_path = self._temporary_path, None
        if handle is not None:
            try:
                handle.close()
            except OSError:  # pragma: no cover - the file is being discarded anyway
                pass
        if temporary is not None:
            _unlink(temporary)

    def _ensure_open(self) -> None:
        if self._closed:
            raise EventWriterError(
                f"Cannot write to {self._path}: the writer is closed."
            )

    def __enter__(self) -> CsvEventWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Publish on success; discard the partial file on the error path.

        Returns `None`, so the body's exception always propagates. Discarding
        rather than publishing is the whole point: an interrupted conversion
        must not leave behind a file that looks like a complete, short catalog.
        """
        if exc_type is not None:
            self._discard()
            return
        self.close()


def _unlink(path: Path) -> None:
    """Remove a partial file, ignoring the case where it is already gone."""
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - nothing useful to do while unwinding
        pass


#: Every type this writer knows how to turn into a CSV cell.
#:
#: A closed list, not a fallback. `csv.writer` calls `str()` on whatever it is
#: handed, and `str()` never fails: a `Decimal` becomes text at a precision the
#: Parquet column does not share, and an enum member becomes `"RecordType.JMA"`,
#: which is a perfectly ordinary string that lands in the column with no error
#: anywhere. Both were real: see the module docstring of `event_schema`.
#:
#: So an unrecognised type raises here instead. A type the writer has no rule
#: for is a programming error — a schema `extract` returning something new, or a
#: domain type that changed underfoot — and CONTRIBUTING's "prefer failing
#: loudly over returning a value that might be wrong" makes that an exception,
#: not a `str()`. It also keeps the two formats honest with each other: Arrow
#: already rejects a value it cannot fit in the declared column type, so with
#: this check the CSV writer refuses exactly what the Parquet writer refuses.
_RENDERABLE: Final = (bool, int, float, str)


def _render(column_name: str, value: object) -> Any:
    """One cell, as the text that must read back as the value written.

    Returns `None` for a null, which `csv.writer` renders as an empty unquoted
    field. An empty string is deliberately collapsed to that same empty field:
    CSV has one empty field and two things to say with it, and the module
    docstring sets out why the collapse is lossless for this catalog and why
    `csv.QUOTE_NOTNULL` is not available at the 3.11 baseline.

    Raises `EventWriterError` for any type not in `_RENDERABLE`.
    """
    if value is None:
        return None
    if column_name in _TIMESTAMP_ZONES:
        return _render_timestamp(column_name, value)
    if not isinstance(value, _RENDERABLE):
        raise EventWriterError(
            f"Column {column_name!r} produced a "
            f"{type(value).__name__}, which this writer has no rule for. "
            "Rendering it with str() could write text that disagrees with the "
            "Parquet column for the same value, so it is refused. Convert it "
            "in event_schema.py, where both writers see the conversion."
        )
    if isinstance(value, float):
        # `repr` is the shortest text that reads back as the identical double.
        return repr(value)
    if value == "":
        # Normalised to a null; see the module docstring. Returning `""` here
        # would be indistinguishable in the output anyway, so this makes the
        # collapse deliberate rather than incidental.
        return None
    return value


def _render_timestamp(column_name: str, value: object) -> str:
    if not isinstance(value, datetime):
        raise EventWriterError(
            f"origin_time must be a datetime, got {type(value).__name__}."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventWriterError(
            "origin_time must be timezone-aware. The JMA catalog is JST "
            "(UTC+9); a naive value would be written with a time zone this "
            "writer had to guess. See docs/jma-hypocenter-format.md."
        )
    moment = value.astimezone(_TIMESTAMP_ZONES[column_name])
    # Millisecond precision: the catalog's second field is F4.2, hundredths of
    # a second, so milliseconds are exact and microseconds would overstate it.
    text = moment.isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")
