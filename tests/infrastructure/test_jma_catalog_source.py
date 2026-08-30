"""Tests for the HTTP/ZIP `CatalogSource` adapter.

Every test here runs against recorded fixtures — never the live network. The
one test that touches JMA lives in `test_jma_catalog_source_integration.py`
and is skipped unless it is opted into explicitly.
"""

from __future__ import annotations

import io
from collections.abc import Generator
from pathlib import Path

import pytest

from jmacat.infrastructure.jma_catalog_source import (
    JmaCatalogSource,
    default_cache_dir,
)
from jmacat.infrastructure.transport import USER_AGENT, Response
from jmacat.usecase.errors import CatalogRetrievalError, CatalogYearUnavailableError
from jmacat.usecase.ports.contract import check_unavailable_year_fails_eagerly
from tests.infrastructure.recorded_transport import (
    DribblingStream,
    FailingStream,
    IncompleteReadStream,
    RecordedTransport,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ZIP = FIXTURES / "h1919_sample.zip"
NOT_FOUND_HTML = FIXTURES / "h2024_404.html"

#: The year JMA's finalized catalog has not reached (verified 2026-08-30:
#: h2024.zip returns 404 with a 2,203-byte HTML body).
UNAVAILABLE_YEAR = 2024


def not_found_transport() -> RecordedTransport:
    """A transport replaying JMA's real 404 for an unpublished year."""
    return RecordedTransport(
        status=404,
        body=NOT_FOUND_HTML.read_bytes(),
        content_type="text/html",
    )


class TestPortContract:
    def test_the_adapter_satisfies_the_eager_availability_contract(
        self, tmp_path: Path
    ) -> None:
        """The port's own executable check, run against the real adapter.

        This is the check that rejects `record_lines` being a generator
        function before it even calls it. Running it here — rather than
        trusting the shape by eye — is what issue #6 requires.
        """
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=not_found_transport(),
        )

        check_unavailable_year_fails_eagerly(source, unavailable_year=UNAVAILABLE_YEAR)


