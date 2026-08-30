"""The export interactor, driven entirely through the in-memory port fakes.

No network, no filesystem. Every record line here is **verbatim from the
published catalog** (`h1919` and `h2023`), as CONTRIBUTING requires: a synthetic
96-byte line would let a column mistake in the test agree with a column mistake
in the code.

The counts these tests assert are derived from those same real lines, by
inspection of the fields quoted beside each constant, never from running the
code and copying what it printed.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from jmacat.domain.filters import UnknownAreaError
from jmacat.domain.hypocenter import Hypocenter, parse_record
from jmacat.usecase.errors import CatalogYearUnavailableError, EventWriterError
from jmacat.usecase.export import (
    MAX_REPORTED_REJECTIONS,
    ExportError,
    ExportRequest,
    OutputFormat,
    export,
)
from tests.fakes import (
    FailingEventWriter,
    InMemoryCatalogSource,
    InMemoryEventWriter,
    UnavailableYearCatalogSource,
)

# Real records, verbatim from the published `h1919` archive (1919-1950), each
# cited by its line number. Synthetic 96-byte lines are avoided deliberately: a
# column mistake invented in a test would agree with the same mistake in the
# code and prove nothing.
#
# Chosen so that one magnitude filter produces all three outcomes at once.
#
# Each is a single 96-column literal and therefore exceeds the line limit;
# `noqa: E501` is preferred to splitting it, because a record broken across
# two string literals can no longer be compared byte-for-byte against the
# archive by eye, which is the whole reason for quoting it verbatim.

#: h1919 line 38. M6.1, SE OFF TOKACHI; above every bound used here.
M61 = "J1919031219312449 049 413032 193 1441504 352  0     61J   5211  1 28SE OFF TOKACHI            9K"  # noqa: E501

#: h1919 line 408. M3.0, NW GUNMA PREF; sits exactly on the `minimum=3.0`
#: bound, which the closed range must keep.
M30 = "J1921011809505958 227 362422     1383157      0     30J   571   3 81NW GUNMA PREF             2S"  # noqa: E501

#: h1919 line 3346. M2.0, NORTHERN KYOTO PREF; below the bound, so an ordinary
#: comparison failure.
M20 = "J1927032408565221 004 353142 076 1351558 087 12     20J   151   5182NORTHERN KYOTO PREF       4K"  # noqa: E501

#: h1919 line 4. Magnitude columns 53-54 are blank: no magnitude was ever
#: determined. 11,621 of the 28,235 h1919 records look like this.
BLANK_MAGNITUDE = "J1919010518532883 087 372982 273 1383601 165  4           5711  4132MID NIIGATA PREF          5S"  # noqa: E501

#: h1919 line 125. M3.1 - the bound CONTRIBUTING names as the one a raw float
#: comparison gets wrong, where `Decimal("3.1") >= 3.1` is False.
M31 = "J1919071919042792 048 360326 414 1401658 289 72     31d   5211  3 87SOUTHERN IBARAKI PREF    10K"  # noqa: E501

#: h1919 line 284. 36.239N 137.080E, inside the approximate Ishikawa box.
#: Its region is TOYAMA GIFU BORDER REG rather than an Ishikawa name, which is
#: the documented limitation of a rectangle standing in for a prefecture; the
#: filter tests the coordinate, and so does this test.
INSIDE_ISHIKAWA = "J1920052903245705 078 361432 300 1370482 345  2     45J   5211  4142TOYAMA GIFU BORDER REG   14K"  # noqa: E501


def _writer() -> InMemoryEventWriter[Hypocenter]:
    return InMemoryEventWriter[Hypocenter]()


def _request(tmp_path: Path, **kwargs: object) -> ExportRequest:
    defaults: dict[str, object] = {
        "year": 1919,
        "destination": tmp_path / "events.parquet",
    }
    defaults.update(kwargs)
    return ExportRequest(**defaults)  # type: ignore[arg-type]


def test_every_record_of_an_unfiltered_year_is_written(tmp_path: Path) -> None:
    source = InMemoryCatalogSource({1919: [M61, M30, M20, BLANK_MAGNITUDE]})
    writer = _writer()

    result = export(_request(tmp_path), source=source, writer=writer)

    assert result.records_read == 4
    assert result.records_written == 4
    assert len(writer.events) == 4


def test_an_unfiltered_run_admits_the_record_with_no_magnitude(
    tmp_path: Path,
) -> None:
    """A filter that is not applied drops nothing, blank field or not.

    The counterpart to the exclusion tests below: the loss is caused by the
    filter, not by the record being incomplete.
    """
    source = InMemoryCatalogSource({1919: [BLANK_MAGNITUDE]})
    writer = _writer()

    result = export(_request(tmp_path), source=source, writer=writer)

    assert writer.events[0].magnitude is None
    assert result.records_written == 1
    assert result.records_excluded_for_a_missing_value == 0


def test_a_magnitude_bound_separates_the_two_reasons_a_record_is_dropped(
    tmp_path: Path,
) -> None:
    """The heart of issue #20.

    Of the four real records, `minimum=3.0` keeps M6.1 and M3.0 (the bound is
    inclusive), drops M2.0 for being too small, and drops the blank one for
    having no magnitude at all. The two rejections must not be reported as one
    number: they mean opposite things to a researcher.
    """
    source = InMemoryCatalogSource({1919: [M61, M30, M20, BLANK_MAGNITUDE]})
    writer = _writer()

    result = export(_request(tmp_path, min_magnitude=3.0), source=source, writer=writer)

    (magnitude,) = result.filter_outcomes
    assert magnitude.name == "magnitude"
    assert result.records_written == 2
    assert magnitude.excluded_by_comparison == 1
    assert magnitude.excluded_missing_value == 1


def test_the_missing_value_count_tracks_the_number_of_blank_records(
    tmp_path: Path,
) -> None:
    """Triangulation: the count is counted, not a constant that happens to fit.

    Two runs differing only in how many blank-magnitude records the catalog
    holds must report two different missing-value counts. A hardcoded 1, or a
    count that actually measures the comparison failures, fails here.
    """
    writer_one = _writer()
    writer_three = _writer()

    one = export(
        _request(tmp_path, min_magnitude=3.0),
        source=InMemoryCatalogSource({1919: [M61, BLANK_MAGNITUDE]}),
        writer=writer_one,
    )
    three = export(
        _request(tmp_path, min_magnitude=3.0),
        source=InMemoryCatalogSource(
            {1919: [M61, BLANK_MAGNITUDE, BLANK_MAGNITUDE, BLANK_MAGNITUDE]}
        ),
        writer=writer_three,
    )

    assert one.records_excluded_for_a_missing_value == 1
    assert three.records_excluded_for_a_missing_value == 3
    # The comparison count is held fixed across the pair, so the difference
    # above can only come from the missing-value attribution.
    assert one.filter_outcomes[0].excluded_by_comparison == 0
    assert three.filter_outcomes[0].excluded_by_comparison == 0


def test_a_bound_no_float_can_represent_still_keeps_the_record_on_it(
    tmp_path: Path,
) -> None:
    """`minimum=3.0` is one of the few bounds a raw float compares correctly.

    CONTRIBUTING records a sprint-2 measurement that passed only because it
    used 3.0. This is the same request at a bound where a float comparison
    fails — `Decimal("3.0") >= 3.1` reasoning breaks at 3.1 — so a future
    change that stopped normalising the bound would be caught here rather than
    silently dropping every record sitting exactly on it.
    """
    on_the_bound = parse_record(M31)
    assert on_the_bound.magnitude == Decimal("3.1")

    source = InMemoryCatalogSource({1919: [M31]})
    writer = _writer()

    result = export(_request(tmp_path, min_magnitude=3.1), source=source, writer=writer)

    assert result.records_written == 1


def test_a_line_that_cannot_be_parsed_is_counted_and_described(
    tmp_path: Path,
) -> None:
    """A malformed line must neither abort the year nor vanish from the report."""
    truncated = M61[:40]
    source = InMemoryCatalogSource({1919: [M61, truncated, M30]})
    writer = _writer()

    result = export(_request(tmp_path), source=source, writer=writer)

    assert result.records_read == 3
    assert result.records_written == 2
    assert result.records_rejected == 1
    assert result.rejections  # the reason, not only the count
    assert "40" in result.rejections[0]


def test_the_counts_account_for_every_record_exactly_once(
    tmp_path: Path,
) -> None:
    """read == written + rejected + excluded, with all three non-zero.

    An identity that held only because two of its terms were zero would prove
    nothing, so this run produces a parse failure, both kinds of exclusion and
    a written record at the same time.
    """
    source = InMemoryCatalogSource({1919: [M61, M20, BLANK_MAGNITUDE, M61[:40]]})
    writer = _writer()

    result = export(_request(tmp_path, min_magnitude=3.0), source=source, writer=writer)

    assert result.records_written == 1
    assert result.records_rejected == 1
    assert result.records_excluded == 2
    assert result.reconciles()


def test_an_unavailable_year_reaches_the_caller(tmp_path: Path) -> None:
    """The 404 must surface here, not become an empty output file."""
    source = UnavailableYearCatalogSource()
    writer = _writer()

    with pytest.raises(CatalogYearUnavailableError) as raised:
        export(_request(tmp_path, year=2024), source=source, writer=writer)

    assert raised.value.year == 2024
    assert not writer.events


def test_an_unavailable_year_fails_before_anything_is_written(
    tmp_path: Path,
) -> None:
    """Availability is resolved at the call, so no partial output is produced."""
    writer = _writer()

    with pytest.raises(CatalogYearUnavailableError):
        export(
            _request(tmp_path, year=2024),
            source=UnavailableYearCatalogSource(),
            writer=writer,
        )

    assert writer.events == []


def test_a_destination_that_rejects_every_write_reaches_the_caller(
    tmp_path: Path,
) -> None:
    source = InMemoryCatalogSource({1919: [M61]})
    writer: FailingEventWriter[Hypocenter] = FailingEventWriter()

    with pytest.raises(EventWriterError):
        export(_request(tmp_path), source=source, writer=writer)


def test_an_unknown_area_fails_before_the_catalog_is_fetched(
    tmp_path: Path,
) -> None:
    """A misspelt area must not cost a 25 MB download, nor return zero events."""
    source = InMemoryCatalogSource({1919: [M61]})
    writer = _writer()

    with pytest.raises(UnknownAreaError) as raised:
        export(_request(tmp_path, area="ishikaw"), source=source, writer=writer)

    assert "ishikawa" in str(raised.value)
    assert source.requested_years == []


def test_a_known_area_selects_by_the_epicentre(tmp_path: Path) -> None:
    """The Ishikawa box admits the Noto record and rejects the Gifu one.

    Both are real h1919 lines; their coordinates are in the constants above.
    """
    source = InMemoryCatalogSource({1919: [INSIDE_ISHIKAWA, M20]})
    writer = _writer()

    result = export(_request(tmp_path, area="ishikawa"), source=source, writer=writer)

    assert result.records_written == 1
    assert writer.events[0].region_name is not None
    (area,) = result.filter_outcomes
    assert area.excluded_by_comparison == 1
    # A coordinate is never blank on a parsed record, so an area filter can
    # exclude nothing for absence.
    assert area.excluded_missing_value == 0


def test_the_catalog_is_streamed_rather_than_materialised(
    tmp_path: Path,
) -> None:
    """The interactor must not list the year before writing the first row.

    `InMemoryEventWriter.write_many` iterates its argument; a `list(...)` in
    the interactor would still pass every count assertion above, so laziness
    is asserted directly, by observing that the source has yielded nothing at
    the moment the interactor hands the writer its iterator.
    """
    observed: list[int] = []
    source = InMemoryCatalogSource({1919: [M61, M30, M20]})

    class ObservingWriter(InMemoryEventWriter[Hypocenter]):
        def write_many(self, events: object) -> None:
            observed.append(source.lines_yielded)
            super().write_many(events)  # type: ignore[arg-type]

    writer = ObservingWriter()
    export(_request(tmp_path), source=source, writer=writer)

    assert observed == [0]
    assert source.lines_yielded == 3


def test_the_result_carries_back_what_was_asked_for(tmp_path: Path) -> None:
    """The CLI formats its report off the result alone, so it must be complete."""
    destination = tmp_path / "events.csv"
    source = InMemoryCatalogSource({1919: [M61]})

    result = export(
        ExportRequest(
            year=1919, destination=destination, output_format=OutputFormat.CSV
        ),
        source=source,
        writer=_writer(),
    )

    assert result.year == 1919
    assert result.destination == destination
    assert result.output_format is OutputFormat.CSV


def test_the_interactor_does_not_close_the_writer_it_was_given(
    tmp_path: Path,
) -> None:
    """Lifetime belongs to the caller's `with`, which is what discards a partial
    file on the error path. Closing here would publish the destination before
    the caller's cleanup had a say."""
    writer = _writer()
    export(
        _request(tmp_path),
        source=InMemoryCatalogSource({1919: [M61]}),
        writer=writer,
    )

    assert not writer.closed


