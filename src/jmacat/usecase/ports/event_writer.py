"""The `EventWriter` output port.

What the use case layer needs in order to emit converted events, expressed
without naming a format. Parquet, CSV, stdout and an in-memory fake all satisfy
it identically.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import TracebackType
from typing import Protocol, TypeVar, runtime_checkable

# The converted event type.
#
# The domain event value object is issue #3 and does not exist yet, so the port
# is generic over the event type rather than naming one. This is a TypeVar and
# not `Any`, and not a forward reference to a type that has not been designed:
#
#   - `Any` would erase the relationship between what a use case produces and
#     what its writer accepts, so a writer of the wrong event type would type
#     check silently. That is the one mistake this port exists to catch.
#   - A forward reference (`"Hypocenter"`) would couple this file to a name
#     issue #3 has not agreed on yet, and would make `usecase/ports/` fail to
#     import until that issue lands - blocking work that only needs the seam.
#   - A TypeVar states the actual contract: a writer is a sink of *some* event
#     type, and the use case that owns both must agree on which.
#
# The TypeVar is *contravariant* because the event type appears only in parameter
# position (`write`, `write_many`) and never in a return type. That makes a writer
# of a wider event type usable wherever a narrower one is expected — an
# `EventWriter[object]` can accept `Hypocenter`s — which is the sound
# direction for a sink. Contravariance is not optional here: an invariant TypeVar
# does not compile in this position, and mypy --strict rejects it outright with
#   error: Invariant type variable "T" used in protocol where contravariant one
#   is expected  [misc]
#
# When issue #3 lands, `EventWriter[Hypocenter]` is the intended spelling at
# the use case boundary; nothing in this file needs to change to allow it.
EventT_contra = TypeVar("EventT_contra", contravariant=True)


@runtime_checkable
class EventWriter(Protocol[EventT_contra]):
    """Writes converted events to a destination.

    Design notes
    ------------

    **Why streaming.** The writer is the downstream half of the same pipeline
    `CatalogSource` feeds: ~257,000 events for one year, more for a multi-year
    run. Requiring `write_all(events: Sequence[...])` would force the caller to
    materialise the year first and undo the streaming the source was designed
    for. So the port accepts events one at a time (`write`) or as a lazily
    consumed `Iterable` (`write_many`), and never asks for a length.

    `Iterable` rather than `Iterator` on `write_many` is deliberate, and is the
    opposite choice from `CatalogSource.record_lines` for a reason: here the
    parameter is an *input the caller supplies*, so accepting the wider type is
    a convenience that costs nothing — a list, a tuple and a generator are all
    valid, and the implementation simply iterates once. There the return type
    was a *promise the implementation makes*, where the narrower `Iterator` is
    what forbids an eager implementation.

    **Why an explicit close, and a context manager.** Every realistic
    destination has a finalisation step that can itself fail: Parquet writes a
    footer with the schema and row-group index, CSV flushes a buffer, a file
    handle must be released. A writer with no close would either leave a
    truncated, unreadable file behind or hide the flush in `__del__`, where the
    error is unraisable and the failure becomes silent — the failure mode
    CONTRIBUTING explicitly rules out.

    The context-manager shape (`__enter__`/`__exit__`) is included alongside
    `close` so that the destination is finalised on the error path too. A
    conversion that raises partway through a year must not leave a half-written
    Parquet file that later reads as a complete, short catalog. `with` makes
    that guarantee structural rather than a thing each interactor must remember.

    `close` is idempotent, so `with` around an explicitly closed writer is safe.

    **Why no `flush`.** Durability points are the adapter's business; exposing
    one here would invite use cases to make guesses about buffering that only
    the concrete format can honour.
    """

    def write(self, event: EventT_contra) -> None:
        """Write a single event.

        Raises:
            EventWriterError: the event could not be written, or the writer has
                already been closed.
        """
        ...

    def write_many(self, events: Iterable[EventT_contra]) -> None:
        """Write a batch of events, consuming `events` lazily.

        Equivalent to calling `write` for each event, but lets an implementation
        batch the underlying operation — a Parquet row group, a single buffered
        CSV pass. The iterable must not be listed by the implementation.

        Raises:
            EventWriterError: the events could not be written, or the writer has
                already been closed.
        """
        ...

    def close(self) -> None:
        """Finalise the destination and release its resources.

        Must be idempotent: closing an already-closed writer is a no-op. After
        close, `write` and `write_many` raise `EventWriterError`.

        Raises:
            EventWriterError: the destination could not be finalised. This is a
                real failure — a Parquet footer that could not be written means
                the output is unreadable — and must not be suppressed.
        """
        ...

    def __enter__(self) -> EventWriter[EventT_contra]:
        """Return the writer itself, ready to accept events."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the destination, whether or not the body raised.

        Returns `None` so an exception from the body always propagates: a
        conversion failure must reach the caller, never be swallowed by cleanup.
        """
        ...