class TestUnavailableYear:
    """The 404 path — the failure a user is most likely to hit."""

    def test_a_404_raises_catalog_year_unavailable(self, tmp_path: Path) -> None:
        source = JmaCatalogSource(cache_dir=tmp_path, transport=not_found_transport())

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            source.record_lines(UNAVAILABLE_YEAR)

        assert excinfo.value.year == UNAVAILABLE_YEAR

    def test_the_404_message_is_actionable(self, tmp_path: Path) -> None:
        """A user asking for 2024 should learn *why*, not just see "404".

        The message must name the year, name the URL that was tried, explain
        the publication lag that is the real cause, and say what to do next.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=not_found_transport())

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            source.record_lines(UNAVAILABLE_YEAR)
        message = str(excinfo.value)

        assert "2024" in message
        assert "h2024.zip" in message
        assert "lag" in message
        assert "several years" in message
        # Tells the user where to look rather than leaving them to guess.
        assert "https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html" in message

    def test_an_unavailable_year_is_not_retried(self, tmp_path: Path) -> None:
        """Waiting will not make JMA publish 2024; retrying only delays the message."""
        transport = not_found_transport()
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        with pytest.raises(CatalogYearUnavailableError):
            source.record_lines(UNAVAILABLE_YEAR)

        assert transport.call_count == 1

    def test_an_unavailable_year_is_declared_not_retryable(
        self, tmp_path: Path
    ) -> None:
        source = JmaCatalogSource(cache_dir=tmp_path, transport=not_found_transport())

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            source.record_lines(UNAVAILABLE_YEAR)

        assert excinfo.value.retryable is False

    def test_a_404_body_is_never_cached(self, tmp_path: Path) -> None:
        """Caching the HTML page would poison every later run for that year."""
        source = JmaCatalogSource(cache_dir=tmp_path, transport=not_found_transport())

        with pytest.raises(CatalogYearUnavailableError):
            source.record_lines(UNAVAILABLE_YEAR)

        assert not source.cache_path(UNAVAILABLE_YEAR).exists()
        assert list(tmp_path.iterdir()) == []

    def test_a_200_with_an_html_body_is_also_unavailable(self, tmp_path: Path) -> None:
        """The classification table's subtle row.

        A server answering a request for h{year}.zip with a page is saying the
        archive does not exist, whether it labels that 404 or 200. Read as
        "not a ZIP, so the transfer failed" it would be retried forever and
        then reported as a transfer problem that does not exist.
        """
        transport = RecordedTransport(
            status=200,
            body=NOT_FOUND_HTML.read_bytes(),
            content_type="text/html",
        )
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        with pytest.raises(CatalogYearUnavailableError) as excinfo:
            source.record_lines(UNAVAILABLE_YEAR)

        assert "lag" in str(excinfo.value)
        # Classified by publication, not by bytes: no retry budget is burnt.
        assert transport.call_count == 1


def sample_transport() -> RecordedTransport:
    """A transport serving the recorded 12-line 1919 archive."""
    return RecordedTransport(body=SAMPLE_ZIP.read_bytes())


class TestReadingRecords:
    def test_the_recorded_archive_streams_its_record_lines(
        self, tmp_path: Path
    ) -> None:
        """Twelve real 1919-1950 records; see fixtures/README.md for provenance."""
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        lines = list(source.record_lines(1919))

        assert len(lines) == 12

    def test_every_record_line_is_the_published_fixed_width(
        self, tmp_path: Path
    ) -> None:
        """96 bytes per record, per docs/jma-hypocenter-format.md.

        Also proves the line terminator is stripped, as the port requires: an
        unstripped line would be 97.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        assert {len(line) for line in source.record_lines(1919)} == {96}

    def test_the_first_record_is_the_verbatim_published_line(
        self, tmp_path: Path
    ) -> None:
        """The first line of JMA's h1919 file, byte for byte.

        A real line rather than a synthetic one, per CONTRIBUTING: it is the
        only expectation that can catch a decoding or offset mistake.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        first = next(source.record_lines(1919))

        assert first == (
            "I1919010110335026      64848     1263156     350    72W        "
            "     MINDANAO, PHILIPPINE IS.    "
        )

    def test_lines_are_produced_lazily(self, tmp_path: Path) -> None:
        """Taking one line must not read the whole archive.

        The port promises a caller can stop early — a `--limit`, a date filter
        past its window — without paying for the rest of the year.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        lines = source.record_lines(1919)
        next(lines)

        # An iterator, not a materialised sequence: proving laziness structurally.
        assert iter(lines) is lines
        assert not isinstance(lines, list)


class TestDecoding:
    def test_a_non_ascii_byte_does_not_abort_the_run(self, tmp_path: Path) -> None:
        """One bad byte in 257,000 records must not kill the whole year.

        The records are ASCII, so a non-ASCII byte is a corrupt record. The
        adapter decodes with `errors="replace"`: the offending record still
        arrives, carrying U+FFFD, so the domain parser rejects that one record
        loudly while every other record is still delivered. The alternative —
        `strict` — throws an opaque UnicodeDecodeError from inside the
        iteration and loses the other 256,999 records.
        """
        good = b"J" + b"1" * 95
        corrupt = b"J" + b"\xff" + b"2" * 94
        transport = RecordedTransport(body=_zip_bytes(good + b"\n" + corrupt + b"\n"))
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        lines = list(source.record_lines(1919))

        assert len(lines) == 2
        assert "�" in lines[1]
        assert lines[0] == good.decode("ascii")