# -- multi-filter attribution: the counts must describe the user's query -----

#: h1919 line 9162. 37.075N 137.024E, inside the approximate Ishikawa box, and
#: magnitude columns 53-54 are blank: NOTO PENINSULA REGION, no magnitude ever
#: determined. This is the record that makes a multi-filter run's missing-value
#: count meaningful — it is missing *inside* the area the user asked about.
INSIDE_ISHIKAWA_BLANK_MAGNITUDE = "J1933092113100852 033 370452 123 1370145 226 20           1312  4135NOTO PENINSULA REGION     9K"  # noqa: E501


def test_a_geographic_filter_runs_before_the_value_filters(tmp_path: Path) -> None:
    """The documented ordering contract, asserted at the boundary that fixes it.

    `filters()` returns the filters in application order, and the area filter
    must come first so that every later outcome counts records *inside the
    user's area*. This is a deliberate part of the contract, not an artefact of
    how `filters()` happens to be written; see its docstring.
    """
    request = ExportRequest(
        year=1919,
        destination=tmp_path / "events.parquet",
        area="ishikawa",
        min_magnitude=3.0,
        min_depth_km=0,
    )

    assert [spec.name for spec in request.filters()] == ["area", "magnitude", "depth"]


def test_a_later_filters_counts_cover_only_what_reached_it(tmp_path: Path) -> None:
    """The blocking defect of PR #25, at the interactor.

    Five real records. Two are inside the Ishikawa box (the M4.5 Toyama/Gifu
    border record and the blank-magnitude Noto record); three are elsewhere in
    Japan (M6.1 off Tokachi, M2.0 northern Kyoto, blank-magnitude mid Niigata).

    With `--area ishikawa --min-magnitude 3.0` the honest report of the
    magnitude filter is over the **two** records that reached it: one selected,
    one missing. The national figures — two blank magnitudes, one below the
    bound — describe Japan, not the researcher's area, and must not be what the
    magnitude outcome carries.
    """
    source = InMemoryCatalogSource(
        {
            1919: [
                M61,
                INSIDE_ISHIKAWA,
                M20,
                BLANK_MAGNITUDE,
                INSIDE_ISHIKAWA_BLANK_MAGNITUDE,
            ]
        }
    )

    result = export(
        _request(tmp_path, area="ishikawa", min_magnitude=3.0),
        source=source,
        writer=_writer(),
    )

    area, magnitude = result.filter_outcomes
    assert area.name == "area"
    assert area.excluded_by_comparison == 3
    assert magnitude.name == "magnitude"
    # Of the two records inside the box, one has no magnitude and none falls
    # below 3.0. The national counts (2 blank, 1 below) must not appear here.
    assert magnitude.excluded_missing_value == 1
    assert magnitude.excluded_by_comparison == 0
    assert result.records_written == 1


