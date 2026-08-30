"""The HTTP seam the catalog adapter fetches through.

Isolated behind a `Protocol` for one reason: it is the only part of the adapter
that cannot be exercised without a network. Everything above it — status
classification, magic-byte verification, caching, streaming, decoding — is then
testable against recorded responses, which is what lets issue #6's unit tests
honour "recorded fixtures, not the live network" without patching `urllib`
internals from the outside.

Standard library only. `urllib.request` covers exactly what is needed here: one
GET, a timeout, a custom User-Agent, and a readable stream. `httpx` or
`requests` would add a dependency (and a transitive tree) to save a dozen lines,
which CONTRIBUTING's "fewer things that break for a researcher in three years"
argues against.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import IO, Protocol


@dataclass(frozen=True)
class Response:
    """One HTTP response, with its body left unread.

    The body is an open stream rather than `bytes` because a year's archive is
    ~7 MB compressed and the adapter writes it to the cache in chunks; reading
    it eagerly here would defeat that before it started.
    """

    status: int
    content_type: str
    stream: IO[bytes]


class Transport(Protocol):
    """Performs one GET and hands back the response with its body unread."""

    def fetch(self, url: str, *, timeout: float) -> Response:
        """GET `url`, returning even non-2xx responses rather than raising.

        A 404 is *data* to this adapter — it is how JMA says a year is not
        published — so it must reach the caller as a `Response` to be
        classified, not as an exception. Only genuine transport failures
        (timeout, reset, DNS) raise, and they raise their native `OSError`
        subclass for the caller to translate.
        """
        ...


#: Identifies the tool and gives JMA's operators a way to make contact, as
#: courtesy to a public data service asks. Includes the project URL rather than
#: a bare token so an unexpected access pattern in their logs is traceable to a
#: human rather than looking like an anonymous scraper.
USER_AGENT = (
    "jmacat/0.1.0 (JMA seismic catalog preprocessing for research and education; "
    "+https://github.com/uonoko1/jmacat)"
)


class UrllibTransport:
    """The production `Transport`, over `urllib.request`."""

    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self._user_agent = user_agent

    def fetch(self, url: str, *, timeout: float) -> Response:
        request = urllib.request.Request(  # noqa: S310 - fixed https JMA host
            url,
            headers={"User-Agent": self._user_agent},
            method="GET",
        )
        try:
            opened = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
        except urllib.error.HTTPError as error:
            # urllib raises on 4xx/5xx, but an HTTPError *is* the response and
            # is readable. Turning it back into a Response is what lets the
            # caller apply the errors-module classification table to a 404 and a
            # 503 in the same place, instead of splitting that decision across
            # an except branch and a success branch.
            return Response(
                status=error.code,
                content_type=error.headers.get("Content-Type", ""),
                stream=error,
            )
        return Response(
            status=opened.status,
            content_type=opened.headers.get("Content-Type", ""),
            stream=opened,
        )