def _zip_bytes(payload: bytes, *, member: str = "h1919") -> bytes:
    """A one-member ZIP around `payload`, for cases no fixture covers."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, payload)
    return buffer.getvalue()


class TestCache:
    def test_a_second_run_does_not_re_download(self, tmp_path: Path) -> None:
        """The point of the cache: 7 MB per year, fetched once."""
        transport = sample_transport()
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        list(source.record_lines(1919))
        list(source.record_lines(1919))

        assert transport.call_count == 1

    def test_the_archive_is_cached_under_the_configured_directory(
        self, tmp_path: Path
    ) -> None:
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        list(source.record_lines(1919))

        assert (tmp_path / "h1919.zip").exists()

    def test_a_truncated_cache_entry_is_discarded_and_re_downloaded(
        self, tmp_path: Path
    ) -> None:
        """A run killed mid-write must not poison the cache permanently.

        Without this, a Ctrl-C during a download leaves a half file that every
        later run reads as a corrupt archive — a failure the user cannot
        diagnose and that re-running never clears.
        """
        transport = sample_transport()
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)
        complete = SAMPLE_ZIP.read_bytes()
        (tmp_path / "h1919.zip").write_bytes(complete[: len(complete) // 2])

        lines = list(source.record_lines(1919))

        assert len(lines) == 12
        assert transport.call_count == 1
        assert (tmp_path / "h1919.zip").read_bytes() == complete

    def test_a_corrupt_non_zip_cache_entry_is_discarded(self, tmp_path: Path) -> None:
        """Whatever the file is, if it does not open as a ZIP it is not a cache hit."""
        transport = sample_transport()
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)
        (tmp_path / "h1919.zip").write_bytes(b"not a zip at all")

        assert len(list(source.record_lines(1919))) == 12
        assert transport.call_count == 1

    def test_an_interrupted_download_leaves_no_cache_entry(
        self, tmp_path: Path
    ) -> None:
        """Written to a temporary file and renamed, so a partial write is invisible.

        This is what makes the previous test's scenario rare rather than
        routine: only a complete, verified archive ever appears at the cache
        path.
        """
        body = SAMPLE_ZIP.read_bytes()
        transport = RecordedTransport(
            responses=[
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=FailingStream(body, fail_after=len(body) // 2),
                )
            ]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError):
            source.record_lines(1919)

        assert not (tmp_path / "h1919.zip").exists()
        # Not even a stray temporary file is left behind.
        assert list(tmp_path.iterdir()) == []

    def test_a_silently_truncated_download_is_not_cached(self, tmp_path: Path) -> None:
        """A short transfer that never raises must still be caught.

        A connection can close cleanly after delivering only part of the body:
        the read returns EOF, no OSError is raised, and the bytes that arrived
        begin with a real ZIP header. Only opening the result as an archive —
        whose central directory lives at the *end* of the file — distinguishes
        it from a complete download. Without that check the truncated archive
        is cached and every later run fails on it.
        """
        complete = SAMPLE_ZIP.read_bytes()
        transport = RecordedTransport(
            responses=[
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=io.BytesIO(complete[: len(complete) // 2]),
                )
            ]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError) as excinfo:
            source.record_lines(1919)

        assert "truncated" in str(excinfo.value)
        assert not (tmp_path / "h1919.zip").exists()
        assert list(tmp_path.iterdir()) == []

    def test_the_cache_directory_is_created_on_demand(self, tmp_path: Path) -> None:
        nested = tmp_path / "does" / "not" / "exist"
        source = JmaCatalogSource(cache_dir=nested, transport=sample_transport())

        list(source.record_lines(1919))

        assert (nested / "h1919.zip").exists()

    def test_the_cache_location_is_configurable_by_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JMACAT_CACHE_DIR, so a shared machine can use scratch space."""
        monkeypatch.setenv("JMACAT_CACHE_DIR", str(tmp_path / "scratch"))

        assert default_cache_dir() == tmp_path / "scratch"

    def test_the_cache_falls_back_to_the_xdg_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JMACAT_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        assert default_cache_dir() == tmp_path / "jmacat"


