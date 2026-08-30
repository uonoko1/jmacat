"""The shape of an event these writers can serialise, as a structural type.

Why this file exists
--------------------

The domain value object is issues #3/#4, developed on a parallel branch; it does
not exist on this one. `EventWriter` was designed for exactly this — it is
generic over a contravariant `EventT_contra` — so the port itself needs nothing.
But an *adapter* must eventually read fields off the event to put them in
columns, and it cannot do that against a bare TypeVar.

Three ways to bridge the gap were available:

* **Import the domain type.** Impossible on this branch, and it would also
  invert the useful direction of the coupling: the writers would be unusable
  until the parser lands, and a test could no longer exercise them with a
  hand-built event.
* **Take `Any` and read attributes.** Types check, and every misspelt attribute
  becomes an `AttributeError` at row 200,000 of a real run. That is precisely
  the silent-wrong-answer failure mode CONTRIBUTING rules out.
* **A `Protocol`** — chosen. Protocols are *structural*: nothing needs to
  inherit from `HypocenterEventLike`, and nothing needs to import it. Dev-D's
  `Hypocenter` satisfies this protocol automatically, `ParquetEventWriter` is an
  `EventWriter[Hypocenter]` with no edit here, and mypy checks the match at the
  composition site rather than leaving it to a runtime crash.

This protocol describes `domain.hypocenter.Hypocenter` as that module actually
defines it, attribute for attribute. It is deliberately a *mirror*, not a wish:
an earlier revision of this file invented names and types the domain does not
use, and because a Protocol is structural, nothing failed until the two were
wired together. `domain/` is the inner layer and is authoritative; this file
adapts to it and never the reverse.

The protocol is deliberately **read-only** (`@property`, not bare annotations).
A writer is a sink; it must never assign to the event it was handed, and a
frozen dataclass — which is what a domain value object should be — satisfies
read-only properties but not mutable attributes.

Types
-----

Two of the domain's choices matter more to a writer than they look:

* `record_type` is an **enum member**, not its `str` code. `str(RecordType.JMA)`
  is the text `"RecordType.JMA"`, which CSV would happily write into the column
  with no error at all. The writers therefore convert it explicitly, through
  `.value`, rather than letting a `str()` fallback decide.
* Coordinates, depth and magnitudes are **`Decimal`**, not `float`. The domain
  is right to decode a fixed-point field exactly; the output schema declares
  `double`, so the narrowing happens once, in `event_schema._as_double`, and
  both formats therefore serialise the identical IEEE-754 value.

Neither is something a writer may infer from the runtime type of whatever it is
handed. `csv_event_writer._render` rejects any type it has no rule for.

Units
-----

The units below are the *converted physical quantities* of issue #4, not the
packed integers of the record. Decimal degrees, kilometres, seconds, signed
magnitudes. An adapter converts no units; unit conversion is domain work, and
doing any of it here would put the highest-consequence arithmetic in the project
outside the layer that tests it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class RecordTypeLike(Protocol):
    """The enum `Hypocenter.record_type` carries: `J`, `U` or `I` in `.value`.

    Structural, like the event protocol itself, so `domain.RecordType` satisfies
    it without either module importing the other. Only `.value` is read — the
    member *name* (`JMA`, `USGS`, `INTERNATIONAL`) is a Python identifier chosen
    for readability, while `.value` is the code the record actually contains and
    the one a researcher joins against.
    """

    @property
    def value(self) -> str:
        """The single-character record type code as published: `J`, `U`, `I`."""


@runtime_checkable
class HypocenterEventLike(Protocol):
    """A decoded hypocenter, as the output writers need to read it.

    Mirrors `domain.hypocenter.Hypocenter`. Every attribute typed `X | None` is
    genuinely optional in the catalog, and `None` must reach the output as a
    null. `None` is never a stand-in for zero (*Traps* 6 in
    `docs/jma-hypocenter-format.md`).
    """

    @property
    def record_type(self) -> RecordTypeLike:
        """Who determined the hypocenter. `J` JMA, `U` USGS, `I` other. Field 1."""

    @property
    def origin_time(self) -> datetime:
        """The origin time as a **timezone-aware** `datetime`.

        Aware, not naive: the catalog's times are JST (UTC+9) and the writers
        emit both a UTC and a JST column from this one value. A naive datetime
        would force the adapter to guess which one it had been given, and the
        guess would be invisible in the output — the exact ambiguity issue #7
        forbids. An adapter therefore rejects a naive value rather than
        assuming a zone.
        """

    @property
    def second_is_known(self) -> bool:
        """False when the second field was blank: located only to the minute.

        Carried into the output because `origin_time` must render *some*
        second, so without this column a reader cannot tell an undetermined
        second from a determined 00.00 s.
        """

    @property
    def latitude(self) -> Decimal:
        """Decimal degrees, positive north. Fields 9-10, converted."""

    @property
    def latitude_minutes_are_known(self) -> bool:
        """False when the minutes field was blank: whole-degree epicentre only.

        Without it, a latitude of exactly 35 is indistinguishable from a
        determination of 35 deg 00.00 min — an accuracy claim JMA did not make.
        """

    @property
    def longitude(self) -> Decimal:
        """Decimal degrees, positive east. Fields 12-13, converted."""

    @property
    def longitude_minutes_are_known(self) -> bool:
        """False when the minutes field was blank. See `latitude_minutes_are_known`."""

    @property
    def depth_km(self) -> Decimal | None:
        """Depth in kilometres, positive downward. Field 15, both encodings."""

    @property
    def magnitude(self) -> Decimal | None:
        """Signed magnitude; negative values are real. Field 17."""

    @property
    def magnitude_type(self) -> str | None:
        """Magnitude type code. Field 18."""

    @property
    def magnitude_2(self) -> Decimal | None:
        """Signed second magnitude. Field 19."""

    @property
    def magnitude_type_2(self) -> str | None:
        """Second magnitude type code. Field 20."""

    @property
    def district(self) -> int | None:
        """JMA geographical district number. Field 27."""

    @property
    def region_number(self) -> int | None:
        """JMA epicentre region number. Field 28."""

    @property
    def region_name(self) -> str | None:
        """Epicentre region name as published in the record. Field 29."""

    @property
    def station_count(self) -> int | None:
        """Stations contributing to the determination. Field 30."""
