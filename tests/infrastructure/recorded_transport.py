"""A `Transport` that replays a recorded response instead of calling JMA.

The adapter takes its transport as a constructor argument precisely so tests
can substitute this. Patching `urllib.request.urlopen` would work too, but it
couples every test to the adapter's internals; a recorded response is the same
seam the production transport uses, so a test that passes here is testing the
real code path.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence

from jmacat.infrastructure.transport import Response


class RecordedTransport:
    """Replays one recorded response, or a scripted sequence of them.

    A sequence is what makes retry behaviour testable: give it two timeouts
    followed by a ZIP and assert the adapter recovers.
    """

    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        content_type: str = "application/zip",
        responses: Sequence[Response | Exception] | None = None,
    ) -> None:
        self._scripted: list[Response | Exception] | None = (
            list(responses) if responses is not None else None
        )
        self._single = Response(
            status=status,
            content_type=content_type,
            stream=io.BytesIO(body),
        )
        self._single_body = body
        self.requested_urls: list[str] = []

    def fetch(self, url: str, *, timeout: float) -> Response:
        self.requested_urls.append(url)
        if self._scripted is not None:
            if not self._scripted:
                raise AssertionError(
                    f"RecordedTransport ran out of scripted responses at {url}"
                )
            nxt = self._scripted.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        # A fresh stream per call, so a retry test does not read an exhausted one.
        return Response(
            status=self._single.status,
            content_type=self._single.content_type,
            stream=io.BytesIO(self._single_body),
        )

    @property
    def call_count(self) -> int:
        return len(self.requested_urls)


def chunked(body: bytes, *, status: int = 200, content_type: str = "application/zip") -> Response:
    """A `Response` whose body is delivered in small chunks."""
    return Response(status=status, content_type=content_type, stream=io.BytesIO(body))


def truncating_stream(body: bytes, *, after: int) -> Iterator[bytes]:
    """Yield `after` bytes of `body`, then fail as a dropped connection would."""
    yield body[:after]
    raise ConnectionResetError("connection reset by peer")
