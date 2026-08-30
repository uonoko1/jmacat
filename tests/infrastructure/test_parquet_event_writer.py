"""`ParquetEventWriter`: round-trip, nulls, time zone and row-group behaviour.

Numeric expectations come from records quoted in
`docs/jma-hypocenter-format.md`; the source is named in each docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from jmacat.usecase.errors import EventWriterError
from tests.infrastructure.events import SampleEvent

JST = timezone(timedelta(hours=9), "JST")


def example_a() -> SampleEvent:
    """Example A of the format document, decoded.

        J2023010100080150 012 354059 100 1403927 136 50     03v   721   3110NEAR CHOSHI CITY          9A

    2023-01-01 00:08:01.50 JST, 35.676500 degN, 140.654500 degE, 50 km, M0.3.
    """  # noqa: E501
    return SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, 0, 8, 1, 500_000, tzinfo=JST),
        origin_time_error_s=0.12,
        latitude_deg=35.676500,
        latitude_error_min=1.00,
        longitude_deg=140.654500,
        longitude_error_min=1.36,
        depth_km=50.0,
        magnitude1=0.3,
        magnitude1_type="v",
        travel_time_table="7",
        location_precision="2",
        subsidiary_information="1",
        district_number=3,
        region_number=110,
        region_name="NEAR CHOSHI CITY",
        station_count=9,
        determination_flag="A",
    )


def read_rows(path: Path) -> list[dict[str, Any]]:
    # pyarrow has no stubs, so to_pylist() is Any; named here once so no test
    # body has to carry the annotation.
    rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows


def test_an_event_round_trips_through_parquet(tmp_path: Path) -> None:
    """Example A: every written value reads back as the value written."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write(example_a())

    (row,) = read_rows(path)
    assert row["record_type"] == "J"
    assert row["latitude_deg"] == 35.676500
    assert row["longitude_deg"] == 140.654500
    assert row["depth_km"] == 50.0
    assert row["magnitude1"] == pytest.approx(0.3)
    assert row["magnitude1_type"] == "v"
    assert row["region_name"] == "NEAR CHOSHI CITY"
    assert row["station_count"] == 9
    assert row["district_number"] == 3
    assert row["region_number"] == 110
    assert row["determination_flag"] == "A"


def test_a_coordinate_is_stored_as_float64_and_is_bit_identical(
    tmp_path: Path,
) -> None:
    """Example B: 142 deg 55.91 min has no exact decimal, so no rounding is safe."""
    path = tmp_path / "out.parquet"
    longitude = 142 + 55.91 / 60
    latitude = 41 + 10.23 / 60
    with ParquetEventWriter(path) as writer:
        writer.write(
            SampleEvent(
                record_type="J",
                origin_time=datetime(2023, 1, 1, tzinfo=JST),
                latitude_deg=latitude,
                longitude_deg=longitude,
            )
        )

    table = pq.read_table(path)
    assert str(table.schema.field("latitude_deg").type) == "double"
    (row,) = table.to_pylist()
    assert row["longitude_deg"] == longitude
    assert row["latitude_deg"] == latitude


def test_both_timestamp_columns_are_typed_with_their_time_zone(
    tmp_path: Path,
) -> None:
    """The type itself carries the zone, so nothing downstream can be naive."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write(example_a())

    schema = pq.read_table(path).schema
    assert schema.field("origin_time_utc").type.tz == "UTC"
    assert schema.field("origin_time_jst").type.tz == "+09:00"
    assert schema.field("origin_time_utc").type.unit == "ms"


def test_the_two_timestamp_columns_are_the_same_instant(tmp_path: Path) -> None:
    """Format document, *Time zone*: JST = UTC + 9 h, one instant, two calendars."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write(example_a())

    (row,) = read_rows(path)
    assert row["origin_time_utc"] == row["origin_time_jst"]
    assert row["origin_time_jst"].utcoffset() == timedelta(hours=9)
    assert row["origin_time_utc"].utcoffset() == timedelta(0)
    # 2023-01-01 00:08:01.50 JST is 2022-12-31 15:08:01.50 UTC.
    assert row["origin_time_utc"].astimezone(UTC) == datetime(
        2022, 12, 31, 15, 8, 1, 500_000, tzinfo=UTC
    )


