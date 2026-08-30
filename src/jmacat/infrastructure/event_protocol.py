"""The shape of an event these writers can serialise, as a structural type.

Why this file exists
--------------------

The domain event value object is issues #3/#4 and is being written in parallel;
it does not exist on `main`. `EventWriter` was designed for exactly this — it is
generic over a contravariant `EventT_contra` — so the port itself needs nothing.
But an *adapter* must eventually read fields off the event to put them in
columns, and it cannot do that against a bare TypeVar.

Three ways to bridge the gap were available:

* **Import the domain type.** Impossible today, and it would also invert the
  useful direction of the coupling: the writers would be unusable until the
  parser lands, and a test could no longer exercise them with a hand-built
  event.
* **Take `Any` and read attributes.** Types check, and every misspelt attribute
  becomes an `AttributeError` at row 200,000 of a real run. That is precisely
  the silent-wrong-answer failure mode CONTRIBUTING rules out.
* **A `Protocol`** — chosen. Protocols are *structural*: nothing needs to
  inherit from `HypocenterEventLike`, and nothing needs to import it. When
  Dev-D's `HypocenterEvent` lands with these attribute names, it satisfies this
  protocol automatically, `ParquetEventWriter` is an
  `EventWriter[HypocenterEvent]` with no edit here, and mypy checks the match at
  the composition site rather than leaving it to a runtime crash.

The one risk this carries is a *name* mismatch: if the domain type spells depth
`depth_km_below_sea_level`, mypy reports it the moment the interactor wires the
two together — loudly, at build time, naming the attribute. The fix is then a
one-line change to the corresponding `extract` lambda in `event_schema.py`,
because every attribute read in this package goes through that one table. No
writer code reads an event attribute directly.

The protocol is deliberately **read-only** (`@property`, not bare annotations).
A writer is a sink; it must never assign to the event it was handed, and a
frozen dataclass — which is what a domain value object should be — satisfies
read-only properties but not mutable attributes.

Units
-----

The units below are the *converted physical quantities* of issue #4, not the
packed integers of the record. Decimal degrees, kilometres, seconds, signed
magnitudes. An adapter converts nothing; conversion is domain work, and doing
any of it here would put the highest-consequence arithmetic in the project
outside the layer that tests it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class HypocenterEventLike(Protocol):
    """A converted hypocenter event, as the output writers need to read it.

    Every attribute typed `X | None` is genuinely optional in the catalog, and
    `None` must reach the output as a null. `None` is never a stand-in for zero
    (*Traps* 6 in `docs/jma-hypocenter-format.md`).
    """

    @property
    def record_type(self) -> str:
        """`J` JMA, `U` USGS, `I` other international. Field 1."""

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
    def origin_time_error_s(self) -> float | None:
        """Standard error of the origin time, in seconds. Field 8."""

    @property
    def latitude_deg(self) -> float:
        """Decimal degrees, positive north. Fields 9-10, converted."""

    @property
    def latitude_error_min(self) -> float | None:
        """Standard error of latitude, in minutes of arc. Field 11."""

    @property
    def longitude_deg(self) -> float:
        """Decimal degrees, positive east. Fields 12-13, converted."""

    @property
    def longitude_error_min(self) -> float | None:
        """Standard error of longitude, in minutes of arc. Field 14."""

    @property
    def depth_km(self) -> float | None:
        """Depth in kilometres, positive downward. Field 15, both encodings."""

    @property
    def depth_error_km(self) -> float | None:
        """Standard error of depth, in kilometres. Field 16."""

    @property
    def magnitude1(self) -> float | None:
        """Signed magnitude; negative values are real. Field 17."""

    @property
    def magnitude1_type(self) -> str | None:
        """Magnitude type code. Field 18."""

    @property
    def magnitude2(self) -> float | None:
        """Signed second magnitude. Field 19."""

    @property
    def magnitude2_type(self) -> str | None:
        """Second magnitude type code. Field 20."""

    @property
    def travel_time_table(self) -> str | None:
        """Travel time table code. Field 21."""

    @property
    def location_precision(self) -> str | None:
        """Hypocenter location precision code. Field 22."""

    @property
    def subsidiary_information(self) -> str | None:
        """Subsidiary information code. Field 23."""

    @property
    def maximum_intensity(self) -> str | None:
        """Maximum JMA shindo code. Field 24."""

    @property
    def damage_class(self) -> str | None:
        """Utsu damage class code. Field 25."""

    @property
    def tsunami_class(self) -> str | None:
        """Tsunami class code; its table depends on the year. Field 26."""

    @property
    def district_number(self) -> int | None:
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

    @property
    def determination_flag(self) -> str | None:
        """Hypocenter determination flag code. Field 31."""
