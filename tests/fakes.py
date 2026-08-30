"""In-memory fakes for the use case output ports.

These are the seam that lets every later use case test run with no network and
no filesystem. They are deliberately real implementations rather than mocks: a
mock asserts that a call happened, whereas these honour the port's actual
semantics — laziness, ordering, close-once, and the difference between a missing
year and an empty one — so a test written against them fails when an interactor
misuses the boundary.

They live under `tests/` because they are test doubles, not shipped code; the
production adapters are `infrastructure/` (issues #6 and #7).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from types import TracebackType
from typing import Generic, TypeVar

from jmacat.usecase.errors import CatalogYearUnavailableError, EventWriterError

EventT = TypeVar("EventT")


class InMemoryCatalogSource:
    """A `CatalogSource` backed by a dict of year to record lines.

    Streams lazily and counts what it has yielded, so a test can assert that a
    caller did not consume more of the catalog than it needed.
    """

    def __init__(self, years: Mapping[int, Sequence[str]]) -> None:
        self._years = dict(years)
        self.lines_yielded = 0
        self.requested_years: list[int] = []

    def record_lines(self, year: int) -> Iterator[str]:
        self.requested_years.append(year)
        # Availability is resolved eagerly, before the generator is returned, so
        # the failure surfaces at the call site rather than on first `next()`.
        if year not in self._years:
            raise CatalogYearUnavailableError(year)
        return self._generate(self._years[year])

    def _generate(self, lines: Sequence[str]) -> Iterator[str]:
        for line in lines:
            self.lines_yielded += 1
            yield line


class UnavailableYearCatalogSource:
    """A `CatalogSource` for which every year is unavailable.

    Stands in for JMA's 404 on a year the finalized catalog has not reached yet
    (h2024.zip today), so failure paths are testable without a network.
    """

    def __init__(self) -> None:
        self.requested_years: list[int] = []

    def record_lines(self, year: int) -> Iterator[str]:
        self.requested_years.append(year)
        raise CatalogYearUnavailableError(year)


class InMemoryEventWriter(Generic[EventT]):
    """An `EventWriter` collecting events in a list for inspection."""

    def __init__(self) -> None:
        self.events: list[EventT] = []
        self.closed = False

    def write(self, event: EventT) -> None:
        self._ensure_open()
        self.events.append(event)

    def write_many(self, events: Iterable[EventT]) -> None:
        self._ensure_open()
        # Iterated rather than listed, to honour the port's lazy-consumption
        # contract and to keep a generator input streaming.
        for event in events:
            self.events.append(event)

    def close(self) -> None:
        self.closed = True

    def _ensure_open(self) -> None:
        if self.closed:
            raise EventWriterError("Cannot write to a closed EventWriter.")

    def __enter__(self) -> InMemoryEventWriter[EventT]:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class FailingEventWriter(Generic[EventT]):
    """An `EventWriter` whose destination rejects every write.

    Stands in for a full disk or an unwritable path, so a use case's cleanup and
    error-reporting paths can be tested. It still closes on exit, which is what
    lets a test assert that a failed run does not leak an open destination.
    """

    def __init__(self, message: str = "destination is unavailable") -> None:
        self._message = message
        self.closed = False

    def write(self, event: EventT) -> None:
        raise EventWriterError(self._message)

    def write_many(self, events: Iterable[EventT]) -> None:
        raise EventWriterError(self._message)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FailingEventWriter[EventT]:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
