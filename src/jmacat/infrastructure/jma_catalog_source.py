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

import io
import logging
import os
import shutil
import zipfile
from collections.abc import Iterator
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

#: 64 KiB: large enough that a ~7 MB archive is a low four-figure number of
#: reads, small enough that peak memory stays flat regardless of archive size.
CHUNK_BYTES: Final = 64 * 1024

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
    """The cache directory used when none is passed explicitly."""
    override = os.environ.get(CACHE_ENV_VAR)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
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
        return self._stream_lines(archive, year)

    # -- availability, resolved eagerly ------------------------------------

    def _ensure_cached(self, year: int) -> Path:
        """Return the path to a verified local archive for `year`.

        A cached file is reused only if it still opens as a ZIP, so a download
        interrupted by Ctrl-C or a full disk is re-fetched rather than being
        served as a permanently broken cache entry.
        """
        cached = self.cache_path(year)
        if cached.exists():
            if self._is_readable_archive(cached):
                logger.debug("Using cached JMA archive for %d at %s", year, cached)
                return cached
            logger.warning(
                "Cached JMA archive for %d at %s is corrupt or truncated; "
                "discarding it and re-downloading.",
                year,
                cached,
            )
            cached.unlink(missing_ok=True)

        self._download(year, cached)
        return cached

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
        except OSError as error:
            # Timeouts, resets and DNS failures all arrive as OSError. The
            # errors module classifies these as retryable retrieval failures.
            raise CatalogRetrievalError(
                f"Could not reach {url} while fetching the JMA catalog for "
                f"year {year}: {error}"
            ) from error

        with response.stream as body:
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
        self, year: int, url: str, *, reason: str
    ) -> CatalogYearUnavailableError:
        """The one place the user-facing "year not published" message is built.

        It names the year and the URL, says what was observed, and explains the
        publication lag — a user who asks for 2024 should learn *why* it is
        missing and what to do, not just see "404".
        """
        return CatalogYearUnavailableError(
            year,
            f"The JMA catalog for year {year} is not available: {url} {reason}. "
            f"JMA's finalized hypocenter catalog is published with a lag of "
            f"several years, so recent years do not exist yet — this is "
            f"expected, not a fault in your setup or network. Check "
            f"https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html for the "
            f"latest published year, and request a year at or below it.",
        )

    # -- reading -----------------------------------------------------------

    def _read_exactly(
        self, body: IO[bytes], count: int, *, year: int, url: str
    ) -> bytes:
        """Read `count` bytes, translating a transport failure mid-read."""
        try:
            return body.read(count)
        except OSError as error:
            raise CatalogRetrievalError(
                f"The transfer of {url} for year {year} failed while reading "
                f"the response: {error}"
            ) from error

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
        `os.replace` is atomic within a filesystem, and the temporary file is
        created in the cache directory so the rename never crosses one.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
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
        except OSError as error:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise CatalogRetrievalError(
                f"The transfer of {url} for year {year} failed before the "
                f"archive was complete: {error}. Nothing was written to the "
                f"cache, so re-running will start a fresh download."
            ) from error

        assert tmp_path is not None
        if not self._is_readable_archive(tmp_path):
            tmp_path.unlink(missing_ok=True)
            raise CatalogRetrievalError(
                f"The archive downloaded from {url} for year {year} did not "
                f"open as a valid ZIP; the transfer was probably truncated. "
                f"Nothing was cached, so re-running will download it again."
            )
        tmp_path.replace(destination)

    @staticmethod
    def _is_readable_archive(path: Path) -> bool:
        """True when `path` opens as a ZIP with at least one member.

        Only the central directory is read, which is at the end of the file —
        so this is cheap and, crucially, a truncated download fails it.
        """
        try:
            with zipfile.ZipFile(path) as archive:
                return bool(archive.namelist())
        except (zipfile.BadZipFile, OSError):
            return False

    def _stream_lines(self, archive_path: Path, year: int) -> Iterator[str]:
        """Yield the archive's record lines, one at a time.

        Constant memory: `ZipFile.open` gives a decompressing stream, wrapped in
        a `TextIOWrapper` that decodes and splits lines incrementally, so at no
        point is more than a buffer plus one line held. The 25 MB expanded file
        is never materialised.
        """
        try:
            with zipfile.ZipFile(archive_path) as archive:
                member = self._single_member(archive, archive_path, year)
                with archive.open(member) as raw:
                    # The records are ASCII (docs/jma-hypocenter-format.md).
                    # `errors="replace"` is chosen over the default `strict`:
                    # a stray byte in one record must not abort a 257,000-line
                    # run with an opaque UnicodeDecodeError. The replacement
                    # character survives into the line, so the domain parser
                    # rejects that one record loudly while the rest proceed.
                    # `newline=""` leaves line splitting to the wrapper without
                    # translating terminators, and the terminator is stripped
                    # below as the port requires.
                    text = io.TextIOWrapper(
                        raw, encoding="ascii", errors="replace", newline=""
                    )
                    for line in text:
                        yield line.rstrip("\r\n")
        except (zipfile.BadZipFile, OSError) as error:
            raise CatalogRetrievalError(
                f"The cached JMA archive for year {year} at {archive_path} "
                f"could not be read: {error}. Delete it and re-run to download "
                f"a fresh copy."
            ) from error

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
