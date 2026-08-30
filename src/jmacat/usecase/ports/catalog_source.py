"""The `CatalogSource` output port.

What the use case layer needs from the outside world in order to read a year of
the JMA hypocenter catalog, expressed without saying anything about *how* that
year is obtained.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class CatalogSource(Protocol):
    """Obtains the raw JMA hypocenter catalog for a year and streams its lines.

    Design notes
    ------------

    **Why a year is the unit.** JMA publishes the finalized hypocenter catalog as
    one archive per year (`h{year}.zip`), so the year is the smallest thing an
    implementation can actually fetch. A narrower unit (a month, a date range)
    would be a fiction the adapter has to synthesise by downloading the whole
    year anyway; filtering to a sub-range is the use case's job, applied to this
    stream. A wider unit (all years at once) would deny the caller any chance to
    fail, resume, or report progress per year.

    **Why it streams.** A single year is roughly 257,000 records / ~25 MB, and a
    multi-decade run is gigabytes. Returning `list[str]` would put a whole year
    in memory at once and force the adapter to finish downloading before the
    first record could be converted. `Iterator[str]` lets the pipeline run
    incrementally — fetch, decode, convert, write — at constant memory, and lets
    a caller stop early (a `--limit` flag, a date filter that has passed its
    window) without paying for the rest of the archive.

    `Iterator[str]` is chosen over `Iterable[str]` deliberately: an `Iterable`
    may be a list, so it would permit exactly the eager implementation the port
    is trying to forbid, and it leaves re-iterability ambiguous. An `Iterator` is
    single-pass by definition, which states the real contract — a downloaded
    stream cannot be rewound — and makes an accidental second iteration fail
    loudly rather than silently re-downloading 25 MB.

    **Why lines, not parsed records.** The port yields the raw fixed-width lines
    and does not interpret them. Parsing the JMA record layout is the domain
    layer's responsibility (issue #3), which keeps the byte offsets and the
    scientific conversion testable with no I/O at all, and keeps this boundary
    stable if JMA changes its transport but not its record format.

    **Why an unavailable year raises.** See `record_lines`.
    """

    def record_lines(self, year: int) -> Iterator[str]:
        """Return an iterator over the catalog's raw record lines for `year`.

        Lines are yielded in the order they appear in the published archive,
        with the line terminator stripped. The catalog is fixed-width text; a
        line is passed through uninterpreted.

        **`record_lines` must not itself be a generator function.** An
        implementation MUST resolve availability first — issue the request,
        observe the 404, check the archive magic bytes — and only then return a
        *separate* generator for the lines. The lines themselves must still be
        produced lazily; it is the availability decision that is eager.

        The mechanism matters because the natural spelling is wrong and type
        checks anyway::

            def record_lines(self, year: int) -> Iterator[str]:
                if unavailable:
                    raise CatalogYearUnavailableError(year)   # never runs
                yield from lines

        A `yield` anywhere in the body makes the whole function a generator
        function, so calling it executes none of that body: it returns a
        generator and raises nothing. The 404 then surfaces at the caller's
        first `next()`, escaping any `try`/`except` around the call site — and a
        failed download becomes an empty catalog, the exact silent wrong answer
        this port exists to prevent. Write it as two functions instead::

            def record_lines(self, year: int) -> Iterator[str]:
                archive = self._resolve(year)      # raises here, eagerly
                return self._lines(archive)        # a separate generator

        `jmacat.usecase.ports.contract.check_unavailable_year_fails_eagerly`
        enforces this; run it against your implementation rather than trusting
        the shape to be right.

        Raises:
            CatalogYearUnavailableError: JMA does not publish this year. The
                finalized catalog lags several years behind the present, so
                recent years 404. This is raised rather than returning an empty
                iterator: an empty stream would be indistinguishable from a year
                in which no earthquakes were recorded, and would let a failed
                download be published as a real — and wrong — result.
            CatalogRetrievalError: the year should exist but could not be
                fetched or read (timeout, truncated transfer, corrupt archive).
        """
        ...
