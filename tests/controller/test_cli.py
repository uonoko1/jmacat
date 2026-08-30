"""The `jmacat` command line, driven through typer's runner.

The catalog source is substituted for the in-memory fake, so these tests touch
no network. The destination is a real `tmp_path`, because a partial-output
guarantee is about the filesystem and cannot be tested against a fake.
"""

from __future__ import annotations

import csv
import inspect
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import jmacat.controller.cli as cli
from jmacat.controller.cli import app, build_writer, fetch, run_fetch
from jmacat.domain.hypocenter import Hypocenter
from jmacat.usecase.export import ExportRequest, ExportResult, OutputFormat
from jmacat.usecase.ports import CatalogSource, EventWriter
from tests.fakes import InMemoryCatalogSource, UnavailableYearCatalogSource

#: h1919 line 38 (M6.1, SE OFF TOKACHI) and line 3346 (M2.0, NORTHERN KYOTO
#: PREF), and line 4, whose magnitude columns are blank. Verbatim; see
#: tests/usecase/test_export.py for the provenance of each.
M61 = "J1919031219312449 049 413032 193 1441504 352  0     61J   5211  1 28SE OFF TOKACHI            9K"  # noqa: E501
M20 = "J1927032408565221 004 353142 076 1351558 087 12     20J   151   5182NORTHERN KYOTO PREF       4K"  # noqa: E501
BLANK_MAGNITUDE = "J1919010518532883 087 372982 273 1383601 165  4           5711  4132MID NIIGATA PREF          5S"  # noqa: E501

runner = CliRunner()


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> InMemoryCatalogSource:
    """Replace the CLI's concrete adapter with the in-memory fake.

    The CLI is the one place wiring belongs, so the seam is the factory it
    calls rather than a parameter threaded through every command.
    """
    source = InMemoryCatalogSource({1919: [M61, M20, BLANK_MAGNITUDE]})
    monkeypatch.setattr("jmacat.controller.cli.build_source", lambda **kwargs: source)
    return source