def test_the_units_travel_inside_the_file(tmp_path: Path) -> None:
    """A Parquet passed on without the README still states its own units."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write(example_a())

    schema = pq.read_table(path).schema
    assert schema.field("latitude_deg").metadata[b"unit"] == b"decimal degrees"
    assert schema.field("depth_km").metadata[b"unit"].startswith(b"kilometres")


def test_a_missing_value_is_null_and_not_zero(tmp_path: Path) -> None:
    """*Traps* 6: null and 0.0 are different measurements and must stay apart.

    9,973 records in h2023 carry no magnitude, and depth is genuinely 0 km for
    the shallowest events, so a null-to-zero collapse would be invisible.
    """
    path = tmp_path / "out.parquet"
    absent = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        depth_km=None,
        magnitude1=None,
        station_count=None,
    )
    measured_zero = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        depth_km=0.0,
        magnitude1=0.0,
        station_count=0,
    )
    with ParquetEventWriter(path) as writer:
        writer.write_many([absent, measured_zero])

    missing, zero = read_rows(path)
    assert missing["depth_km"] is None
    assert missing["magnitude1"] is None
    assert missing["station_count"] is None
    assert zero["depth_km"] == 0.0
    assert zero["magnitude1"] == 0.0
    assert zero["station_count"] == 0


def test_a_null_string_stays_distinct_from_an_empty_string(tmp_path: Path) -> None:
    """Parquet can express the distinction CSV cannot, so it must not lose it."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write_many(
            [
                SampleEvent(
                    record_type="J",
                    origin_time=datetime(2023, 1, 1, tzinfo=JST),
                    latitude_deg=35.0,
                    longitude_deg=140.0,
                    region_name=None,
                ),
                SampleEvent(
                    record_type="J",
                    origin_time=datetime(2023, 1, 1, tzinfo=JST),
                    latitude_deg=35.0,
                    longitude_deg=140.0,
                    region_name="",
                ),
            ]
        )

    from_null, from_empty = read_rows(path)
    assert from_null["region_name"] is None
    assert from_empty["region_name"] == ""


def test_a_negative_magnitude_survives(tmp_path: Path) -> None:
    """Example C: `-6` is M-0.6, and 24,882 records of h2023 are negative."""
    path = tmp_path / "out.parquet"
    with ParquetEventWriter(path) as writer:
        writer.write(
            SampleEvent(
                record_type="J",
                origin_time=datetime(2023, 1, 1, tzinfo=JST),
                latitude_deg=34.0,
                longitude_deg=133.0,
                magnitude1=-0.6,
            )
        )

    (row,) = read_rows(path)
    assert row["magnitude1"] == pytest.approx(-0.6)
    assert row["magnitude1"] < 0


def test_a_southern_latitude_stays_negative(tmp_path: Path) -> None:
    """The `U` record of issue #3: `- 70352` is about -7.0587 deg, not +7."""
    path = tmp_path / "out.parquet"
    latitude = -(7 + 3.52 / 60)
    with ParquetEventWriter(path) as writer:
        writer.write(
            SampleEvent(
                record_type="U",
                origin_time=datetime(2023, 1, 10, 2, 47, 35, 40_000, tzinfo=JST),
                latitude_deg=latitude,
                longitude_deg=130 + 0.54 / 60,
            )
        )

    (row,) = read_rows(path)
    assert row["latitude_deg"] == latitude
    assert row["latitude_deg"] < 0


def test_writing_after_close_raises(tmp_path: Path) -> None:
    writer = ParquetEventWriter(tmp_path / "out.parquet")
    writer.close()
    with pytest.raises(EventWriterError):
        writer.write(example_a())


def test_close_is_idempotent(tmp_path: Path) -> None:
    writer = ParquetEventWriter(tmp_path / "out.parquet")
    writer.close()
    writer.close()


def test_a_naive_origin_time_is_rejected(tmp_path: Path) -> None:
    """The writer never guesses a zone; see docs *Time zone — JST, not UTC*."""
    naive = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, 0, 8, 1),
        latitude_deg=35.0,
        longitude_deg=140.0,
    )
    with pytest.raises(EventWriterError, match="origin_time"):
        with ParquetEventWriter(tmp_path / "out.parquet") as writer:
            writer.write(naive)


def test_a_batch_size_below_one_is_rejected(tmp_path: Path) -> None:
    """A batch size of 0 would never flush, so it must fail at construction."""
    with pytest.raises(EventWriterError, match="batch_size"):
        ParquetEventWriter(tmp_path / "out.parquet", batch_size=0)
