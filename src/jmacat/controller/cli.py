"""The `jmacat` command line.

Thin by design: parse arguments, wire the concrete adapters, call the
interactor, format the result. Every decision about *what* an export does lives
in `jmacat.usecase.export`; this module decides only how it is spelled on a
terminal and how the outcome is rendered.

This is the one place in the project where wiring belongs — `build_source` and
`build_writer` are the only functions that name a class from
`jmacat.infrastructure`. `usecase/` never does, and the AST guard in
`tests/test_architecture.py` enforces it.

The CLI and the SDK are the same code
-------------------------------------

`fetch` is both the function typer binds to the `fetch` command and the
function a Python caller imports:

    from jmacat.controller.cli import fetch
    from jmacat.usecase.export import OutputFormat

    result = fetch(year=2023, output=Path("events.parquet"),
                   min_magnitude=3.0, area="ishikawa")

Every option below is a parameter of that one function, so the two paths cannot
drift into different behaviour: there is no second implementation to keep in
step. The command layer adds only argument parsing and the printed report; the
returned `ExportResult` is what the SDK caller gets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from jmacat.domain.filters import FilterError, available_area_names
from jmacat.domain.hypocenter import Hypocenter
from jmacat.infrastructure.csv_event_writer import CsvEventWriter
from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource
from jmacat.infrastructure.parquet_event_writer import ParquetEventWriter
from jmacat.usecase.errors import PortError
from jmacat.usecase.export import (
    ExportRequest,
    ExportResult,
    OutputFormat,
    export,
)
from jmacat.usecase.ports import CatalogSource, EventWriter

__version__ = "0.1.0"

#: The module's public surface. `export` is re-exported deliberately: the
#: interactor is what this module composes, and naming it here is what lets a
#: caller — or a test substituting it at the composition seam — reach it
#: without importing around the controller.
__all__ = [
    "OutputFormat",
    "app",
    "build_source",
    "build_writer",
    "export",
    "fetch",
    "report",
    "run_fetch",
]

app = typer.Typer(
    name="jmacat",
    help=(
        "Fetch the JMA hypocenter catalog and write it as Parquet or CSV. "
        "For research and education only; not for evacuation decisions or "
        "real-time alerting."
    ),
    add_completion=False,
)


# -- wiring: the only place a concrete adapter is named ---------------------


def build_source(**kwargs: object) -> CatalogSource:
    """The catalog adapter the commands use.

    A function rather than a direct constructor call so that a test can
    substitute the in-memory fake at exactly the seam the architecture
    describes, without any command taking a source parameter it would never
    otherwise want.
    """
    return JmaCatalogSource()


def build_writer(
    output_format: OutputFormat, destination: Path
) -> EventWriter[Hypocenter]:
    """Open the writer for `output_format` at `destination`.

    Returned open and unclosed: the caller owns its lifetime through `with`,
    which is what discards the staged file if the run fails part-way. Both
    writers publish by atomic rename on a clean close, so an interrupted run
    leaves the destination absent rather than short.
    """
    if output_format is OutputFormat.CSV:
        return CsvEventWriter(destination)
    return ParquetEventWriter(destination)


# -- the fetch command ------------------------------------------------------


# The option annotations, defined once and used by both `fetch` (the SDK entry
# point) and `run_fetch` (the command typer binds). Sharing the aliases is what
# makes the two signatures impossible to drift apart: an option added here
# appears on both, and one removed disappears from both.

YearOption = Annotated[int, typer.Option("--year", help="Catalog year, e.g. 2023.")]
OutputOption = Annotated[
    Path,
    typer.Option(
        "--output",
        "-o",
        help="Destination file. Written only if the whole run succeeds.",
    ),
]
FormatOption = Annotated[OutputFormat, typer.Option("--format", help="Output format.")]
AreaOption = Annotated[
    str | None,
    typer.Option(
        "--area",
        help=(
            "Keep only events inside a named area's approximate bounding box. "
            f"Available: {', '.join(available_area_names())}. A rectangle, not "
            "a prefecture boundary."
        ),
    ),
]
MinMagnitudeOption = Annotated[
    float | None,
    typer.Option(
        "--min-magnitude",
        help=(
            "Keep events of at least this magnitude, inclusive. Records with "
            "no magnitude are excluded and counted separately."
        ),
    ),
]
MaxMagnitudeOption = Annotated[
    float | None,
    typer.Option("--max-magnitude", help="Keep events at most this magnitude."),
]
MinDepthOption = Annotated[
    float | None,
    typer.Option("--min-depth", help="Keep events at least this deep, in km."),
]
MaxDepthOption = Annotated[
    float | None,
    typer.Option("--max-depth", help="Keep events at most this deep, in km."),
]


def fetch(
    year: YearOption,
    output: OutputOption,
    output_format: FormatOption = OutputFormat.PARQUET,
    area: AreaOption = None,
    min_magnitude: MinMagnitudeOption = None,
    max_magnitude: MaxMagnitudeOption = None,
    min_depth_km: MinDepthOption = None,
    max_depth_km: MaxDepthOption = None,
) -> ExportResult:
    """Fetch one year of the JMA catalog, filter it, and write it out.

    Importable and callable directly; see the module docstring. Raises the use
    case's own errors rather than exiting, so an SDK caller can handle them —
    `run_fetch` is the wrapper that turns them into a command-line message and
    a non-zero exit.
    """
    request = ExportRequest(
        year=year,
        destination=output,
        output_format=output_format,
        area=area,
        min_magnitude=min_magnitude,
        max_magnitude=max_magnitude,
        min_depth_km=min_depth_km,
        max_depth_km=max_depth_km,
    )
    source = build_source()
    # `with` owns the writer's lifetime: on any exception, including
    # KeyboardInterrupt, the adapter discards its staged file rather than
    # publishing a short one.
    with build_writer(output_format, output) as writer:
        return export(request, source=source, writer=writer)


@app.command("fetch")
def run_fetch(
    year: YearOption,
    output: OutputOption,
    output_format: FormatOption = OutputFormat.PARQUET,
    area: AreaOption = None,
    min_magnitude: MinMagnitudeOption = None,
    max_magnitude: MaxMagnitudeOption = None,
    min_depth_km: MinDepthOption = None,
    max_depth_km: MaxDepthOption = None,
) -> None:
    """Fetch one year of the JMA catalog, filter it, and write it out.

    The command layer, and deliberately nothing more: it forwards its arguments
    unchanged to `fetch`, turns a failure into a message and a non-zero exit,
    and prints the report. The option types it declares are the *same* annotated
    aliases `fetch` uses, so an option cannot exist on one and not the other —
    which is what "the CLI and the SDK must not drift" means in practice.
    """
    try:
        result = fetch(
            year=year,
            output=output,
            output_format=output_format,
            area=area,
            min_magnitude=min_magnitude,
            max_magnitude=max_magnitude,
            min_depth_km=min_depth_km,
            max_depth_km=max_depth_km,
        )
    except FilterError as error:
        # An unknown area, or a bound the filters refuse. The message already
        # lists what would have worked.
        _fail(str(error))
    except PortError as error:
        _fail(_port_failure(error))
    except KeyboardInterrupt:
        _fail("Interrupted. No file was written to the destination.")

    for line in report(result):
        typer.echo(line)


def _fail(message: str) -> NoReturn:
    """Print `message` to stderr and exit non-zero, with no traceback."""
    typer.secho(f"error: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)


def _port_failure(error: PortError) -> str:
    """Render a boundary failure, adding retry advice only where it applies.

    `retryable` is read off the error rather than re-derived with `isinstance`,
    which is the whole reason the attribute exists: a new error type states its
    own answer instead of falling into whichever branch this function forgot.
    """
    if error.retryable:
        return f"{error} You can try again."
    return str(error)


# -- reporting --------------------------------------------------------------


def report(result: ExportResult) -> list[str]:
    """The lines printed after a successful run.

    Separate from the command so it can be tested as a pure function of a
    result, and so an SDK caller can print the same summary.

    **Selected is reported once, not per filter.** The outcome counts partition
    the input — a record is attributed to the first filter that rejects it — so
    there is exactly one selected count for the run, and printing it under each
    filter would read as though every filter had independently selected that
    many.

    The missing-value exclusion gets its own line, and **only when it is
    non-zero**: a line that always appeared would tell every user the same
    thing and stop carrying information. Issue #20 exists because 41.2 per cent
    of the pre-war corpus vanishes from an `--min-magnitude` run for want of a
    magnitude, and a user told only the selected count cannot see it.
    """
    lines = [
        f"Wrote {result.records_written:,} events to {result.destination} "
        f"({result.output_format.value}).",
        f"Read {result.records_read:,} records from the {result.year} catalog.",
    ]
    if result.records_rejected:
        lines.append(
            f"{result.records_rejected:,} records could not be parsed and were "
            f"not written."
        )
        lines.extend(f"  {reason}" for reason in result.rejections)
    if result.filter_outcomes:
        lines.append(f"{result.records_written:,} selected after filtering:")
        for outcome in result.filter_outcomes:
            if outcome.excluded_by_comparison:
                lines.append(
                    f"  {outcome.excluded_by_comparison:,} excluded by {outcome.name}"
                )
            if outcome.excluded_missing_value:
                share = outcome.excluded_missing_value / result.records_read * 100
                lines.append(
                    f"  {outcome.excluded_missing_value:,} excluded for a "
                    f"missing {outcome.name} ({share:.1f}% of the records "
                    f"read) — these records carry no {outcome.name} at all, "
                    f"so the filter could not judge them"
                )
        # The identity is printed so a reader can check it rather than take the
        # numbers on trust; a run whose counts did not reconcile would be a bug
        # in the attribution, and this is where it would show.
        lines.append(
            f"  ({result.records_written:,} + {result.records_excluded:,} "
            f"excluded + {result.records_rejected:,} unparsed "
            f"= {result.records_read:,} read)"
        )
    return lines


# -- top level --------------------------------------------------------------


def _version(value: bool) -> None:
    if value:
        typer.echo(f"jmacat {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Fetch and convert the JMA hypocenter catalog."""


if __name__ == "__main__":  # pragma: no cover
    app()
