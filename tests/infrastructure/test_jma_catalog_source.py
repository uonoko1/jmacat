"""Tests for the HTTP/ZIP `CatalogSource` adapter.

Every test here runs against recorded fixtures — never the live network. The
one test that touches JMA lives in `test_jma_catalog_source_integration.py`
and is skipped unless it is opted into explicitly.
"""

from __future__ import annotations

from pathlib import Path

from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource
from jmacat.usecase.ports.contract import check_unavailable_year_fails_eagerly
from tests.infrastructure.recorded_transport import RecordedTransport

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
