"""`CatalogSource` over JMA's published yearly hypocenter archives.

Fetches `h{year}.zip` from the JMA bulletin site, caches it, and streams its
records line by line.

Verified against the live site on 2026-08-30:

- `h2023.zip` -> 200, 6,977,812 bytes, one member of 24,930,940 bytes /
  257,020 lines, every line exactly 96 bytes.
- `h2024.zip` -> 404 with a 2,203-byte `text/html` body. The finalized catalog
  lags several years behind the present.
"""

from __future__ import annotations

import http.client
import io
import logging
import lzma
import os
import shutil
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Final

from jmacat.infrastructure.transport import Transport, UrllibTransport
from jmacat.usecase.errors import CatalogRetrievalError, CatalogYearUnavailableError

logger = logging.getLogger(__name__)

#: JMA publishes one archive per year at a stable path. Verified 2026-08-30.
URL_TEMPLATE: Final = (
    "https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h{year}.zip"
)

#: `PK\x03\x04` — the local file header signature every non-empty ZIP starts
#: with (APPNOTE.TXT 4.3.7). Checked against the first bytes of the body so an
#: HTML error page can never be handed to `zipfile` and reported as a corrupt
#: archive; the user-visible truth is that the year is not published.
ZIP_MAGIC: Final = b"PK\x03\x04"

#: `PK\x05\x06` — the end-of-central-directory signature. A ZIP with *no*
#: members consists of nothing else, so it starts with this rather than with a
#: local file header and fails the check above. It is still a valid ZIP, and
#: saying so changes only the message the user reads; see `_unavailable`.
EMPTY_ZIP_MAGIC: Final = b"PK\x05\x06"

#: 64 KiB: large enough that a ~7 MB archive is a low four-figure number of
#: reads, small enough that peak memory stays flat regardless of archive size.
CHUNK_BYTES: Final = 64 * 1024

#: Every way a transfer can fail mid-flight. `http.client.IncompleteRead` is
#: listed explicitly because it is an `HTTPException`, *not* an `OSError` — it
#: is what urllib raises when a Content-Length is not satisfied, i.e. the
#: ordinary truncated download. Catching only `OSError` lets the single most
#: likely truncation escape as a non-port error and strand a partial file.
TRANSFER_FAILURES: Final = (OSError, http.client.HTTPException)

#: Every way `zipfile` can refuse an archive whose central directory parsed.
#:
#: `except (BadZipFile, OSError)` is the guard that looks right and is not. The
#: central directory is a *table of contents*: reading it proves the file is a
#: ZIP and names its members, and nothing more. Everything that can be wrong
#: with the member itself surfaces later, at `open()` or mid-read, and almost
#: none of it arrives as an `OSError`:
#:
#: - `NotImplementedError` — a compression method this build cannot inflate
#:   (method 99 is WinZip AES, common enough to meet in the wild).
#: - `RuntimeError` — an encrypted member, refused for want of a password.
#: - `zlib.error` / `lzma.LZMAError` — a damaged compressed stream, raised
#:   part-way through reading, after lines have already been handed to the
#:   caller. (bz2 reports the same condition as `OSError`, which is why the
#:   family is not uniform and why guessing at it does not work.)
#: - `EOFError` — a decompressor asked to continue past a stream that ended.
#: - `ValueError` — reading from a member handle closed underneath us.
#:
#: All of them mean the same thing to a user: this archive cannot be read.
#: Enumerating them here rather than at each call site is what stops the next
#: one from escaping as a native exception the port never promised.
ARCHIVE_FAILURES: Final = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    NotImplementedError,
    RuntimeError,
    zlib.error,
    lzma.LZMAError,
    EOFError,
    ValueError,
    OSError,
)

