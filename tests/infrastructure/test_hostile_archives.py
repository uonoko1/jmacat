"""Failure paths where a *native* exception would otherwise escape the port.

Every case here is the same species of bug: a standard-library call the adapter
makes that raises something outside the guard around it. The port promises that
whatever goes wrong, the caller sees a `PortError` carrying a retryable flag —
so a `NotImplementedError` or a `zlib.error` reaching the caller is a contract
break regardless of how exotic the archive that caused it is.

The archives are built here rather than committed. They are hostile inputs, not
data: committing a ZIP whose only purpose is to expand to 200 MB, or one crafted
to look encrypted, invites a scanner to quarantine the repository.
"""

from __future__ import annotations

import io
import struct
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from jmacat.infrastructure.jma_catalog_source import (
    MAX_LINE_CHARS,
    JmaCatalogSource,
    default_cache_dir,
)
from jmacat.infrastructure.transport import Response
from jmacat.usecase.errors import (
    CatalogRetrievalError,
    CatalogYearUnavailableError,
    PortError,
)
from tests.infrastructure.recorded_transport import RecordedTransport

RECORD_BYTES = 96


def _one_member_zip(payload: bytes, *, member: str = "h1919") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, payload)
    return buffer.getvalue()


def _local_data_offset(raw: bytes | bytearray) -> int:
    """Where the first member's compressed bytes begin."""
    name_length: int = struct.unpack_from("<H", raw, 26)[0]
    extra_length: int = struct.unpack_from("<H", raw, 28)[0]
    return 30 + name_length + extra_length


def unsupported_compression_zip() -> bytes:
    """A ZIP whose central directory reads fine but whose member will not open.

    Compression method 99 is what a WinZip AES archive uses; `zipfile` reads
    the directory happily and raises `NotImplementedError` only at `open()`.
    That split is the whole point: the archive passes every check made before
    it is cached.
    """
    raw = bytearray(_one_member_zip(b"J" + b"0" * 94 + b"\n", member="h1919"))
    struct.pack_into("<H", raw, 8, 99)  # local file header
    struct.pack_into("<H", raw, raw.index(b"PK\x01\x02") + 10, 99)  # central dir
    return bytes(raw)


def encrypted_zip() -> bytes:
    """A ZIP whose member is flagged encrypted; `open()` raises `RuntimeError`."""
    raw = bytearray(_one_member_zip(b"J" + b"0" * 94 + b"\n", member="h1919"))
    struct.pack_into("<H", raw, 6, 0x1)  # general-purpose flag bit 0
    struct.pack_into("<H", raw, raw.index(b"PK\x01\x02") + 8, 0x1)
    return bytes(raw)


def corrupt_deflate_zip() -> bytes:
    """A ZIP whose member opens but whose deflate stream is damaged.

    Raises `zlib.error`, which derives from `Exception` — not from `OSError`
    and not from `BadZipFile`. Corruption is confined to the compressed data so
    the central directory still parses and the member still opens; the failure
    lands in the middle of reading, which is exactly where a caller iterating
    lines would meet it.
    """
    payload = b"".join(
        b"J" + str(index % 10).encode() * 95 + b"\n" for index in range(4000)
    )
    raw = bytearray(_one_member_zip(payload))
    start = _local_data_offset(raw)
    compressed_size: int = struct.unpack_from("<I", raw, 18)[0]
    assert compressed_size > 80, "fixture must be large enough to damage safely"
    for index in range(start + 20, start + 60):
        raw[index] ^= 0xFF
    return bytes(raw)