def test_a_successful_run_writes_the_destination_and_exits_zero(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    destination = tmp_path / "events.csv"

    result = runner.invoke(
        app,
        ["fetch", "--year", "1919", "--output", str(destination), "--format", "csv"],
    )

    assert result.exit_code == 0, result.output
    assert destination.exists()
    with destination.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3


def test_the_report_names_all_three_counts_separately(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    """Issue #20 at the surface a researcher actually reads.

    With `--min-magnitude 3.0` over these three records: M6.1 is selected, M2.0
    fails the comparison, and the blank one is dropped for having no magnitude.
    The output must let those three be told apart.
    """
    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "events.csv"),
            "--format",
            "csv",
            "--min-magnitude",
            "3.0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "1 selected after filtering" in result.output
    assert "1 excluded for a missing magnitude" in result.output
    assert "1 excluded by magnitude" in result.output


def test_the_missing_value_line_is_absent_when_an_active_filter_drops_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The complement of the test above, so the line cannot be unconditional.

    The filter must be **active** here, not simply absent: with no filter there
    are no outcomes at all, so a report that printed the missing-value line
    unconditionally would still say nothing and the test would pass for a
    reason unrelated to what it checks. (It did, until this was fixed.) So the
    catalog holds only records that *have* a magnitude, `--min-magnitude` is
    applied, and the line must still not appear.
    """
    monkeypatch.setattr(
        "jmacat.controller.cli.build_source",
        lambda **kwargs: InMemoryCatalogSource({1919: [M61, M20]}),
    )

    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "e.csv"),
            "--format",
            "csv",
            "--min-magnitude",
            "3.0",
        ],
    )

    assert result.exit_code == 0, result.output
    # The filter ran and rejected M2.0 by comparison ...
    assert "1 excluded by magnitude" in result.output
    # ... but nothing for absence, so that line must be absent too.
    assert "missing magnitude" not in result.output


def test_a_run_with_no_filter_reports_no_filter_lines(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    """An unfiltered run drops nothing, so it claims nothing about exclusions."""
    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "e.csv"),
            "--format",
            "csv",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "excluded" not in result.output


def test_an_unavailable_year_is_a_clean_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`h2024.zip` 404s today. The user must get the publication-lag message."""
    monkeypatch.setattr(
        "jmacat.controller.cli.build_source",
        lambda **kwargs: UnavailableYearCatalogSource(),
    )
    destination = tmp_path / "events.parquet"

    result = runner.invoke(
        app, ["fetch", "--year", "2024", "--output", str(destination)]
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "2024" in result.output
    assert not destination.exists()


def test_an_unavailable_year_does_not_suggest_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`retryable` is an attribute on the error; the CLI reads it.

    A 404 is not retryable, so the advice to try again must not appear. This is
    the pair to the retryable case below, which is what stops the CLI from
    hardcoding either answer.
    """
    monkeypatch.setattr(
        "jmacat.controller.cli.build_source",
        lambda **kwargs: UnavailableYearCatalogSource(),
    )

    result = runner.invoke(
        app, ["fetch", "--year", "2024", "--output", str(tmp_path / "e.parquet")]
    )

    assert "try again" not in result.output.lower()


def test_a_retryable_failure_is_reported_as_worth_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is `CatalogRetrievalError`, whose `retryable` is True."""
    from jmacat.usecase.errors import CatalogRetrievalError

    class TimingOutSource:
        def record_lines(self, year: int) -> Iterator[str]:
            raise CatalogRetrievalError(f"h{year}.zip: the connection timed out")

    monkeypatch.setattr(
        "jmacat.controller.cli.build_source", lambda **kwargs: TimingOutSource()
    )

    result = runner.invoke(
        app, ["fetch", "--year", "1919", "--output", str(tmp_path / "e.parquet")]
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "try again" in result.output.lower()


def test_an_unknown_area_lists_the_names_that_do_work(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "e.parquet"),
            "--area",
            "ishikaw",
        ],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "ishikawa" in result.output


def test_an_unknown_format_is_rejected_before_anything_is_fetched(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "e.txt"),
            "--format",
            "parqet",
        ],
    )

    assert result.exit_code != 0
    assert catalog.requested_years == []


def test_a_missing_required_argument_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["fetch", "--output", str(tmp_path / "e.parquet")])

    assert result.exit_code != 0