def test_each_outcome_carries_the_number_of_records_that_reached_it(
    tmp_path: Path,
) -> None:
    """The denominator a percentage must be computed against.

    A missing-value count is only interpretable against the records that filter
    actually judged. The first filter sees every parsed record; each later one
    sees what its predecessors left.
    """
    source = InMemoryCatalogSource(
        {
            1919: [
                M61,
                INSIDE_ISHIKAWA,
                M20,
                BLANK_MAGNITUDE,
                INSIDE_ISHIKAWA_BLANK_MAGNITUDE,
            ]
        }
    )

    result = export(
        _request(tmp_path, area="ishikawa", min_magnitude=3.0),
        source=source,
        writer=_writer(),
    )

    area, magnitude = result.filter_outcomes
    assert area.records_reaching == 5
    assert magnitude.records_reaching == 2
    assert magnitude.missing_share_of_those_reaching == pytest.approx(50.0)


def test_an_unparsed_line_is_not_counted_as_reaching_a_filter(
    tmp_path: Path,
) -> None:
    """`records_reaching` is a filter denominator, not a line count.

    A line that never parsed was never judged by any filter, so including it
    would understate the share of missing values in exactly the direction that
    hides the problem.
    """
    source = InMemoryCatalogSource({1919: ["too short to be a record", M61, M20]})

    result = export(
        _request(tmp_path, min_magnitude=3.0), source=source, writer=_writer()
    )

    assert result.records_rejected == 1
    (magnitude,) = result.filter_outcomes
    assert magnitude.records_reaching == 2


