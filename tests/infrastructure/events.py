"""A stand-in hypocenter event for the writer tests.

The domain value object lives on Dev-D's branch and is not on this one yet.
This module is *not* a substitute for it and must not grow any conversion
logic: it exists only to give the writer tests something that satisfies
`HypocenterEventLike` structurally, which is the whole point of bridging with a
Protocol. When `domain.hypocenter` lands, these tests can be pointed at the real
type by changing this file alone.

It deliberately mirrors `domain.hypocenter.Hypocenter` **including its types** —
a `RecordType` enum for the record type, `Decimal` for every coordinate, depth
and magnitude. An earlier version of this file used `str` and `float`, which
made every writer test pass against values the domain never produces, and hid
both of the type mismatches the review found. A fake that is easier to satisfy
than the real thing tests nothing.

Field values used in the tests are decoded from real `h2023` and `h1919`
records quoted in `docs/jma-hypocenter-format.md`; each test says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class RecordType(Enum):
    """Mirrors `domain.hypocenter.RecordType`: field 1, who determined it.

    Redeclared rather than imported for the same reason the protocol is
    structural — `domain/` is not on this branch. `.value` is the published
    code and the only thing the writers read.
    """

    JMA = "J"
    USGS = "U"
    INTERNATIONAL = "I"


@dataclass(frozen=True, slots=True)
class SampleEvent:
    """A decoded hypocenter. Satisfies `HypocenterEventLike`.

    A frozen dataclass, so its attributes are read-only in the sense the
    protocol's `@property` declarations require, and so a test cannot mutate an
    event a writer already consumed.
    """

    record_type: RecordType
    origin_time: datetime
    latitude: Decimal
    longitude: Decimal
    second_is_known: bool = True
    latitude_minutes_are_known: bool = True
    longitude_minutes_are_known: bool = True
    depth_km: Decimal | None = None
    magnitude: Decimal | None = None
    magnitude_type: str | None = None
    magnitude_2: Decimal | None = None
    magnitude_type_2: str | None = None
    district: int | None = None
    region_number: int | None = None
    region_name: str | None = None
    station_count: int | None = None
