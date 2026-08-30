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

from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource
from jmacat.usecase.errors import CatalogRetrievalError, PortError
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
