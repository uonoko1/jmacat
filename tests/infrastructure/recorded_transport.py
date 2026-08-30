"""A `Transport` that replays a recorded response instead of calling JMA.

The adapter takes its transport as a constructor argument precisely so tests
can substitute this. Patching `urllib.request.urlopen` would work too, but it
couples every test to the adapter's internals; a recorded response is the same
seam the production transport uses, so a test that passes here is testing the
real code path.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

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


class _FailingRaw(io.RawIOBase):
    """Delivers `fail_after` bytes of `body`, then raises as a reset does."""

    def __init__(self, body: bytes, *, fail_after: int) -> None:
        self._body = body
        self._fail_after = fail_after
        self._position = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        if self._position >= self._fail_after:
            raise ConnectionResetError("connection reset by peer")
        remaining = self._fail_after - self._position
        count = min(len(buffer), remaining)
        buffer[:count] = self._body[self._position : self._position + count]
        self._position += count
        return count


def FailingStream(  # noqa: N802 - reads as a constructor at the call site
    body: bytes, *, fail_after: int
) -> io.BufferedReader:
    """A response body that dies partway through, as a dropped transfer does.

    A truncated transfer is the failure most likely to poison a cache — the
    bytes that did arrive look like the start of a real archive. Simulating it
    at the stream level, rather than by pre-truncating the body, is what
    exercises the adapter's mid-write error path.

    Wrapped in a `BufferedReader` so it is a genuine `IO[bytes]`, which is what
    the adapter receives from `urllib` in production.
    """
    return io.BufferedReader(_FailingRaw(body, fail_after=fail_after))