#: The longest line the reader will assemble, in characters.
#:
#: Without a bound, `readline()` reads until it finds a terminator — so a member
#: containing no newline at all is read into a single string, and the streaming
#: guarantee this adapter is built around evaporates. That is not hypothetical:
#: a 204 KB archive expanding to 200 MB of one character peaks at ~2,000x the
#: bytes accepted from the network, and the archive passes the magic-byte check,
#: the central-directory check and the single-member check on the way in.
#:
#: 64 KiB is chosen as *unmistakably* over-generous rather than tight. A JMA
#: record is a documented fixed 96 bytes (docs/jma-hypocenter-format.md), so the
#: cap sits ~680x above the only line length the format defines — no plausible
#: revision of it, nor a hand-edited file with a long comment or a merged pair
#: of records, comes close. Deliberately not sized to the record: a cap near
#: 96 would turn a benign format change into data loss, whereas this one can
#: only fire on input that is not the JMA catalog. It is also, conveniently,
#: the same order as `CHUNK_BYTES`, so the memory ceiling is unchanged.
MAX_LINE_CHARS: Final = 64 * 1024

DEFAULT_TIMEOUT_SECONDS: Final = 30.0

#: Three attempts total. A transient JMA hiccup usually clears on the first
#: retry; beyond a handful, a researcher is better served by a clear failure
#: than by a command that appears to hang. Only `CatalogRetrievalError` is
#: retried — an unpublished year is not going to appear mid-run.
DEFAULT_MAX_ATTEMPTS: Final = 3

#: Where the cache lives when the caller says nothing. Honours
#: `JMACAT_CACHE_DIR`, then `XDG_CACHE_HOME`, then `~/.cache`, so a researcher
#: on a shared machine can point it at scratch space without code changes.
CACHE_ENV_VAR: Final = "JMACAT_CACHE_DIR"


def default_cache_dir() -> Path:
    """The cache directory used when none is passed explicitly.

    Resolution only — nothing here touches the filesystem. Whether the
    directory exists, is writable, or is a file is settled by
    `_ensure_cache_dir` at the moment it matters; checking it here as well
    would do I/O in a resolver and still race with the `mkdir` that follows.

    What *is* checked here is that the path can be resolved at all. Both
    `expanduser()` and `Path.home()` raise `RuntimeError` when a `~` cannot be
    resolved — no `HOME` and no passwd entry for the uid, which is ordinary in
    a container or under some HPC batch schedulers. Unguarded that surfaces as
    a bare `RuntimeError` from a function whose job is to name a path, with
    nothing to tell the user which of the three environment variables to set.
    """
    override = os.environ.get(CACHE_ENV_VAR)
    try:
        if override:
            return Path(override).expanduser()
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    except RuntimeError as error:
        raise CatalogRetrievalError(
            f"The default cache directory could not be determined: {error}. "
            f"This happens when a path starts with '~' and no home directory "
            f"can be resolved. Set {CACHE_ENV_VAR} to an absolute path."
        ) from error
    return base / "jmacat"


