"""A stand-in hypocenter event for the writer tests.

The domain value object is issues #3/#4 and is not on `main` yet. This frozen
dataclass is *not* a substitute for it and must not grow any conversion logic:
it exists only to give the writer tests something that satisfies
`HypocenterEventLike` structurally, which is the whole point of bridging with a
Protocol. When the domain type lands, these tests can be pointed at it by
changing this file alone.

Field values used in the tests are decoded from real `h2023` and `h1919`
records quoted in `docs/jma-hypocenter-format.md`; each test says which.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SampleEvent:
    """A converted hypocenter event. Satisfies `HypocenterEventLike`.

    A frozen dataclass, so its attributes are read-only in the sense the
    protocol's `@property` declarations require, and so a test cannot mutate an
    event a writer already consumed.
    """

    record_type: str
    origin_time: datetime
    latitude_deg: float
    longitude_deg: float
    origin_time_error_s: float | None = None
    latitude_error_min: float | None = None
    longitude_error_min: float | None = None
    depth_km: float | None = None
    depth_error_km: float | None = None
    magnitude1: float | None = None
    magnitude1_type: str | None = None
    magnitude2: float | None = None
    magnitude2_type: str | None = None
    travel_time_table: str | None = None
    location_precision: str | None = None
    subsidiary_information: str | None = None
    maximum_intensity: str | None = None
    damage_class: str | None = None
    tsunami_class: str | None = None
    district_number: int | None = None
    region_number: int | None = None
    region_name: str | None = None
    station_count: int | None = None
    determination_flag: str | None = None