def unterminated_member_zip(*, expanded_bytes: int) -> bytes:
    """A small archive whose single member is `expanded_bytes` with no newline.

    The zip bomb. Every check the adapter makes before reading — magic bytes,
    central directory, exactly one member — passes, because the archive really
    is a well-formed one-member ZIP. What is hostile is the *content*: with no
    terminator anywhere, an unbounded `readline()` must materialise the entire
    expansion in one string.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("h1919", "w") as member:
            chunk = b"A" * (1024 * 1024)
            written = 0
            while written < expanded_bytes:
                count = min(len(chunk), expanded_bytes - written)
                member.write(chunk[:count])
                written += count
    return buffer.getvalue()


def _zip_transport(body: bytes) -> RecordedTransport:
    return RecordedTransport(status=200, body=body, content_type="application/zip")


class TestMembersThatWillNotOpen:
    """`zipfile.open()` raises outside `(BadZipFile, OSError)`.

    Two distinct escapes with one shared consequence: because the archive's
    central directory is intact, `_is_readable_archive` says yes and the file is
    cached. A point fix at the raise site alone would leave the cache poisoned.
    """

    @pytest.mark.parametrize(
        "build",
        [unsupported_compression_zip, encrypted_zip],
        ids=["unsupported-compression", "encrypted-member"],
    )
    def test_it_is_a_port_error_not_a_native_one(
        self, tmp_path: Path, build: Callable[[], bytes]
    ) -> None:
        body = build()
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=_zip_transport(body), max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError):
            source.record_lines(1919)

    @pytest.mark.parametrize(
        "build",
        [unsupported_compression_zip, encrypted_zip],
        ids=["unsupported-compression", "encrypted-member"],
    )
    def test_it_does_not_poison_the_cache(
        self, tmp_path: Path, build: Callable[[], bytes]
    ) -> None:
        """The promise in docs/catalog-cache.md is that damage self-corrects.

        Such an archive passes the central-directory check, so without an
        explicit discard it is cached and every later run fails identically
        *without re-downloading* — a permanent failure no re-run can clear,
        which is precisely the state the cache design exists to prevent.
        """
        transport = _zip_transport(build())
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=transport, max_attempts=1
        )

        for _ in range(3):
            with pytest.raises(CatalogRetrievalError):
                source.record_lines(1919)

        assert not source.cache_path(1919).exists(), (
            "an archive that cannot be opened must not stay in the cache"
        )
        assert transport.call_count == 3, (
            f"expected a fresh download each run, got {transport.call_count}; "
            f"the cache is poisoned"
        )
        assert not list(tmp_path.glob(".h1919.*")), "a temporary file was left behind"


class TestCorruptCompressedStream:
    def test_a_damaged_deflate_stream_is_a_port_error(self, tmp_path: Path) -> None:
        """`zlib.error` inherits from `Exception`, so `except OSError` misses it.

        This is the same species as the two above but at a different call: the
        failure happens *during* iteration, after several lines have already
        been handed to the caller.
        """
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=_zip_transport(corrupt_deflate_zip()),
            max_attempts=1,
        )

        with pytest.raises(CatalogRetrievalError):
            list(source.record_lines(1919))


class TestUnboundedLine:
    """A member with no newline must not be read into memory in one string."""

    def test_a_member_without_a_newline_is_rejected(self, tmp_path: Path) -> None:
        body = unterminated_member_zip(expanded_bytes=4 * MAX_LINE_CHARS)
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=_zip_transport(body), max_attempts=1
        )

        with pytest.raises(CatalogRetrievalError, match="line"):
            list(source.record_lines(1919))

    def test_the_rejection_happens_before_the_expansion_is_materialised(
        self, tmp_path: Path
    ) -> None:
        """The streaming guarantee, restated for a hostile input.

        A 200 MB member compresses to ~200 KB, so an unbounded `readline()`
        peaks at roughly 2,000x the bytes accepted from the network. The cap
        must hold peak memory to the same order as an ordinary read buffer,
        regardless of how far the expansion would have gone.
        """
        import tracemalloc

        expanded = 200 * 1024 * 1024
        body = unterminated_member_zip(expanded_bytes=expanded)
        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=_zip_transport(body), max_attempts=1
        )

        tracemalloc.start()
        baseline = tracemalloc.get_traced_memory()[0]
        with pytest.raises(CatalogRetrievalError):
            list(source.record_lines(1919))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert peak - baseline < 4 * 1024 * 1024, (
            f"peak {peak - baseline:,} bytes rejecting a {expanded:,}-byte "
            f"expansion from a {len(body):,}-byte archive"
        )

    def test_a_real_record_is_nowhere_near_the_cap(self, tmp_path: Path) -> None:
        """The cap must not touch real data.

        A JMA record is a documented fixed 96 bytes. Reading a year of them
        must be unaffected, and the final line without a terminator — legal at
        end of file — must still be yielded rather than mistaken for a
        truncation.
        """
        payload = b"".join(
            b"J" + str(index % 10).encode() * 95 + b"\n" for index in range(50)
        )
        payload += b"J" + b"9" * 95  # last line, no terminator
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=_zip_transport(_one_member_zip(payload)),
            max_attempts=1,
        )

        lines = list(source.record_lines(1919))

        assert len(lines) == 51
        assert all(len(line) == RECORD_BYTES for line in lines)
        assert MAX_LINE_CHARS > 100 * RECORD_BYTES, (
            "the cap must leave room for records far longer than JMA's"
        )

    def test_a_line_of_exactly_the_cap_is_not_mistaken_for_an_overrun(
        self, tmp_path: Path
    ) -> None:
        """The boundary case `readline(n)` cannot distinguish on its own.

        `readline(n)` returns exactly n characters both when it truncated a
        longer line and when the line was exactly n characters with no
        terminator. Reading one character past the cap is what tells them
        apart; without that, a legal line of exactly the cap length is rejected.
        """
        payload = b"B" * MAX_LINE_CHARS + b"\n"
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=_zip_transport(_one_member_zip(payload)),
            max_attempts=1,
        )

        assert list(source.record_lines(1919)) == ["B" * MAX_LINE_CHARS]


class TestCachePathFailures:
    """`OSError`s on the cache path itself, none of them transport failures."""

    def test_a_cache_entry_that_is_a_directory_is_reported_as_a_port_error(
        self, tmp_path: Path
    ) -> None:
        """`unlink` on a directory raises `IsADirectoryError`, not a port error.

        Reachable when something else — an archive extracted in place, a
        botched sync — leaves a directory where the archive belongs. The entry
        fails the readable-archive check, and the discard that follows blows up.
        """
        source = JmaCatalogSource(cache_dir=tmp_path, transport=_zip_transport(b""))
        source.cache_path(1919).mkdir(parents=True)

        with pytest.raises(PortError):
            source.record_lines(1919)

    def test_a_read_only_cache_directory_is_reported_as_a_port_error(
        self, tmp_path: Path
    ) -> None:
        """A corrupt entry in a directory that cannot be written to.

        The discard fails with `PermissionError`. Before this guard the user
        was stuck permanently, with no fetch even attempted and a raw `OSError`
        instead of a message naming the cache.
        """
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "h1919.zip").write_bytes(b"not a zip at all")
        cache.chmod(0o500)
        try:
            source = JmaCatalogSource(cache_dir=cache, transport=_zip_transport(b""))
            with pytest.raises(PortError):
                source.record_lines(1919)
        finally:
            cache.chmod(0o700)

    def test_a_cache_directory_that_is_a_regular_file_is_reported_as_a_port_error(
        self, tmp_path: Path
    ) -> None:
        """`JMACAT_CACHE_DIR` pointed at a file: `mkdir` raises `FileExistsError`.

        An easy mistake to make from a shell and, before this guard, an
        immediate non-port crash on the very first fetch.
        """
        not_a_directory = tmp_path / "jmacat"
        not_a_directory.write_bytes(b"")
        transport = _zip_transport(_one_member_zip(b"J" + b"0" * 95 + b"\n"))
        source = JmaCatalogSource(
            cache_dir=not_a_directory, transport=transport, max_attempts=3
        )

        with pytest.raises(PortError) as caught:
            source.record_lines(1919)

        assert str(not_a_directory) in str(caught.value)
        assert transport.call_count == 0, (
            "a directory that cannot be created will not become creatable on "
            "the next attempt, so nothing should have been fetched"
        )
        assert "network access" not in str(caught.value), (
            "a local misconfiguration must not be reported as a network problem"
        )


class TestEmptyArchive:
    """A valid ZIP with zero members is a broken archive, not an unpublished year."""

    def test_it_is_not_reported_with_the_publication_lag_explanation(
        self, tmp_path: Path
    ) -> None:
        """A zero-member ZIP starts `PK\\x05\\x06`, so the magic check rejects it.

        Classifying it as unavailable is defensible — a server serving an empty
        archive is arguably saying there is nothing there — but the *message*
        is not: it tells the user JMA has not published the year yet, which for
        1919 is plainly false and sends them to check a publication table that
        will contradict it. A dir-only ZIP already gets the right treatment via
        `_single_member`; an empty one must not be worse off.
        """
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        body = empty.getvalue()
        assert body.startswith(b"PK\x05\x06")

        source = JmaCatalogSource(
            cache_dir=tmp_path, transport=_zip_transport(body), max_attempts=1
        )

        with pytest.raises(CatalogYearUnavailableError) as caught:
            source.record_lines(1919)

        assert "does not exist yet" not in str(caught.value)
        assert "lag" not in str(caught.value)
        assert "empty" in str(caught.value).lower()

    def test_a_body_that_is_not_a_zip_at_all_keeps_the_lag_explanation(
        self, tmp_path: Path
    ) -> None:
        """Guard against over-correcting.

        The HTML error page — the case the lag message was written for — must
        still get it. Narrowing the message for empty archives must not narrow
        it for the common case.
        """
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=RecordedTransport(
                status=200, body=b"<html>no such file</html>", content_type="text/html"
            ),
            max_attempts=1,
        )

        with pytest.raises(CatalogYearUnavailableError) as caught:
            source.record_lines(2024)

        assert "lag" in str(caught.value)


class TestFoundBySweepingTheRestOfTheModule:
    """Same species as the rest of this file, found by enumerating every call.

    Not reported in review. Listed together because what they have in common is
    the finding, not the symptom: an unguarded standard-library call raising
    something the port never promised.
    """

    def test_a_directory_appearing_under_the_archive_name_is_a_port_error(
        self, tmp_path: Path
    ) -> None:
        """The rename is atomic, not infallible.

        `_ensure_cached` clears an unusable entry before the download starts,
        so the only way to reach `replace` with a directory in the way is for
        one to appear in the window between that check and the rename. Narrow,
        but it is the atomic-write path, whose whole purpose is that nothing is
        left behind however it fails.
        """
        body = _one_member_zip(b"J" + b"0" * 95 + b"\n")

        class PlantsADirectory(RecordedTransport):
            """Creates the obstacle mid-download, inside the TOCTOU window."""

            def fetch(self, url: str, *, timeout: float) -> Response:
                (tmp_path / "h1919.zip").mkdir(exist_ok=True)
                return super().fetch(url, timeout=timeout)

        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=PlantsADirectory(
                status=200, body=body, content_type="application/zip"
            ),
            max_attempts=1,
        )

        with pytest.raises(PortError):
            source.record_lines(1919)

        assert not list(tmp_path.glob(".h1919.*")), (
            "the temporary file must not survive a failed rename"
        )

    def test_a_cleanup_failure_does_not_replace_the_real_diagnosis(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Removing the partial file must not become the reported failure.

        Every cleanup here runs while a failure is already being reported. A
        `PermissionError` from the cleanup would replace the message explaining
        what actually went wrong — strictly worse than a stray temporary file,
        which at least carries a `.partial` suffix and can never be mistaken
        for a cache entry.

        The cleanup is made to fail directly rather than by a read-only
        directory, which would trip the write itself and never reach here.
        """
        original_unlink = Path.unlink

        def refuse(self: Path, *args: object, **kwargs: object) -> None:
            if self.name.endswith(".partial"):
                raise PermissionError(13, "Permission denied", str(self))
            original_unlink(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "unlink", refuse)
        source = JmaCatalogSource(
            cache_dir=tmp_path,
            transport=_zip_transport(b"PK\x03\x04 not really an archive"),
            max_attempts=1,
        )

        with caplog.at_level("WARNING"):
            with pytest.raises(CatalogRetrievalError) as caught:
                source.record_lines(1919)

        assert "did not open as a valid ZIP" in str(caught.value)
        assert "Permission" not in str(caught.value)
        assert any("temporary file" in record.message for record in caplog.records), (
            "a leftover temporary file must still be logged, not silently ignored"
        )

    def test_an_unresolvable_home_directory_is_a_port_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`expanduser()` raises `RuntimeError`, which is not an `OSError`.

        Reachable wherever `~` cannot be resolved — no `HOME` and no passwd
        entry for the uid, ordinary in a container or under an HPC batch
        scheduler. A bare `RuntimeError` from a function whose job is to name a
        path tells the user nothing about which variable to set.
        """
        monkeypatch.setenv("JMACAT_CACHE_DIR", "~nosuchuser12345/jmacat")

        with pytest.raises(PortError, match="JMACAT_CACHE_DIR"):
            default_cache_dir()
