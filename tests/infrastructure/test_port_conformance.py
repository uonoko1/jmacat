"""The adapters really do satisfy `EventWriter`, checked by the type system.

This is the assertion that makes the Protocol bridge worth anything. Both
writers are declared `EventWriter[HypocenterEventLike]` in a position mypy
checks, so a signature that drifts from the port — a renamed method, a `write`
that returns something, a `close` that takes an argument — fails
`uv run mypy` rather than surviving to a runtime `AttributeError` in an
interactor.

When issues #3/#4 land, `HypocenterEvent` satisfies `HypocenterEventLike`
structurally and `EventWriter[HypocenterEvent]` becomes spellable at the use
case boundary with no change to `infrastructure/`. If Dev-D's value object
spells an attribute differently, mypy reports it *there*, naming the attribute,
and the fix is one `extract` lambda in `event_schema.py`.
"""

from __future__ import annotations

from pathlib import Path

from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.event_protocol import HypocenterEventLike
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from jmacat.usecase.ports.event_writer import EventWriter
from tests.infrastructure.events import SampleEvent


def test_the_csv_writer_is_an_event_writer(tmp_path: Path) -> None:
    """Assigning to the annotated name is what mypy checks."""
    writer: EventWriter[HypocenterEventLike] = CsvEventWriter(tmp_path / "out.csv")
    writer.close()


def test_the_parquet_writer_is_an_event_writer(tmp_path: Path) -> None:
    writer: EventWriter[HypocenterEventLike] = ParquetEventWriter(
        tmp_path / "out.parquet"
    )
    writer.close()


def test_a_sample_event_satisfies_the_event_protocol() -> None:
    """A plain frozen dataclass satisfies the protocol with no inheritance.

    That is the property Dev-D's value object will rely on: nothing in
    `domain/` needs to know this protocol exists, or import anything from
    `infrastructure/` — which the dependency rule forbids anyway.
    """
    from datetime import datetime, timedelta, timezone

    event: HypocenterEventLike = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=timezone(timedelta(hours=9))),
        latitude_deg=35.0,
        longitude_deg=140.0,
    )
    assert event.record_type == "J"


def test_both_writers_work_through_the_port_type(tmp_path: Path) -> None:
    """A caller holding only the port can drive either adapter identically."""
    from datetime import datetime, timedelta, timezone

    event = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=timezone(timedelta(hours=9))),
        latitude_deg=35.0,
        longitude_deg=140.0,
    )
    writers: list[EventWriter[HypocenterEventLike]] = [
        CsvEventWriter(tmp_path / "out.csv"),
        ParquetEventWriter(tmp_path / "out.parquet"),
    ]
    for writer in writers:
        with writer as opened:
            opened.write(event)
            opened.write_many([event])

    assert (tmp_path / "out.csv").exists()
    assert (tmp_path / "out.parquet").exists()