class JmaCatalogSource:
    """Fetches, caches and streams one year of the JMA hypocenter catalog.

    Implements `jmacat.usecase.ports.catalog_source.CatalogSource`.
    """

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        url_template: str = URL_TEMPLATE,
    ) -> None:
        self._cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._transport = transport if transport is not None else UrllibTransport()
        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._url_template = url_template

    # -- the port ---------------------------------------------------------

    def record_lines(self, year: int) -> Iterator[str]:
        """Return an iterator over `year`'s raw record lines.

        **Deliberately not a generator function.** Availability is resolved
        here, eagerly — the archive is fetched (or found in the cache) and
        verified before this returns — and only the line-by-line reading is
        deferred to the generator handed back. A `yield` anywhere in this body
        would make the whole method a generator function, so calling it would
        run none of this and a 404 would surface at the caller's first
        `next()`, indistinguishable from a year with no earthquakes.

        `jmacat.usecase.ports.contract.check_unavailable_year_fails_eagerly`
        enforces this, and the adapter's test suite runs it.
        """
        archive = self._ensure_cached(year)  # raises here, at the call site
        return self._open_lines(archive, year)

    # -- availability, resolved eagerly ------------------------------------

    def _ensure_cached(self, year: int) -> Path:
        """Return the path to a verified local archive for `year`.

        A cached file is reused only if it still opens as a ZIP, so a download
        interrupted by Ctrl-C or a full disk is re-fetched rather than being
        served as a permanently broken cache entry.
        """
        cached = self.cache_path(year)
        if self._exists(cached):
            if self._is_readable_archive(cached):
                logger.debug("Using cached JMA archive for %d at %s", year, cached)
                return cached
            logger.warning(
                "Cached JMA archive for %d at %s is corrupt or truncated; "
                "discarding it and re-downloading.",
                year,
                cached,
            )
            self._discard(cached, year)

        self._ensure_cache_dir(year)
        self._download(year, cached)
        return cached

    def _ensure_cache_dir(self, year: int) -> None:
        """Create the cache directory, or explain why it cannot exist.

        `exist_ok=True` forgives a directory that is already there; it does not
        forgive a *regular file* sitting where the directory belongs, which is
        `FileExistsError` — what a user who pointed `JMACAT_CACHE_DIR` at a file
        hits on their first fetch. `PermissionError` on an unwritable parent
        lands here too. Neither is a transport failure, and unguarded both
        escape as non-port exceptions.

        Done here, before the retry loop, rather than inside `_write_atomically`
        where the `mkdir` used to live. A directory that cannot be created will
        not become creatable on the second attempt, so retrying is pure delay —
        and worse, the loop's exhaustion message blames the network and tells
        the user to check their connection to www.data.jma.go.jp for what is a
        local misconfiguration.
        """
        directory = self._cache_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise CatalogRetrievalError(
                f"The cache directory {directory} could not be created or used "
                f"while fetching year {year}: {error}. Check that it is a "
                f"writable directory, or set JMACAT_CACHE_DIR to one that is."
            ) from error

    @staticmethod
    def _exists(path: Path) -> bool:
        """`Path.exists`, treating an unstattable path as absent.

        `exists()` is documented to swallow `OSError` for a path that merely is
        not there, but it still raises for one the OS refuses to stat at all —
        a component longer than NAME_MAX, an unreadable parent directory. That
        is a cache problem, not a reason to crash before a fetch is attempted,
        and reporting "not cached" sends it down the download path where the
        same condition surfaces with a message that names the cache.
        """
        try:
            return path.exists()
        except OSError:
            return False

    def _discard(self, cached: Path, year: int) -> None:
        """Remove a cache entry that must not be served, or say why it cannot be.

        `unlink` is not the safe no-op it looks like. A *directory* under the
        archive's name raises `IsADirectoryError`; a read-only cache directory
        holding a corrupt entry raises `PermissionError`. Both are `OSError`s
        with nothing to do with the transport, and unguarded both escape as
        non-port exceptions — leaving the user permanently stuck, with no fetch
        even attempted and no message naming the cache they need to clear.

        Not retryable in the sense that matters: re-running changes nothing
        until the user intervenes. It is still a `CatalogRetrievalError`,
        because the alternative type would tell them JMA has not published the
        year, which is false and points them away from the actual fix.
        """
        try:
            cached.unlink(missing_ok=True)
        except OSError as error:
            raise CatalogRetrievalError(
                f"The cached JMA archive for year {year} at {cached} cannot be "
                f"used and could not be removed: {error}. Delete it by hand — "
                f"or point JMACAT_CACHE_DIR somewhere writable — and re-run."
            ) from error

    def cache_path(self, year: int) -> Path:
        """Where `year`'s archive is cached. Public so a CLI can report it."""
        return self._cache_dir / f"h{year}.zip"

    def _download(self, year: int, destination: Path) -> None:
        """Fetch `year`'s archive into `destination`, retrying retryable errors."""
        url = self._url_template.format(year=year)
        last_error: CatalogRetrievalError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                self._download_once(year, url, destination)
            except CatalogRetrievalError as error:
                # Only this class is retried. CatalogYearUnavailableError is not
                # caught here at all, so it propagates on the first attempt:
                # waiting will not make JMA publish the year.
                last_error = error
                logger.warning(
                    "Attempt %d/%d to fetch %s failed: %s",
                    attempt,
                    self._max_attempts,
                    url,
                    error,
                )
            else:
                return

        assert last_error is not None  # the loop runs at least once
        raise CatalogRetrievalError(
            f"Could not retrieve the JMA catalog for year {year} from {url} "
            f"after {self._max_attempts} attempts. Last failure: {last_error}. "
            f"This looks transient (timeout, connection reset or a server "
            f"error), so retrying later is worthwhile; if it persists, check "
            f"network access to www.data.jma.go.jp."
        ) from last_error

    def _download_once(self, year: int, url: str, destination: Path) -> None:
        """One attempt: fetch, classify, verify, and write atomically."""
        try:
            response = self._transport.fetch(url, timeout=self._timeout)
        except TRANSFER_FAILURES as error:
            # Timeouts, resets and DNS failures arrive as OSError. But not
            # everything urllib lets out of `urlopen` is one:
            # `AbstractHTTPHandler.do_open` wraps `h.request(...)` in
            # `except OSError` and then calls `h.getresponse()` *outside* that
            # wrap, so every `http.client.HTTPException` raised while reading
            # the status line and headers propagates unwrapped —
            # `BadStatusLine` from a broken proxy or a captive portal answering
            # in its own protocol, `LineTooLong`, `InvalidURL`.
            # `RemoteDisconnected` happens to be safe only because it is also a
            # `ConnectionResetError`; its siblings are not. All of them are
            # transport trouble and say nothing about publication, so they are
            # retryable retrieval failures — the same bucket, reached through
            # the same tuple used everywhere else a transfer can fail.
            raise CatalogRetrievalError(
                f"Could not reach {url} while fetching the JMA catalog for "
                f"year {year}: {error}"
            ) from error

        # `closing`, not `with response.stream`: `IO[bytes]` guarantees
        # `close()` but not `__enter__`, and the transport's HTTPError path
        # hands back an object whose context-manager behaviour is incidental
        # rather than promised. Closing it explicitly is what the type actually
        # supports, and it still releases the connection on every path below.
        with closing(response.stream) as body:
            self._classify_status(year, url, response.status)
            head = self._read_exactly(body, len(ZIP_MAGIC), year=year, url=url)
            self._verify_archive_magic(year, url, head, response.content_type)
            self._write_atomically(year, url, destination, head, body)

    def _classify_status(self, year: int, url: str, status: int) -> None:
        """Apply the errors module's classification table to a status code.

        The table is the port's decision, not this adapter's; it is followed
        here rather than re-derived.
        """
        if status == 404:
            raise self._unavailable(year, url, reason="returned HTTP 404")
        if status >= 500:
            raise CatalogRetrievalError(
                f"JMA returned HTTP {status} for {url} while fetching year "
                f"{year}. This is a server-side problem and says nothing about "
                f"whether the year exists, so it is worth retrying."
            )
        if status != 200:
            raise CatalogRetrievalError(
                f"JMA returned an unexpected HTTP {status} for {url} while "
                f"fetching year {year}."
            )

    def _verify_archive_magic(
        self, year: int, url: str, head: bytes, content_type: str
    ) -> None:
        """Reject a body that is not a ZIP, however it was served.

        A 200 whose body is HTML is classified as *unavailable*, not as a
        retrieval failure: a server answering a request for `h{year}.zip` with
        a page is saying there is no such archive, and whether it says so with
        a 404 or a 200 error page is a detail of its configuration. See the
        classification table in `jmacat.usecase.errors`.
        """
        if head.startswith(ZIP_MAGIC):
            return
        if head.startswith(EMPTY_ZIP_MAGIC):
            # A valid ZIP containing zero members. Classifying it as
            # unavailable is right — a server handing back an empty archive is
            # saying there is nothing in it — but the publication-lag
            # explanation is not: it would tell a user asking for 1919 that
            # JMA "has not published it yet" and send them to a table that says
            # otherwise. Same class, different reason, so the message says what
            # was actually seen.
            raise self._unavailable(
                year,
                url,
                reason="returned an empty ZIP archive, containing no files",
                explain_publication_lag=False,
            )
        raise self._unavailable(
            year,
            url,
            reason=(
                f"returned a non-archive body (Content-Type "
                f"{content_type or 'unknown'!s}, starting {head!r}) instead of "
                f"a ZIP"
            ),
        )

    def _unavailable(
        self,
        year: int,
        url: str,
        *,
        reason: str,
        explain_publication_lag: bool = True,
    ) -> CatalogYearUnavailableError:
        """The one place the user-facing "year not published" message is built.

        It names the year and the URL and says what was observed. It normally
        also explains the publication lag — a user who asks for 2024 should
        learn *why* it is missing and what to do, not just see "404".

        `explain_publication_lag=False` for the observations the lag does not
        explain. The lag text is a diagnosis, not a decoration: attaching it to
        an empty archive tells a user asking for 1919 that the year "does not
        exist yet", which is false and points them at a publication table that
        will contradict it. Better to say only what was seen than to volunteer
        a confident wrong cause.
        """
        detail = (
            "JMA's finalized hypocenter catalog is published with a lag of "
            "several years, so recent years do not exist yet — this is "
            "expected, not a fault in your setup or network. Check "
            "https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html for the "
            "latest published year, and request a year at or below it."
            if explain_publication_lag
            else "Check "
            "https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html to "
            "confirm what JMA publishes for this year; if it is listed there, "
            "the served archive is at fault and re-running later may help."
        )
        return CatalogYearUnavailableError(
            year,
            f"The JMA catalog for year {year} is not available: {url} "
            f"{reason}. {detail}",
        )

    # -- reading -----------------------------------------------------------

    def _read_exactly(
        self, body: IO[bytes], count: int, *, year: int, url: str
    ) -> bytes:
        """Read up to `count` bytes, looping until they arrive or the body ends.

        A single `read(count)` is *not* enough. Returning fewer bytes than
        asked for is legal and routine — `HTTPResponse` does it at every chunk
        boundary under chunked transfer-encoding — so a one-shot read can hand
        back `b"PK"` from a perfectly healthy archive. That fails the
        magic-byte check, and a real year is then reported as permanently
        unavailable: the non-retryable branch, telling the user to stop asking
        for a year that exists. Short reads are a property of the transport,
        never evidence about publication.

        Returns short only at a genuine end of body, which the caller is left
        to judge — an empty or 2-byte body really is not an archive.
        """
        chunks: list[bytes] = []
        remaining = count
        try:
            while remaining > 0:
                chunk = body.read(remaining)
                if not chunk:  # end of body, not a short read
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except TRANSFER_FAILURES as error:
            raise CatalogRetrievalError(
                f"The transfer of {url} for year {year} failed while reading "
                f"the response: {error}"
            ) from error
        return b"".join(chunks)

    def _write_atomically(
        self,
        year: int,
        url: str,
        destination: Path,
        head: bytes,
        body: IO[bytes],
    ) -> None:
        """Stream the body to a temporary file, then rename it into place.

        The rename is what keeps the cache honest: a partial download is never
        visible under the cache path, so an interrupted run cannot leave behind
        a truncated file that a later run would mistake for a complete archive.
        `Path.replace` is atomic within a filesystem, and the temporary file is
        created in the cache directory so the rename never crosses one.
        """
        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".h{year}.",
                suffix=".partial",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(head)
                shutil.copyfileobj(body, tmp, CHUNK_BYTES)
        except TRANSFER_FAILURES as error:
            self._remove_quietly(tmp_path)
            raise CatalogRetrievalError(
                f"The transfer of {url} for year {year} failed before the "
                f"archive was complete: {error}. Nothing was written to the "
                f"cache, so re-running will start a fresh download."
            ) from error

        assert tmp_path is not None
        if not self._is_readable_archive(tmp_path):
            self._remove_quietly(tmp_path)
            raise CatalogRetrievalError(
                f"The archive downloaded from {url} for year {year} did not "
                f"open as a valid ZIP; the transfer was probably truncated. "
                f"Nothing was cached, so re-running will download it again."
            )
        try:
            tmp_path.replace(destination)
        except OSError as error:
            # The rename is atomic, not infallible. `_ensure_cached` clears an
            # unusable entry before the download starts, but a *directory* can
            # appear under the archive's name in the window between that check
            # and this rename — a concurrent extraction, another tool — and
            # then `replace` raises `IsADirectoryError`. Report it against the
            # cache, and take the temporary file with us: leaving it behind
            # would contradict the "not even a stray temporary file" promise
            # this method exists to keep.
            self._remove_quietly(tmp_path)
            raise CatalogRetrievalError(
                f"The archive for year {year} was downloaded but could not be "
                f"moved into place at {destination}: {error}. Check what "
                f"occupies that path; nothing was cached."
            ) from error

    @staticmethod
    def _remove_quietly(path: Path | None) -> None:
        """Delete a temporary file, never raising in place of a real diagnosis.

        Every call site is already reporting a failure. If the cleanup itself
        raises — a read-only cache directory, a path that is not a file — the
        `PermissionError` would replace the message explaining what actually
        went wrong, which is strictly worse than a stray temporary file. The
        leftover is logged rather than silently swallowed, so it is still
        discoverable; and it cannot be mistaken for a cache entry, since it
        carries the `.partial` suffix and never the archive's name.
        """
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("Could not remove the temporary file %s: %s", path, error)

    @staticmethod
    def _is_readable_archive(path: Path) -> bool:
        """True when `path` opens as a ZIP with at least one member.

        Only the central directory is read, which is at the end of the file —
        so this is cheap and, crucially, a truncated download fails it.
        """
        try:
            with zipfile.ZipFile(path) as archive:
                return bool(archive.namelist())
        except ARCHIVE_FAILURES:
            return False

    def _open_lines(self, archive_path: Path, year: int) -> Iterator[str]:
        """Open the archive, validate its shape, and return a line generator.

        Deliberately not a generator function, for the same reason
        `record_lines` is not: opening the archive and finding its single
        member are availability questions, and a `yield` here would defer them
        to the caller's first `next()` — past any `try`/`except` around the
        call site.
        """
        try:
            archive = zipfile.ZipFile(archive_path)
        except ARCHIVE_FAILURES as error:
            self._discard(archive_path, year)
            raise self._unreadable(archive_path, year, error) from error

        try:
            member = self._single_member(archive, archive_path, year)
            raw = archive.open(member)
        except ARCHIVE_FAILURES as error:
            archive.close()
            # Discard, and this is the case that most needs it. An archive
            # whose member will not open — an unsupported compression method,
            # an encrypted member — has an intact central directory, so
            # `_is_readable_archive` says yes and it is cached. Left there, it
            # fails identically on every later run *without re-downloading*:
            # a permanent failure that no amount of re-running clears, which is
            # exactly what docs/catalog-cache.md promises cannot happen.
            self._discard(archive_path, year)
            raise self._unreadable(archive_path, year, error) from error
        except BaseException:
            archive.close()
            raise

        return self._iterate(archive, raw, archive_path, year)

    def _iterate(
        self,
        archive: zipfile.ZipFile,
        raw: IO[bytes],
        archive_path: Path,
        year: int,
    ) -> Iterator[str]:
        """Yield the member's lines, closing every handle on any exit.

        The `try` wraps only the *reads*, never the `yield`. A `try` around the
        yield would catch exceptions raised in the caller's own loop body —
        they re-enter the generator at the yield point — and re-raise them as
        "the cached JMA archive could not be read", blaming a healthy file for
        the caller's bug and inviting a retry loop over it.

        `finally` rather than `with`, so the handles are released whether the
        archive is exhausted, the caller abandons the iterator (GeneratorExit
        on close), or a read fails.
        """
        # The records are ASCII (docs/jma-hypocenter-format.md).
        # `errors="replace"` is chosen over the default `strict`: a stray byte
        # in one record must not abort a 257,000-line run with an opaque
        # UnicodeDecodeError. The replacement character survives into the line,
        # so the domain parser rejects that one record loudly while the rest
        # proceed. `newline=""` leaves line splitting to the wrapper without
        # translating terminators; the terminator is stripped below, as the
        # port requires.
        text = io.TextIOWrapper(raw, encoding="ascii", errors="replace", newline="")
        try:
            while True:
                try:
                    # Bounded, and asking for one character *past* the cap.
                    # The cap alone cannot tell an over-long line from a legal
                    # one: `readline(n)` returns exactly n characters both when
                    # it gave up mid-line and when the line was n characters
                    # long. Reading n+1 makes the terminator the discriminator
                    # instead of the length — a line the reader saw the end of
                    # comes back with its "\n", and one it did not does not.
                    line = text.readline(MAX_LINE_CHARS + 1)
                except ARCHIVE_FAILURES as error:
                    raise self._unreadable(archive_path, year, error) from error
                if not line:
                    return
                if len(line) > MAX_LINE_CHARS and not line.endswith("\n"):
                    # Not `len(line) > MAX_LINE_CHARS` on its own: a legal line
                    # of exactly the cap *plus* its terminator is one character
                    # over and perfectly fine. The unterminated case is the
                    # only one where the reader stopped because it hit the cap
                    # rather than because the line ended.
                    #
                    # A final line at end of file legitimately has no
                    # terminator, but it cannot reach here: to be this long it
                    # would have to exceed the cap, which the format does not
                    # allow, and a shorter one fails the length test first.
                    raise self._overlong_line(archive_path, year)
                yield line.rstrip("\r\n")
        finally:
            text.close()  # closes `raw` too
            archive.close()

    def _overlong_line(self, archive_path: Path, year: int) -> CatalogRetrievalError:
        """A line longer than the cap: not the JMA catalog, whatever else it is.

        Raised rather than truncated. Silently splitting an over-long line
        would hand the domain parser two half-records that might individually
        look plausible, which is the quiet wrong answer CONTRIBUTING's "fail
        loudly" rule exists to prevent.
        """
        return CatalogRetrievalError(
            f"A line in the JMA archive for year {year} at {archive_path} "
            f"exceeded {MAX_LINE_CHARS:,} characters without a terminator. A "
            f"JMA record is 96 bytes, so this file is not the published "
            f"catalog — it is corrupt, or it is some other archive under that "
            f"name. Delete it and re-run to download a fresh copy."
        )

    def _unreadable(
        self, archive_path: Path, year: int, error: Exception
    ) -> CatalogRetrievalError:
        return CatalogRetrievalError(
            f"The cached JMA archive for year {year} at {archive_path} could "
            f"not be read: {error}. Delete it and re-run to download a fresh "
            f"copy."
        )

    @staticmethod
    def _single_member(
        archive: zipfile.ZipFile, archive_path: Path, year: int
    ) -> zipfile.ZipInfo:
        """The archive's one data member.

        JMA ships exactly one file per archive (`h2023.zip` -> `h2023`), but
        the member is selected by being the only one rather than by name: the
        1919 archive's member covers 1919-1950, so a name-equals-year rule
        would be wrong for it.
        """
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) != 1:
            raise CatalogRetrievalError(
                f"Expected exactly one file inside the JMA archive for year "
                f"{year} at {archive_path}, found {len(members)}: "
                f"{[info.filename for info in members]}."
            )
        return members[0]
