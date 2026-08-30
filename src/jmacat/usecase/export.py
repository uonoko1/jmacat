"""The export interactor: fetch a year, convert it, filter it, write it.

One use case, called identically by the CLI (`jmacat.controller.cli`) and by any
Python caller. That is the point: `export` is the only place the steps are
sequenced, so the command line and the SDK cannot drift into two behaviours.

Standard library only, and it names no adapter. The catalog arrives through
`CatalogSource` and leaves through `EventWriter`; a test drives it with the
in-memory fakes and no network or filesystem at all.

Counting what a filter drops, and why
-------------------------------------

A filter result is not one number. `magnitude_range(minimum=3.0)` over `h1919`
(1919-1950) selects 15,874 of 28,235 records — and of the 12,361 it rejects,
**11,621 (41.2 per cent of the corpus) carry no magnitude at all**, rather than
a magnitude below 3.0. A researcher told only "15,874 events" has no way to see
that two fifths of the era went missing for a reason unrelated to their query.

So `ExportResult` reports the two exclusions separately, per filtered field
(`FilterOutcome`). The distinction is drawn here rather than in
`domain/filters.py`, which is pure predicates by design: a predicate that
accumulated a count would no longer be a pure function, and the same predicate
is used in contexts that must not pay for counting. What this layer does instead
is ask the *value* whether it was present, using the same policy the predicate
applies, and attribute the rejection accordingly.

That leaves one honest limitation, stated rather than hidden: attribution is
per-record and first-match. A record failing several filters is attributed to
the first that rejects it, in the order the filters were given, so the outcome
counts partition the input exactly once and always sum to the total. They are
not "how many records each filter would drop in isolation", which would
double-count and could not sum.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path

from jmacat.domain.filters import (
    Bound,
    EventPredicate,
    FilterableEvent,
    bounding_box,
    depth_range,
    magnitude_range,
    named_area,
)
from jmacat.domain.hypocenter import Hypocenter, RecordError, parse_record
from jmacat.usecase.ports import CatalogSource, EventWriter


class OutputFormat(Enum):
    """The formats an export can be written in.

    Named here, in the use case layer, rather than in the CLI: the SDK caller
    chooses a format too, and a `str` passed straight to an adapter factory
    would let "parqet" reach the filesystem before failing.
    """

    PARQUET = "parquet"
    CSV = "csv"


class ExportError(Exception):
    """The export request itself is malformed; nothing was fetched or written."""


@dataclass(frozen=True)
class FilterSpec:
    """One named filter: its predicate, and how to read the value it tests.

    `measurement` is what makes the missing-value count possible without
    putting a counter in `domain/filters.py`. It reads the field the predicate
    tests off an event, so the interactor can ask "was this rejected because
    the value fell outside the range, or because there was no value?" — and it
    asks that question the same way `_passes_optional_range` does, by testing
    for `None`.

    A filter whose test cannot be missing — `time_range`, `bounding_box`; an
    origin time and a coordinate are never `None` on a parsed record — carries
    `measurement=None`, and every rejection it makes is a comparison.
    """

    name: str
    predicate: EventPredicate
    measurement: Callable[[FilterableEvent], Decimal | None] | None = None

    def rejects_for_a_missing_value(self, event: FilterableEvent) -> bool:
        """Whether this filter rejected `event` for having no value to test."""
        return self.measurement is not None and self.measurement(event) is None


@dataclass(frozen=True)
class FilterOutcome:
    """What one filter did to the records that reached it.

    `excluded_missing` is the number this project exists to surface; see the
    module docstring. It is zero for a filter over a field that is never blank,
    and that zero is meaningful — it says the filter was applied and dropped
    nothing for absence, not that nobody looked.
    """

    name: str
    excluded_by_comparison: int
    excluded_missing_value: int

    @property
    def excluded(self) -> int:
        return self.excluded_by_comparison + self.excluded_missing_value


@dataclass(frozen=True)
class ExportResult:
    """What one export run did, in counts that add up.

    `records_read` is every line the source yielded. Each line then lands in
    exactly one of three places, so the four numbers reconcile:

        records_read == records_written + records_rejected + records_excluded

    `records_rejected` is lines that failed to parse — never silently dropped;
    `rejections` keeps the first few messages so a user can see what was wrong
    rather than only how many.
    """

    year: int
    destination: Path
    output_format: OutputFormat
    records_read: int
    records_written: int
    records_rejected: int
    filter_outcomes: tuple[FilterOutcome, ...] = ()
    rejections: tuple[str, ...] = ()

    @property
    def records_excluded(self) -> int:
        """Records a filter excluded, for any reason."""
        return sum(outcome.excluded for outcome in self.filter_outcomes)

    @property
    def records_excluded_for_a_missing_value(self) -> int:
        """Records excluded because the field a filter tests was blank."""
        return sum(outcome.excluded_missing_value for outcome in self.filter_outcomes)

    def reconciles(self) -> bool:
        """Whether every record read is accounted for exactly once."""
        return self.records_read == (
            self.records_written + self.records_rejected + self.records_excluded
        )


#: How many parse failures to keep the message of. A corrupt archive could fail
#: on every one of 257,020 lines; holding them all would turn a reporting
#: convenience into a memory problem, and the count is reported in full anyway.
MAX_REPORTED_REJECTIONS = 10


@dataclass(frozen=True)
class ExportRequest:
    """One export: which year, filtered how, written where and in what format.

    The filters are given as the values a caller actually has — a magnitude
    bound, an area name — rather than as predicates, so the CLI and an SDK
    caller build the identical request from the identical arguments and the
    interactor is the only place that turns them into predicates. That is what
    keeps `--min-magnitude 3.0` and `min_magnitude=3.0` from meaning two
    different things.

    Bounds are `Bound` (float, int or Decimal), normalised by `domain.filters`
    to the decimal that was written; see `filters._as_decimal` for why a raw
    float bound silently drops the records sitting exactly on it.
    """

    year: int
    destination: Path
    output_format: OutputFormat = OutputFormat.PARQUET
    area: str | None = None
    min_magnitude: Bound | None = None
    max_magnitude: Bound | None = None
    min_depth_km: Bound | None = None
    max_depth_km: Bound | None = None

    def filters(self) -> tuple[FilterSpec, ...]:
        """The filters this request asks for, in the order they are applied.

        Cheapest first, as `domain.filters.all_of` advises: the numeric range
        tests are two comparisons, the bounding box is four.

        Raises:
            UnknownAreaError: `area` is not a name `named_area` knows.
        """
        specs: list[FilterSpec] = []
        if self.min_magnitude is not None or self.max_magnitude is not None:
            specs.append(
                FilterSpec(
                    name="magnitude",
                    predicate=magnitude_range(
                        minimum=self.min_magnitude, maximum=self.max_magnitude
                    ),
                    measurement=lambda event: event.magnitude,
                )
            )
        if self.min_depth_km is not None or self.max_depth_km is not None:
            specs.append(
                FilterSpec(
                    name="depth",
                    predicate=depth_range(
                        minimum_km=self.min_depth_km, maximum_km=self.max_depth_km
                    ),
                    measurement=lambda event: event.depth_km,
                )
            )
        if self.area is not None:
            # Resolved here so an unknown name fails before anything is
            # fetched or a destination file is staged.
            specs.append(
                FilterSpec(name="area", predicate=bounding_box(named_area(self.area)))
            )
        return tuple(specs)


def export(
    request: ExportRequest,
    *,
    source: CatalogSource,
    writer: EventWriter[Hypocenter],
) -> ExportResult:
    """Run one export and return what it did.

    The writer is passed in already open, and this function does **not** close
    it: whoever built the destination owns its lifetime, and closing here would
    publish a file on a path where the caller's own `with` still had cleanup to
    do. `jmacat.controller.cli` wraps the call in `with`, which is what makes an
    interrupted run leave no file behind — the writers stage to a temporary
    file and publish by atomic rename only on a clean `close`.

    Raises:
        CatalogYearUnavailableError: JMA does not publish `request.year`.
        CatalogRetrievalError: the year exists but could not be fetched.
        EventWriterError: the destination could not be written.
        UnknownAreaError: `request.area` names no known area.
    """
    specs = request.filters()
    # Resolved before the first fetch, so a bad area name costs no download.
    lines = source.record_lines(request.year)

    counter = _Counter(specs)
    writer.write_many(counter.selected(lines))
    return counter.result(request)


class _Counter:
    """Parses, filters and counts a stream, attributing every record it drops.

    A class rather than a closure because the counts must survive the generator
    the writer consumes: `write_many` is handed a lazy iterator, so the numbers
    are only final once the writer has drained it, and they have to be readable
    afterwards from the outside.
    """

    def __init__(self, specs: Sequence[FilterSpec]) -> None:
        self._specs = tuple(specs)
        self._by_comparison = [0] * len(self._specs)
        self._missing = [0] * len(self._specs)
        self.records_read = 0
        self.records_written = 0
        self.records_rejected = 0
        self.rejections: list[str] = []

    def selected(self, lines: Iterator[str]) -> Iterator[Hypocenter]:
        """Yield the events that pass every filter, counting the rest.

        Lazy, so a year streams through at constant memory rather than being
        materialised before the first row is written.
        """
        for line in lines:
            self.records_read += 1
            event = self._parse(line)
            if event is None:
                continue
            if self._admits(event):
                self.records_written += 1
                yield event

    def _parse(self, line: str) -> Hypocenter | None:
        """Decode one line, counting and describing a failure rather than raising.

        A single malformed line must not abort a 257,020-record year, but it
        must not vanish either: it is counted, and the first few messages are
        kept so the report says *what* was wrong. CONTRIBUTING's "fail loudly"
        is honoured by reporting, not by discarding.
        """
        try:
            return parse_record(line)
        except RecordError as error:
            self.records_rejected += 1
            if len(self.rejections) < MAX_REPORTED_REJECTIONS:
                self.rejections.append(str(error))
            return None

    def _admits(self, event: Hypocenter) -> bool:
        """Whether every filter accepts `event`, attributing the first rejection.

        First-match attribution, so the outcome counts partition the input
        exactly once; see the module docstring.
        """
        for index, spec in enumerate(self._specs):
            if spec.predicate(event):
                continue
            if spec.rejects_for_a_missing_value(event):
                self._missing[index] += 1
            else:
                self._by_comparison[index] += 1
            return False
        return True

    def result(self, request: ExportRequest) -> ExportResult:
        return ExportResult(
            year=request.year,
            destination=request.destination,
            output_format=request.output_format,
            records_read=self.records_read,
            records_written=self.records_written,
            records_rejected=self.records_rejected,
            filter_outcomes=tuple(
                FilterOutcome(
                    name=spec.name,
                    excluded_by_comparison=self._by_comparison[index],
                    excluded_missing_value=self._missing[index],
                )
                for index, spec in enumerate(self._specs)
            ),
            rejections=tuple(self.rejections),
        )