def test_a_bound_pair_that_can_admit_nothing_is_refused(tmp_path: Path) -> None:
    """`--min-magnitude 5.0 --max-magnitude 3.0` selects nothing, always.

    An empty result file is indistinguishable from a legitimate one, so this
    fails loudly before anything is fetched rather than exiting zero on a
    header-only file. CONTRIBUTING: "Prefer failing loudly over returning a
    value that might be wrong."
    """
    source = InMemoryCatalogSource({1919: [M61]})

    with pytest.raises(ExportError) as raised:
        export(
            _request(tmp_path, min_magnitude=5.0, max_magnitude=3.0),
            source=source,
            writer=_writer(),
        )

    assert "magnitude" in str(raised.value)
    assert source.requested_years == []


def test_a_depth_bound_pair_that_can_admit_nothing_is_refused(
    tmp_path: Path,
) -> None:
    """Triangulation: the check is over the bound pair, not hardcoded to magnitude."""
    source = InMemoryCatalogSource({1919: [M61]})

    with pytest.raises(ExportError) as raised:
        export(
            _request(tmp_path, min_depth_km=700, max_depth_km=10),
            source=source,
            writer=_writer(),
        )

    assert "depth" in str(raised.value)
    assert source.requested_years == []


def test_equal_bounds_are_accepted_because_a_closed_range_admits_them(
    tmp_path: Path,
) -> None:
    """The complement, so the guard cannot be `minimum >= maximum`.

    Ranges are closed, so `min == max` selects exactly the records on that
    value. M6.1 off Tokachi is a real such record.
    """
    source = InMemoryCatalogSource({1919: [M61, M20]})

    result = export(
        _request(tmp_path, min_magnitude=6.1, max_magnitude=6.1),
        source=source,
        writer=_writer(),
    )

    assert result.records_written == 1


