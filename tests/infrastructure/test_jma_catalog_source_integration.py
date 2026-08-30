"""The one test that talks to JMA. Skipped unless explicitly opted into.

Everything else in the suite runs against recorded fixtures, which is what
keeps CI fast, offline and independent of a public service. But recordings can
drift: JMA can change the URL scheme, the archive layout, or the response for
an unpublished year, and a suite of recordings would keep passing while the
adapter had stopped working. This test is the periodic check against that.

Run it deliberately:

    JMACAT_INTEGRATION=1 uv run pytest -m integration

It is one test, not a suite, per issue #6's "at most one opt-in integration
test": it asserts the two facts the whole adapter rests on — a published year
downloads and parses, and an unpublished year fails as unavailable — in a
single request each.
"""

from __future__ import annotations

import os
from itertools import islice
from pathlib import Path

import pytest

from jmacat.infrastructure.jma_catalog_source import JmaCatalogSource
from jmacat.usecase.errors import CatalogYearUnavailableError

#: 1919 rather than 2023: the same code path over a 799,597-byte archive
#: instead of a 6,977,812-byte one, which is politer to a public service for a
#: test whose purpose is to check the contract, not the throughput.
PUBLISHED_YEAR = 1919

#: Verified 2026-08-30: h2024.zip returns 404. If JMA publishes 2024 this test
#: starts failing, which is the correct signal — the fixture and the docstrings
#: naming 2024 as the unavailable year would then need updating too.
UNPUBLISHED_YEAR = 2024

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("JMACAT_INTEGRATION"),
        reason="touches the live JMA site; set JMACAT_INTEGRATION=1 to run",
    ),
]


def test_the_live_site_still_matches_the_recorded_behaviour(tmp_path: Path) -> None:
    """A published year downloads and streams; an unpublished year fails."""
    source = JmaCatalogSource(cache_dir=tmp_path)

    first_lines = list(islice(source.record_lines(PUBLISHED_YEAR), 5))

    assert len(first_lines) == 5
    # Every record is 96 bytes (docs/jma-hypocenter-format.md).
    assert {len(line) for line in first_lines} == {96}
    assert (tmp_path / f"h{PUBLISHED_YEAR}.zip").exists()

    with pytest.raises(CatalogYearUnavailableError) as excinfo:
        source.record_lines(UNPUBLISHED_YEAR)

    assert "lag" in str(excinfo.value)
