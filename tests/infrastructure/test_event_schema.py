"""The output column schema: names, order, types, units and null handling.

The schema is the contract a researcher joins against, so it is pinned here
rather than left implicit in whichever writer ran. Every expectation below is
traceable to `docs/jma-hypocenter-format.md` (the field table and the *Time
zone* section) — no value is invented.
"""

from __future__ import annotations

from jmacat.infrastructure.event_schema import COLUMNS, column_names


def test_the_schema_is_a_fixed_ordered_list_of_columns() -> None:
    """Column order is part of the contract: CSV has no other way to say it."""
    assert column_names() == [
        "record_type",
        "origin_time_utc",
        "origin_time_jst",
        "second_is_known",
        "latitude_deg",
        "latitude_minutes_are_known",
        "longitude_deg",
        "longitude_minutes_are_known",
        "depth_km",
        "magnitude",
        "magnitude_type",
        "magnitude_2",
        "magnitude_type_2",
        "district",
        "region_number",
        "region_name",
        "station_count",
    ]


def test_every_column_documents_a_unit_and_a_null_meaning() -> None:
    """A column with no documented unit is how a hundredfold error ships."""
    for column in COLUMNS:
        assert column.unit, f"{column.name} has no unit"
        assert column.null_meaning, f"{column.name} has no null meaning"


def test_coordinates_are_float64_decimal_degrees() -> None:
    """Traps 1 and 2: decimal degrees, signed, not degrees-and-minutes."""
    by_name = {column.name: column for column in COLUMNS}
    for name in ("latitude_deg", "longitude_deg"):
        assert by_name[name].arrow_type_name == "double"
        assert by_name[name].unit == "decimal degrees"


def test_both_origin_time_columns_carry_an_explicit_time_zone() -> None:
    """A naive timestamp is unacceptable; see docs *Time zone — JST, not UTC*."""
    by_name = {column.name: column for column in COLUMNS}
    assert by_name["origin_time_utc"].arrow_type_name == "timestamp[ms, tz=UTC]"
    assert by_name["origin_time_jst"].arrow_type_name == "timestamp[ms, tz=+09:00]"


def test_the_schema_exposes_only_fields_the_parser_decodes() -> None:
    """No column is always null, and the count is pinned so it cannot creep.

    An always-null column is worse than an absent one: a reader sees
    `maximum_intensity` in the schema, finds it empty on every row, and
    concludes no event was ever felt. The eleven undecoded record fields are
    therefore absent rather than declared, and their eventual return is an
    additive change — a new column at the end of the table.
    """
    assert len(COLUMNS) == 17
    undecoded = {
        "origin_time_error_s",
        "latitude_error_min",
        "longitude_error_min",
        "depth_error_km",
        "travel_time_table",
        "location_precision",
        "subsidiary_information",
        "maximum_intensity",
        "damage_class",
        "tsunami_class",
        "determination_flag",
    }
    assert undecoded.isdisjoint(column_names())