def test_a_rejection_message_says_which_line_was_bad(tmp_path: Path) -> None:
    """A count tells a user how much was lost; a position tells them where.

    Ten identical "must be 96 bytes, got 40" messages with no positions cannot
    be acted on: the archive has 28,235 lines and the user has no way to find
    the offending ones. The line number is the stream's ordinal, counted from
    one as a text editor does, and it is added here because the parser sees one
    record and has no idea where it came from.
    """
    source = InMemoryCatalogSource({1919: [M61, "too short", M20, "also too short"]})

    result = export(_request(tmp_path), source=source, writer=_writer())

    assert result.records_rejected == 2
    first, second = result.rejections
    assert first.startswith("line 2: ")
    assert second.startswith("line 4: ")
    # The parser's own explanation survives, rather than being replaced.
    assert "96 bytes" in first


def test_only_the_first_few_rejections_are_kept_but_all_are_counted(
    tmp_path: Path,
) -> None:
    """A wholly corrupt archive must not be held in memory line by line.

    The cap is on the messages, never on the count, so the report can still
    say how much was lost.
    """
    source = InMemoryCatalogSource({1919: ["bad"] * (MAX_REPORTED_REJECTIONS + 5)})

    result = export(_request(tmp_path), source=source, writer=_writer())

    assert result.records_rejected == MAX_REPORTED_REJECTIONS + 5
    assert len(result.rejections) == MAX_REPORTED_REJECTIONS
    # The kept ones are the first, so their line numbers run from one.
    assert result.rejections[0].startswith("line 1: ")
    assert result.rejections[-1].startswith(f"line {MAX_REPORTED_REJECTIONS}: ")