class TestRetries:
    def test_a_timeout_is_retried_and_can_succeed(self, tmp_path: Path) -> None:
        transport = RecordedTransport(
            responses=[
                TimeoutError("timed out"),
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=io.BytesIO(SAMPLE_ZIP.read_bytes()),
                ),
            ]
        )
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        assert len(list(source.record_lines(1919))) == 12
        assert transport.call_count == 2

    def test_a_server_error_is_retried(self, tmp_path: Path) -> None:
        """A 5xx is the server's own trouble; it says nothing about the year."""
        transport = RecordedTransport(
            responses=[
                Response(status=503, content_type="text/html", stream=io.BytesIO(b"")),
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=io.BytesIO(SAMPLE_ZIP.read_bytes()),
                ),
            ]
        )
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        assert len(list(source.record_lines(1919))) == 12

    def test_retries_are_bounded(self, tmp_path: Path) -> None:
        """A researcher is better served by a clear failure than a hang."""
        transport = RecordedTransport(
            responses=[TimeoutError("timed out") for _ in range(3)]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=3
        )

        with pytest.raises(CatalogRetrievalError):
            source.record_lines(1919)

        assert transport.call_count == 3

    def test_an_exhausted_retry_budget_reports_the_attempts_and_the_cause(
        self, tmp_path: Path
    ) -> None:
        transport = RecordedTransport(
            responses=[TimeoutError("timed out") for _ in range(3)]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=3
        )

        with pytest.raises(CatalogRetrievalError) as excinfo:
            source.record_lines(1919)
        message = str(excinfo.value)

        assert "3 attempts" in message
        assert "www.data.jma.go.jp" in message

    def test_a_retrieval_failure_is_declared_retryable(self, tmp_path: Path) -> None:
        transport = RecordedTransport(responses=[TimeoutError("timed out")])
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError) as excinfo:
            source.record_lines(1919)

        assert excinfo.value.retryable is True


class TestArchiveShape:
    def test_the_member_is_chosen_by_being_the_only_one_not_by_name(
        self, tmp_path: Path
    ) -> None:
        """h1919.zip's member covers 1919-1950, so name-equals-year would be wrong."""
        transport = RecordedTransport(
            body=_zip_bytes(b"J" + b"1" * 95 + b"\n", member="h1919")
        )
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        assert len(list(source.record_lines(1925))) == 1

    def test_a_multi_member_archive_fails_loudly(self, tmp_path: Path) -> None:
        """If JMA ever changes the layout, guessing which member to read is worse."""
        import io as _io
        import zipfile as _zipfile

        buffer = _io.BytesIO()
        with _zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("h1919", b"J" + b"1" * 95 + b"\n")
            archive.writestr("h1920", b"J" + b"2" * 95 + b"\n")
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=RecordedTransport(body=buffer.getvalue())
        )

        with pytest.raises(CatalogRetrievalError) as excinfo:
            list(source.record_lines(1919))

        assert "exactly one file" in str(excinfo.value)


class TestRequest:
    def test_the_requested_url_follows_jmas_published_pattern(
        self, tmp_path: Path
    ) -> None:
        """Verified against the live site 2026-08-30."""
        transport = sample_transport()
        source = JmaCatalogSource(cache_dir=tmp_path, transport=transport)

        list(source.record_lines(2023))

        assert transport.requested_urls == [
            "https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h2023.zip"
        ]

    def test_the_user_agent_identifies_the_tool_and_a_contact(self) -> None:
        """Courtesy to a public data service: an unusual access pattern in
        JMA's logs should be traceable to a project rather than look anonymous.
        """
        assert "jmacat" in USER_AGENT
        assert "github.com/uonoko1/jmacat" in USER_AGENT


class TestPartialReads:
    """Streams that deliver fewer bytes per read than asked for.

    A short read is legal and routine — `HTTPResponse` returns one at every
    chunk boundary under chunked transfer-encoding — so it must never be
    mistaken for a fault in the data.
    """

    def test_a_dribbling_stream_still_downloads_the_year(self, tmp_path: Path) -> None:
        """The body is complete; only the read granularity is small.

        Read four bytes at a time from a stream that yields two, and a naive
        single `read(4)` sees b"PK", fails the magic-byte check, and reports a
        *healthy* year as permanently unavailable — the non-retryable branch,
        so the user is told to stop asking for a year that exists.
        """
        transport = RecordedTransport(
            responses=[
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=DribblingStream(SAMPLE_ZIP.read_bytes(), per_read=2),
                )
            ]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        assert len(list(source.record_lines(1919))) == 12

    def test_a_genuinely_empty_body_is_still_unavailable(self, tmp_path: Path) -> None:
        """Guard against over-correcting: a stream that ends is not a short read."""
        transport = RecordedTransport(status=200, body=b"", content_type="text/html")
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogYearUnavailableError):
            source.record_lines(1919)


