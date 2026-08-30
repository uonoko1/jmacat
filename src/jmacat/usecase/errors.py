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

Classifying a catalog failure
-----------------------------

**Classify by what the response says about *publication*, not about bytes.** The
question is never "did I get a ZIP?" but "does JMA have this year?". Those come
apart precisely where it matters, so the port decides the mapping rather than
leaving each adapter to guess:

===============================  ==============================================
Observation                      Error
===============================  ==============================================
404 (HTML body or not)           `CatalogYearUnavailableError`
200 whose body is HTML,          `CatalogYearUnavailableError`
not a ZIP
5xx                              `CatalogRetrievalError`
Timeout, connection reset,       `CatalogRetrievalError`
truncated transfer
200 ZIP that will not open       `CatalogRetrievalError`
===============================  ==============================================

**Why a 200 with an HTML body is "unavailable", not "retrieval failed".** Both
readings type check and they diverge completely on behaviour, so this is worth
stating once here. Read by bytes, an HTML body is "not a ZIP, so the archive
failed" — `CatalogRetrievalError`, which is retryable, so the CLI would retry a
stable condition forever and eventually report a transfer problem that does not
exist. Read by publication, a web server that answers a request for `h2024.zip`
with a page is telling us there is no such archive; whether it says so with a
404 or with a 200 and an error page is a detail of that server's configuration,
not a fact about the catalog. The user-visible truth is the same in both cases —
*JMA has not published this year* — and that is what the error should carry. So
the HTML body is classified as unavailable, and the publication-lag message is
the one the user gets.

The cost of the two mistakes is asymmetric, which settles the residual doubt. A
genuine transient failure misread as "unavailable" fails loudly and the user
re-runs. A permanent "this year does not exist" misread as retryable burns the
retry budget and then reports the wrong cause. CONTRIBUTING's "fail loudly"
rule prefers the first.

**Why a 5xx is retryable.** A 5xx is the server reporting its own trouble, and
says nothing about whether the year exists — the resource may well be there once
the server recovers. That is `CatalogRetrievalError`, the same bucket as a
timeout.

Anchor, verified against the live site: `h2023.zip` returns 200 `application/zip`
(6,977,812 bytes); `h2024.zip` returns 404 with a `text/html` body.
"""

from __future__ import annotations


class PortError(Exception):
    """Base class for every failure raised by a use case output port.

    Lets a caller catch all boundary failures without enumerating them, which
    matters for the CLI: it needs to turn any port failure into a non-zero exit
    and a readable message, and must not silently swallow one it forgot to name.
    """

    #: Whether retrying the same operation unchanged could plausibly succeed.
    #:
    #: Declared here as a class attribute rather than left to the caller's
    #: `isinstance` checks. Retryability is a property of *why* the failure
    #: happened, which only the error type knows; re-deriving it at each call
    #: site means every new error type silently defaults to whatever that site's
    #: `else` branch does. A new subclass must now state its answer, and a
    #: retry loop reads `if err.retryable:` without importing the taxonomy.
    #:
    #: Conservatively False at the base: an unrecognised failure is not retried.
    retryable: bool = False


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

    Not retryable: waiting will not make JMA publish the year sooner, and
    retrying a 404 in a loop only delays a clear message to the user.
    """

    retryable = False

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
    corrupt ZIP, an HTTP 5xx. Worth separating because this class of failure is
    transient, whereas a year JMA has not published is not.

    Retryable: the request was well-formed and the year is expected to exist, so
    the same call may succeed later. Issue #6 owns the retry budget; the port
    only classifies.
    """

    retryable = True


class EventWriterError(PortError):
    """Converted events could not be written to the destination.

    Not retryable by default: a full disk or an unwritable path does not fix
    itself within a run, and retrying a partially written destination risks
    duplicating records.
    """
