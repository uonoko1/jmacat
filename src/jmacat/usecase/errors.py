"""Typed failures raised by the use case output ports.

These live in `usecase/`, not `domain/`, because they describe failures of the
*boundary* — a catalog that could not be obtained, a destination that could not
be written — not failures of the earthquake domain itself. A malformed record is
a domain concern; a 404 is not.

Infrastructure adapters translate their native exceptions (`urllib.error.HTTPError`,
`zipfile.BadZipFile`, `OSError`, a Parquet writer's own errors) into these types
at the boundary. That translation is what keeps `usecase/` free of third-party
imports and lets the interactors handle failure without knowing whether the
catalog arrived over HTTP, from a local ZIP, or from a fake.
"""

from __future__ import annotations


class PortError(Exception):
    """Base class for every failure raised by a use case output port.

    Lets a caller catch all boundary failures without enumerating them, which
    matters for the CLI: it needs to turn any port failure into a non-zero exit
    and a readable message, and must not silently swallow one it forgot to name.
    """


class CatalogSourceError(PortError):
    """The raw catalog could not be obtained."""


class CatalogYearUnavailableError(CatalogSourceError):
    """The requested year is not published by JMA.

    JMA's finalized hypocenter catalog lags several years behind the present, so
    `h{year}.zip` returns 404 for recent years (h2024.zip does today). A year
    before the catalog begins is unavailable for the same reason.

    This is a distinct type rather than an empty stream because the two mean
    opposite things: "we have no data for this year" versus "this year had no
    earthquakes". Conflating them would let a missing download be published as a
    quiet, plausible-looking result — exactly the silent wrong answer that
    CONTRIBUTING's "fail loudly" rule exists to prevent.
    """

    def __init__(self, year: int, message: str | None = None) -> None:
        self.year = year
        super().__init__(
            message
            if message is not None
            else f"The JMA catalog for year {year} is not available."
        )


class CatalogRetrievalError(CatalogSourceError):
    """The catalog for an available year could not be retrieved or read.

    Distinct from `CatalogYearUnavailableError`: the year is expected to exist,
    but the transfer or the archive failed — a timeout, a truncated download, a
    corrupt ZIP. Worth separating because this class of failure is usually worth
    retrying, whereas a 404 for a year JMA has not published yet is not.
    """


class EventWriterError(PortError):
    """Converted events could not be written to the destination."""
