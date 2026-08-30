"""A `Transport` that replays a recorded response instead of calling JMA.

The adapter takes its transport as a constructor argument precisely so tests
can substitute this. Patching `urllib.request.urlopen` would work too, but it
couples every test to the adapter's internals; a recorded response is the same
seam the production transport uses, so a test that passes here is testing the
real code path.
"""

from __future__ import annotations

import http.client
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


class _DribblingRaw(io.RawIOBase):
    """A stream that returns only `per_read` bytes at a time.

    Returning fewer bytes than asked for is legal and routine: `HTTPResponse`
    does it at every chunk boundary under chunked transfer-encoding. Code that
    assumes one `read(n)` yields all n bytes is wrong, and this is what proves
    it — the body is complete, so any failure is the reader's fault, not the
    transfer's.
    """

    def __init__(self, body: bytes, *, per_read: int = 2) -> None:
        self._body = body
        self._per_read = per_read
        self._position = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        count = min(self._per_read, len(buffer), len(self._body) - self._position)
        buffer[:count] = self._body[self._position : self._position + count]
        self._position += count
        return count


class _IncompleteReadRaw(io.RawIOBase):
    """Fails mid-body with `http.client.IncompleteRead`.

    Worth its own double because `IncompleteRead` is an `HTTPException`, *not*
    an `OSError` — so an adapter that guards only `OSError` lets it escape as a
    non-port error and leaves its partial file behind. This is the truncation
    urllib actually reports when a Content-Length is not satisfied.
    """

    def __init__(self, body: bytes, *, fail_after: int) -> None:
        self._body = body
        self._fail_after = fail_after
        self._position = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        if self._position >= self._fail_after:
            raise http.client.IncompleteRead(b"", 1024)
        remaining = self._fail_after - self._position
        count = min(len(buffer), remaining)
        buffer[:count] = self._body[self._position : self._position + count]
        self._position += count
        return count


def DribblingStream(  # noqa: N802 - reads as a constructor at the call site
    body: bytes, *, per_read: int = 2
) -> io.BufferedReader:
    """A complete body delivered a couple of bytes per read.

    Wrapped in a `BufferedReader` so it is a genuine `IO[bytes]`, matching what
    the adapter receives from urllib. The buffering does not defeat the test:
    the adapter still asks the wrapper for exactly 4 bytes, and a
    `BufferedReader` over a dribbling raw stream can still return fewer.
    """
    return io.BufferedReader(_DribblingRaw(body, per_read=per_read))


def IncompleteReadStream(  # noqa: N802 - reads as a constructor at the call site
    body: bytes, *, fail_after: int
) -> io.BufferedReader:
    """A body that fails mid-transfer with `http.client.IncompleteRead`."""
    return io.BufferedReader(_IncompleteReadRaw(body, fail_after=fail_after))


class RaisingTransport:
    """A `Transport` whose `fetch` raises a chosen native exception.

    Distinct from `RecordedTransport(responses=[error])`, which raises *after*
    recording the URL and is aimed at retry scripting. This one models the
    class of failure urllib lets escape from `urlopen` itself — notably
    `http.client.BadStatusLine`, which `do_open` cannot wrap because it calls
    `getresponse()` outside its own `except OSError`.
    """

    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.requested_urls: list[str] = []

    def fetch(self, url: str, *, timeout: float) -> Response:
        self.requested_urls.append(url)
        raise self._error

    @property
    def call_count(self) -> int:
        return len(self.requested_urls)
