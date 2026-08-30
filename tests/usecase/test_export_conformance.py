"""The conformance assignments for the export interactor's boundary.

CONTRIBUTING records that two layers once independently guessed `float` where
`domain/` uses `Decimal`, and that nothing forced the types to meet until
someone tried to compose them. The interactor is that composition point: it is
the first module that names the event type, the source port and the writer port
in one place.

So these assignments are written **before** the interactor, and each one is a
`probe: TheProtocol = the_real_thing(...)` that mypy has to prove. A protocol
nothing has ever been checked against is a guess.

`assert probe is not None` keeps the binding from being an unused local; the
work of the test is done by mypy, and pytest only proves the modules import.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from jmacat.domain.filters import FilterableEvent
from jmacat.domain.hypocenter import Hypocenter, parse_record
from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from jmacat.usecase.export import ExportRequest, ExportResult
from jmacat.usecase.ports import CatalogSource, EventWriter
from tests.fakes import InMemoryCatalogSource, InMemoryEventWriter

# h2023 line 1, verbatim from the published catalog. 96 columns; the
# trailing spaces before the station count are part of the record, so the
# literal is split at a column boundary rather than reflowed.
REAL_LINE = (
    "J2023010100080150 012 354059 100 1403927 136 50 "
    "    03v   721   3110NEAR CHOSHI CITY          9A"
)


def test_the_real_catalog_adapter_satisfies_the_source_port() -> None:
    """`JmaCatalogSource` is what the interactor will be handed for `source`."""
    probe: CatalogSource = JmaCatalogSource()
    assert probe is not None


def test_the_fake_catalog_source_satisfies_the_source_port() -> None:
    probe: CatalogSource = InMemoryCatalogSource({2023: []})
    assert probe is not None


def test_the_csv_writer_accepts_the_domain_event_the_interactor_produces(
    tmp_path: Path,
) -> None:
    """`EventWriter[Hypocenter]` is the spelling at the use case boundary.

    The port is contravariant in its event type, so this assignment only type
    checks if `CsvEventWriter` really does accept a `Hypocenter` — the exact
    agreement the `Decimal`/`float` incident broke.
    """
    with CsvEventWriter(tmp_path / "events.csv") as writer:
        probe: EventWriter[Hypocenter] = writer
        assert probe is not None


def test_the_parquet_writer_accepts_the_domain_event_the_interactor_produces(
    tmp_path: Path,
) -> None:
    with ParquetEventWriter(tmp_path / "events.parquet") as writer:
        probe: EventWriter[Hypocenter] = writer
        assert probe is not None


def test_the_fake_writer_satisfies_the_writer_port() -> None:
    probe: EventWriter[Hypocenter] = InMemoryEventWriter[Hypocenter]()
    assert probe is not None


def test_a_parsed_record_satisfies_the_filter_protocol_the_request_carries() -> None:
    """The events the interactor filters are the events the parser produces.

    `ExportRequest.filters` holds `EventPredicate`s, which read a
    `FilterableEvent`. This is the assignment that makes mypy check the
    measurement types are `Decimal` on both sides.
    """
    probe: FilterableEvent = parse_record(REAL_LINE)
    assert probe.magnitude == Decimal("0.3")


def test_the_request_and_result_name_the_types_they_carry(tmp_path: Path) -> None:
    """The interactor's own vocabulary exists and is importable."""
    request = ExportRequest(year=2023, destination=tmp_path / "events.csv")
    assert request.year == 2023
    assert ExportResult is not None
