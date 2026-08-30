"""Contract tests for the use case output ports.

The ports are `typing.Protocol` declarations, so there is no behaviour of their
own to test. What *is* worth testing — and what these tests pin down — is the
contract every implementation must honour, exercised through the in-memory
fakes:

- `CatalogSource` streams; it never materialises a year in memory.
- An unavailable year raises `CatalogYearUnavailableError`; it never returns an
  empty stream that would read as "no earthquakes in this year".
- `EventWriter` accepts events incrementally and is usable as a context manager.

The fakes are the seam that lets every later use case test run with no network
and no filesystem, so their conformance is verified here rather than assumed.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from jmacat.usecase.errors import (
    CatalogRetrievalError,
    CatalogSourceError,
    CatalogYearUnavailableError,
    EventWriterError,
    PortError,
)
from jmacat.usecase.ports.catalog_source import CatalogSource
from jmacat.usecase.ports.contract import check_unavailable_year_fails_eagerly
from jmacat.usecase.ports.event_writer import EventWriter
from tests.fakes import (
    FailingEventWriter,
    InMemoryCatalogSource,
    InMemoryEventWriter,
    UnavailableYearCatalogSource,
)

# A JMA hypocenter catalog line is fixed-width; these stand in for record lines
# only as opaque strings. The port deliberately does not parse them - parsing is
# the domain layer's job (issue #3), so any non-empty str is a valid payload here.
SAMPLE_LINES = ("line-one", "line-two", "line-three")


class TestCatalogSourceProtocolConformance:
    def test_in_memory_fake_satisfies_the_catalog_source_protocol(self) -> None:
        """mypy --strict proves this statically; the assignment makes it explicit."""
        source: CatalogSource = InMemoryCatalogSource({2011: SAMPLE_LINES})
        assert isinstance(source, InMemoryCatalogSource)

    def test_unavailable_year_fake_satisfies_the_catalog_source_protocol(self) -> None:
        source: CatalogSource = UnavailableYearCatalogSource()
        assert isinstance(source, UnavailableYearCatalogSource)


class TestCatalogSourceStreaming:
    def test_yields_every_record_line_in_order(self) -> None:
        source: CatalogSource = InMemoryCatalogSource({2011: SAMPLE_LINES})

        assert list(source.record_lines(2011)) == list(SAMPLE_LINES)

    def test_returns_an_iterator_not_a_materialised_sequence(self) -> None:
        """A year is ~257,000 lines / ~25 MB; returning a list is a design smell."""
        source: CatalogSource = InMemoryCatalogSource({2011: SAMPLE_LINES})

        stream = source.record_lines(2011)

        assert iter(stream) is stream

    def test_is_lazy_so_an_unconsumed_year_costs_nothing(self) -> None:
        """Calling the port must not pull any line until the caller iterates."""
        source = InMemoryCatalogSource({2011: SAMPLE_LINES})

        stream = source.record_lines(2011)

        assert source.lines_yielded == 0
        next(iter(stream))
        assert source.lines_yielded == 1

    def test_a_caller_may_stop_early_without_consuming_the_whole_year(self) -> None:
        """Supports `--limit`-style use without paying for the full 25 MB."""
        source = InMemoryCatalogSource({2011: SAMPLE_LINES})

        first_two = list(itertools.islice(source.record_lines(2011), 2))

        assert first_two == list(SAMPLE_LINES[:2])
        assert source.lines_yielded == 2

    def test_an_empty_year_yields_no_lines_without_raising(self) -> None:
        """A genuinely empty year is a legitimate result, distinct from a missing one."""
        source: CatalogSource = InMemoryCatalogSource({2011: ()})

        assert list(source.record_lines(2011)) == []


class TestCatalogSourceFailure:
    def test_an_unavailable_year_raises_rather_than_yielding_nothing(self) -> None:
        """h2024.zip currently 404s: the finalized catalog lags years behind.

        This must never be mistaken for a year with no earthquakes.
        """
        source: CatalogSource = UnavailableYearCatalogSource()

        with pytest.raises(CatalogYearUnavailableError):
            list(source.record_lines(2024))

    def test_the_unavailable_year_is_carried_on_the_error(self) -> None:
        source: CatalogSource = UnavailableYearCatalogSource()

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            list(source.record_lines(2024))

        assert excinfo.value.year == 2024
        assert "2024" in str(excinfo.value)

    def test_a_year_absent_from_the_in_memory_fake_is_also_unavailable(self) -> None:
        source: CatalogSource = InMemoryCatalogSource({2011: SAMPLE_LINES})

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            list(source.record_lines(1998))

        assert excinfo.value.year == 1998

    def test_the_error_is_raised_eagerly_at_call_time(self) -> None:
        """Failing before iteration keeps the failure adjacent to its cause.

        A generator that only raises on first `next()` would surface the 404
        deep inside an unrelated loop, far from the call that caused it.
        """
        source: CatalogSource = UnavailableYearCatalogSource()

        with pytest.raises(CatalogYearUnavailableError):
            source.record_lines(2024)

    def test_the_unavailable_year_fake_honours_the_shared_eager_contract(self) -> None:
        """The same check issue #6's HTTP adapter runs against itself.

        Asserted here too so the fakes cannot drift from the rule their
        production counterparts are held to.
        """
        check_unavailable_year_fails_eagerly(
            UnavailableYearCatalogSource(), unavailable_year=2024
        )

    def test_the_in_memory_fake_honours_the_shared_eager_contract(self) -> None:
        check_unavailable_year_fails_eagerly(
            InMemoryCatalogSource({2011: SAMPLE_LINES}), unavailable_year=1998
        )


class TestEventWriterProtocolConformance:
    def test_in_memory_fake_satisfies_the_event_writer_protocol(self) -> None:
        writer: EventWriter[str] = InMemoryEventWriter[str]()
        assert isinstance(writer, InMemoryEventWriter)

    def test_failing_fake_satisfies_the_event_writer_protocol(self) -> None:
        writer: EventWriter[str] = FailingEventWriter[str]()
        assert isinstance(writer, FailingEventWriter)


class TestEventWriterStreaming:
    def test_writes_events_incrementally_in_order(self) -> None:
        writer = InMemoryEventWriter[str]()

        with writer:
            writer.write("a")
            writer.write("b")

        assert writer.events == ["a", "b"]

    def test_accepts_a_batch_without_holding_the_year_in_memory(self) -> None:
        """`write_many` takes an Iterable so a generator can stream straight through."""
        writer = InMemoryEventWriter[str]()

        def generated() -> Iterator[str]:
            yield "a"
            yield "b"

        with writer:
            writer.write_many(generated())

        assert writer.events == ["a", "b"]

    def test_write_many_consumes_lazily_rather_than_listing_its_input(self) -> None:
        writer = InMemoryEventWriter[str]()
        consumed: list[str] = []

        def tracked() -> Iterator[str]:
            for event in ("a", "b"):
                consumed.append(event)
                yield event

        with writer:
            writer.write_many(tracked())

        assert consumed == ["a", "b"]
        assert writer.events == ["a", "b"]

    def test_writing_nothing_still_produces_a_closed_destination(self) -> None:
        """An empty result must still create a well-formed output, not nothing."""
        writer = InMemoryEventWriter[str]()

        with writer:
            pass

        assert writer.events == []
        assert writer.closed is True


class TestEventWriterLifecycle:
    def test_the_context_manager_closes_the_destination(self) -> None:
        """Parquet and CSV both need a footer/flush, so close must be explicit."""
        writer = InMemoryEventWriter[str]()

        with writer as entered:
            assert entered is writer
            assert writer.closed is False

        assert writer.closed is True

    def test_the_destination_is_closed_even_when_the_body_raises(self) -> None:
        """A half-written Parquet file must not be left behind on error."""
        writer = InMemoryEventWriter[str]()

        # Not combined into one `with`: the writer's __exit__ must run inside the
        # `raises` scope, which is exactly the close-on-error path under test.
        with pytest.raises(RuntimeError):  # noqa: SIM117
            with writer:
                writer.write("a")
                raise RuntimeError("conversion failed")

        assert writer.closed is True
        assert writer.events == ["a"]

    def test_writing_after_close_is_refused(self) -> None:
        writer = InMemoryEventWriter[str]()

        with writer:
            writer.write("a")

        with pytest.raises(EventWriterError):
            writer.write("b")


class TestEventWriterFailure:
    def test_a_failing_destination_raises_a_typed_writer_error(self) -> None:
        writer: EventWriter[str] = FailingEventWriter[str]()

        with pytest.raises(EventWriterError):
            writer.write("a")

    def test_the_failing_fake_still_closes_so_cleanup_paths_are_testable(self) -> None:
        writer = FailingEventWriter[str]()

        # Not combined: __exit__ must run inside the `raises` scope so the test can
        # assert the destination was still closed after a failing write.
        with pytest.raises(EventWriterError):  # noqa: SIM117
            with writer:
                writer.write("a")

        assert writer.closed is True


class TestErrorHierarchy:
    def test_every_port_error_shares_one_base(self) -> None:
        """Lets a caller catch all port failures without naming each one."""
        assert issubclass(CatalogSourceError, PortError)
        assert issubclass(EventWriterError, PortError)

    def test_year_unavailable_is_a_catalog_source_error(self) -> None:
        assert issubclass(CatalogYearUnavailableError, CatalogSourceError)

    def test_port_errors_are_exceptions(self) -> None:
        assert issubclass(PortError, Exception)


class TestErrorRetryability:
    """Retryability is carried on the error, not re-derived by each caller.

    A retry loop reads `err.retryable`; it must not have to know the taxonomy.
    """

    def test_an_unpublished_year_is_not_retryable(self) -> None:
        """Waiting will not make JMA publish h2024.zip sooner."""
        assert CatalogYearUnavailableError(2024).retryable is False

    def test_a_transfer_or_archive_failure_is_retryable(self) -> None:
        """A timeout, a 5xx or a truncated download may succeed on a re-run."""
        assert CatalogRetrievalError("timeout").retryable is True

    def test_a_writer_failure_is_not_retryable(self) -> None:
        """A full disk does not fix itself, and a retry risks duplicate records."""
        assert EventWriterError("disk full").retryable is False

    def test_an_unrecognised_port_failure_defaults_to_not_retryable(self) -> None:
        """A new subclass must opt in; the safe default is to fail loudly."""
        assert PortError("something new").retryable is False

    def test_retryability_is_readable_without_isinstance_checks(self) -> None:
        """The point of the attribute: one branch handles every port error."""
        errors: list[PortError] = [
            CatalogYearUnavailableError(2024),
            CatalogRetrievalError("timeout"),
            EventWriterError("disk full"),
        ]

        assert [e.retryable for e in errors] == [False, True, False]
