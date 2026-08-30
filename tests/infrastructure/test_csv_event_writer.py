"""`CsvEventWriter`: round-trip, null representation and float formatting.

Numeric expectations come from records quoted in
`docs/jma-hypocenter-format.md`; the source is named in each docstring.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.event_schema import column_names
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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_the_header_row_is_the_schema_column_names_in_order(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    with CsvEventWriter(path):
        pass
    with path.open(encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle)) == column_names()


def test_an_event_round_trips_through_csv(tmp_path: Path) -> None:
    """Example A: every written value reads back as the value written."""
    path = tmp_path / "out.csv"
    with CsvEventWriter(path) as writer:
        writer.write(example_a())

    (row,) = read_rows(path)
    assert row["record_type"] == "J"
    assert row["origin_time_jst"] == "2023-01-01T00:08:01.500+09:00"
    assert row["origin_time_utc"] == "2022-12-31T15:08:01.500Z"
    assert float(row["latitude_deg"]) == 35.676500
    assert float(row["longitude_deg"]) == 140.654500
    assert float(row["depth_km"]) == 50.0
    assert float(row["magnitude1"]) == 0.3
    assert row["region_name"] == "NEAR CHOSHI CITY"
    assert int(row["station_count"]) == 9


def test_the_utc_column_is_the_jst_column_shifted_by_nine_hours(
    tmp_path: Path,
) -> None:
    """Format document, *Time zone*: JST = UTC + 9 h."""
    path = tmp_path / "out.csv"
    with CsvEventWriter(path) as writer:
        writer.write(example_a())

    (row,) = read_rows(path)
    jst = datetime.fromisoformat(row["origin_time_jst"])
    utc = datetime.fromisoformat(row["origin_time_utc"].replace("Z", "+00:00"))
    assert jst == utc
    assert jst.utcoffset() == timedelta(hours=9)
    assert utc.utcoffset() == timedelta(0)


def test_a_missing_magnitude_is_empty_and_not_zero(tmp_path: Path) -> None:
    """*Traps* 6: a blank magnitude must not read back as M0.0.

    9,973 records in h2023 carry no magnitude at all.
    """
    path = tmp_path / "out.csv"
    absent = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        magnitude1=None,
    )
    measured_zero = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        magnitude1=0.0,
    )
    with CsvEventWriter(path) as writer:
        writer.write_many([absent, measured_zero])

    missing, zero = read_rows(path)
    assert missing["magnitude1"] == ""
    assert zero["magnitude1"] == "0.0"
    assert missing["magnitude1"] != zero["magnitude1"]


def test_an_empty_string_and_a_null_both_become_an_empty_csv_field(
    tmp_path: Path,
) -> None:
    """The documented CSV limitation, pinned so it cannot change unnoticed.

    CSV has one empty field and two things to say with it. `csv.QUOTE_NOTNULL`
    would keep them apart, but it needs Python 3.12 and the project baseline is
    3.11, so the writer normalises an empty string to a null and says so. That
    is lossless for this catalog: no field of the 96-byte record can carry a
    zero-length string that means something other than "blank". A blank
    24-byte region name (553 records in h1919) *is* an absent name.

    The distinction that actually matters — a null against a numeric zero — is
    unaffected and covered by the test above. Parquet keeps both apart.
    """
    path = tmp_path / "out.csv"
    null_name = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        region_name=None,
    )
    empty_name = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, tzinfo=JST),
        latitude_deg=35.0,
        longitude_deg=140.0,
        region_name="",
    )
    with CsvEventWriter(path) as writer:
        writer.write_many([null_name, empty_name])

    from_null, from_empty = read_rows(path)
    assert from_null["region_name"] == ""
    assert from_empty["region_name"] == ""
    # No stray quoting: both are a genuinely empty field, not the text `""`.
    lines = path.read_text(encoding="utf-8").splitlines()
    assert '"' not in lines[1]
    assert '"' not in lines[2]


def test_a_coordinate_keeps_full_double_precision(tmp_path: Path) -> None:
    """Default `str()` on a float is not enough for a coordinate.

    35 deg 40.59 min is 35.6765 exactly, but a converted longitude such as
    142 deg 55.91 min (Example B) is 142.93183333333333..., whose nearest
    double must survive the text round trip byte for byte. Losing the last
    digits moves the epicentre; `repr` is the shortest string that reads back
    as the identical double.
    """
    path = tmp_path / "out.csv"
    # Example B: J2023010100102271 ... 41 deg 10.23 min, 142 deg 55.91 min.
    longitude = 142 + 55.91 / 60
    latitude = 41 + 10.23 / 60
    with CsvEventWriter(path) as writer:
        writer.write(
            SampleEvent(
                record_type="J",
                origin_time=datetime(2023, 1, 1, tzinfo=JST),
                latitude_deg=latitude,
                longitude_deg=longitude,
                depth_km=26.45,
            )
        )

    (row,) = read_rows(path)
    assert float(row["longitude_deg"]) == longitude
    assert float(row["latitude_deg"]) == latitude


def test_writing_after_close_raises(tmp_path: Path) -> None:
    from jmacat.usecase.errors import EventWriterError

    writer = CsvEventWriter(tmp_path / "out.csv")
    writer.close()
    try:
        writer.write(example_a())
    except EventWriterError:
        return
    raise AssertionError("write after close must raise EventWriterError")


def test_close_is_idempotent(tmp_path: Path) -> None:
    writer = CsvEventWriter(tmp_path / "out.csv")
    writer.close()
    writer.close()


def test_a_naive_origin_time_is_rejected(tmp_path: Path) -> None:
    """The one thing this writer must never do is guess a time zone."""
    from jmacat.usecase.errors import EventWriterError

    path = tmp_path / "out.csv"
    naive = SampleEvent(
        record_type="J",
        origin_time=datetime(2023, 1, 1, 0, 8, 1),
        latitude_deg=35.0,
        longitude_deg=140.0,
    )
    try:
        with CsvEventWriter(path) as writer:
            writer.write(naive)
    except EventWriterError as error:
        assert "origin_time" in str(error)
        return
    raise AssertionError("a naive origin time must be rejected, not assumed")


def test_an_event_whose_origin_time_is_already_utc_is_written_correctly(
    tmp_path: Path,
) -> None:
    """The writer converts; it does not assume the domain hands it JST.

    Example G: the 2023 Turkey M7.8, 2023-02-06 10:17:34.34 JST, which the
    format document cross-checks against USGS as 2023-02-06 01:17:34 UTC.
    """
    path = tmp_path / "out.csv"
    with CsvEventWriter(path) as writer:
        writer.write(
            SampleEvent(
                record_type="U",
                origin_time=datetime(2023, 2, 6, 1, 17, 34, 340_000, tzinfo=UTC),
                latitude_deg=37.174,
                longitude_deg=37.032,
            )
        )

    (row,) = read_rows(path)
    assert row["origin_time_utc"] == "2023-02-06T01:17:34.340Z"
    assert row["origin_time_jst"] == "2023-02-06T10:17:34.340+09:00"