def test_a_destination_that_is_a_directory_is_a_clean_error(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    """The writers raise `EventWriterError`; the CLI must not leak it raw."""
    result = runner.invoke(
        app, ["fetch", "--year", "1919", "--output", str(tmp_path), "--format", "csv"]
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_version_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "jmacat" in result.output


def _plain(text: str) -> str:
    """Strip the ANSI styling rich puts inside an option name.

    `--year` reaches the terminal as `--` and `year` in two colours, so a
    substring match against the raw output fails even though the help is
    correct. Stripping the escapes tests what a reader sees.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_help_names_every_documented_option() -> None:
    result = runner.invoke(app, ["fetch", "--help"])

    assert result.exit_code == 0
    output = _plain(result.output)
    for option in (
        "--year",
        "--output",
        "--format",
        "--area",
        "--min-magnitude",
        "--max-magnitude",
        "--min-depth",
        "--max-depth",
    ):
        assert option in output


def test_help_offers_exactly_the_options_the_python_api_takes() -> None:
    """The CLI and the SDK must not be able to drift.

    Rather than trusting that both signatures were edited together, this reads
    the parameters off `fetch` — the function an SDK caller imports — and
    requires the command's help to advertise every one of them. Adding a
    parameter to `fetch` alone, or an option to the command alone, turns this
    red.
    """
    parameters = [
        name for name in inspect.signature(fetch).parameters if name != "output_format"
    ]
    output = _plain(runner.invoke(app, ["fetch", "--help"]).output)

    for name in parameters:
        assert f"--{name.removesuffix('_km').replace('_', '-')}" in output
    # `output_format` is spelled `--format`, the one place the two names differ.
    assert "--format" in output
    assert set(inspect.signature(fetch).parameters) == set(
        inspect.signature(run_fetch).parameters
    )


def test_an_interrupted_run_publishes_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl-C mid-run must leave the destination absent, not short.

    The writers stage to a temporary file and publish by atomic rename on a
    clean close; this asserts the guarantee survives the CLI's own layer, and
    that no staging file is left lying beside the destination either.
    """

    class InterruptingSource:
        def record_lines(self, year: int) -> Iterator[str]:
            def lines() -> Iterator[str]:
                yield M61
                raise KeyboardInterrupt

            return lines()

    monkeypatch.setattr(
        "jmacat.controller.cli.build_source", lambda **kwargs: InterruptingSource()
    )
    destination = tmp_path / "events.csv"

    result = runner.invoke(
        app,
        ["fetch", "--year", "1919", "--output", str(destination), "--format", "csv"],
    )

    assert result.exit_code != 0
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_existing_output_survives_a_failed_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed re-run must not damage the complete file from an earlier run."""
    destination = tmp_path / "events.csv"
    destination.write_text("an earlier, complete run\n", encoding="utf-8")

    monkeypatch.setattr(
        "jmacat.controller.cli.build_source",
        lambda **kwargs: UnavailableYearCatalogSource(),
    )
    result = runner.invoke(
        app,
        ["fetch", "--year", "2024", "--output", str(destination), "--format", "csv"],
    )

    assert result.exit_code != 0
    assert destination.read_text(encoding="utf-8") == "an earlier, complete run\n"


def test_the_python_api_takes_the_same_arguments_as_the_command_line(
    tmp_path: Path, catalog: InMemoryCatalogSource
) -> None:
    """The CLI and the SDK must not be able to drift.

    `fetch` is the function typer binds to the command, so calling it directly
    is the SDK path, and it returns the same `ExportResult` the CLI formats.
    Anything the command can express, this call can express identically.
    """
    result = fetch(
        year=1919,
        output=tmp_path / "events.csv",
        output_format=OutputFormat.CSV,
        min_magnitude=3.0,
    )

    assert result.records_written == 1
    assert result.records_excluded_for_a_missing_value == 1
    assert result.reconciles()


def test_the_writer_factory_honours_the_requested_format(tmp_path: Path) -> None:
    """The one place a format string becomes a concrete adapter."""
    with build_writer(OutputFormat.CSV, tmp_path / "a.csv") as csv_writer:
        assert type(csv_writer).__name__ == "CsvEventWriter"
    with build_writer(OutputFormat.PARQUET, tmp_path / "a.parquet") as parquet_writer:
        assert type(parquet_writer).__name__ == "ParquetEventWriter"


def test_the_request_the_cli_builds_is_the_one_the_interactor_receives(
    tmp_path: Path, catalog: InMemoryCatalogSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every command-line option must reach the request, not be dropped silently.

    A CLI that accepted `--max-magnitude` and never passed it on would still
    exit zero and write a file, so the assertion is on the request object
    itself rather than on the run's outcome.
    """
    seen: list[ExportRequest] = []
    original = cli.export

    def spy(
        request: ExportRequest,
        *,
        source: CatalogSource,
        writer: EventWriter[Hypocenter],
    ) -> ExportResult:
        seen.append(request)
        return original(request, source=source, writer=writer)

    monkeypatch.setattr(cli, "export", spy)
    result = runner.invoke(
        app,
        [
            "fetch",
            "--year",
            "1919",
            "--output",
            str(tmp_path / "e.csv"),
            "--format",
            "csv",
            "--min-magnitude",
            "3.0",
            "--max-magnitude",
            "7.5",
            "--min-depth",
            "10",
            "--max-depth",
            "200",
            "--area",
            "ishikawa",
        ],
    )

    assert result.exit_code == 0, result.output
    (request,) = seen
    assert request.year == 1919
    assert request.destination == tmp_path / "e.csv"
    assert request.output_format is OutputFormat.CSV
    assert request.min_magnitude == 3.0
    assert request.max_magnitude == 7.5
    assert request.min_depth_km == 10
    assert request.max_depth_km == 200
    assert request.area == "ishikawa"