class TestTruncatedTransfer:
    def test_an_incomplete_read_is_a_retrieval_failure_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        """`IncompleteRead` is an HTTPException, not an OSError.

        urllib raises it when a Content-Length is not satisfied — the ordinary
        truncated download. Guarding only `OSError` lets it escape as a raw
        non-port error, so the retry loop never sees it and the caller gets an
        exception the port never promised.
        """
        body = SAMPLE_ZIP.read_bytes()
        transport = RecordedTransport(
            responses=[
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=IncompleteReadStream(body, fail_after=len(body) // 2),
                )
            ]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError):
            source.record_lines(1919)

    def test_an_incomplete_read_leaves_nothing_in_the_cache(
        self, tmp_path: Path
    ) -> None:
        """Not even a temporary file: "never store a partial download" is absolute."""
        body = SAMPLE_ZIP.read_bytes()
        transport = RecordedTransport(
            responses=[
                Response(
                    status=200,
                    content_type="application/zip",
                    stream=IncompleteReadStream(body, fail_after=len(body) // 2),
                )
            ]
        )
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError):
            source.record_lines(1919)

        assert list(tmp_path.iterdir()) == []


class TestIterationDoesNotMaskCallerErrors:
    def test_an_exception_from_the_consumer_is_not_reported_as_a_catalog_failure(
        self, tmp_path: Path
    ) -> None:
        """The caller's own bug must not be blamed on the cache.

        The read loop's `except (BadZipFile, OSError)` sits around a `yield`,
        so an exception raised in the *caller's* loop body re-enters there. If
        it is caught, a caller whose own code raised OSError is told the JMA
        archive is corrupt — and, being a retryable error, may loop on it.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())

        lines = source.record_lines(1919)
        next(lines)

        # `throw` injects the exception at the yield, which is exactly how a
        # real caller's failure re-enters a generator it is iterating.
        assert isinstance(lines, Generator)
        with pytest.raises(OSError, match="the consumer's own failure"):
            lines.throw(OSError("the consumer's own failure"))


class TestArchiveShapeIsResolvedEagerly:
    def test_a_multi_member_archive_fails_at_the_call_not_at_first_next(
        self, tmp_path: Path
    ) -> None:
        """Availability includes "is this archive usable at all?".

        Deferring this to the first `next()` is the same failure mode the
        eager-availability contract forbids: a caller's try/except around
        `record_lines(...)` would not see it.
        """
        import io as _io
        import zipfile as _zipfile

        buffer = _io.BytesIO()
        with _zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("h1919", b"J" + b"1" * 95 + b"\n")
            archive.writestr("h1920", b"J" + b"2" * 95 + b"\n")
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=RecordedTransport(body=buffer.getvalue())
        )

        # No list(...) here: the raise must happen at the call itself.
        with pytest.raises(CatalogRetrievalError, match="exactly one file"):
            source.record_lines(1919)


class TestHandleHygiene:
    def test_an_abandoned_iterator_does_not_hold_the_archive_open(
        self, tmp_path: Path
    ) -> None:
        """Closing a partially-consumed iterator must release its handles.

        A caller that stops early — a `--limit`, a date filter past its window —
        is explicitly supported by the port, so it must not cost a file
        descriptor each time.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=sample_transport())
        list(source.record_lines(1919))  # populate the cache

        before = _open_file_count()
        iterators = []
        for _ in range(30):
            iterator = source.record_lines(1919)
            next(iterator)
            iterators.append(iterator)
        for iterator in iterators:
            assert isinstance(iterator, Generator)
            iterator.close()

        assert _open_file_count() - before == 0


def _open_file_count() -> int:
    """How many file descriptors this process holds open."""
    return len(list(Path("/proc/self/fd").iterdir()))
