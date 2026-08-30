"""One end-to-end run against the real published catalog. Opt-in.

Everything else exercising the interactor and the CLI runs against the
in-memory fakes, which is what keeps the suite offline and fast. But the fakes
agree with the adapters only as long as somebody checks: this is the test that
composes the *real* JmaCatalogSource, the real parser, the real filters and a
real writer, and it is the only place the whole stack is exercised at once.

Run it deliberately:

    JMACAT_INTEGRATION=1 uv run pytest -m integration

No catalog data is committed. The archive is downloaded to a temporary cache
directory and discarded with it, so nothing from JMA ever enters the
repository.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jmacat.controller.cli import fetch
from jmacat.usecase.export import OutputFormat

#: 1919 rather than 2023: a 799,597-byte archive instead of a 6,977,812-byte
#: one, which is politer to a public service, and it is also the corpus where
#: the missing-magnitude effect is largest, which is what this test measures.
PUBLISHED_YEAR = 1919

#: h1919 covers 1919-1950 and holds 28,235 records, of which 11,621 carry no
#: magnitude at all. With `min_magnitude=3.0` the run selects 15,874 and
#: rejects 740 on the comparison.
#:
#: These are the numbers `domain/filters.py` documents, and they are asserted
#: exactly rather than as a threshold: a `>= 15000` assertion would still pass
#: if the parser silently lost a thousand records, which is the failure this
#: test exists to catch. If JMA republishes the archive these must be
#: re-derived from the new data, not relaxed.
TOTAL_RECORDS = 28_235
SELECTED = 15_874
EXCLUDED_BY_COMPARISON = 740
EXCLUDED_MISSING_MAGNITUDE = 11_621

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("JMACAT_INTEGRATION"),
        reason="downloads from the live JMA site; set JMACAT_INTEGRATION=1 to run",
    ),
]


def test_a_real_year_is_fetched_filtered_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole stack, on the corpus where the missing-value effect is largest.

    A researcher filtering the pre-war era for M3.0 and above loses two fifths
    of their rows to blank magnitudes. That is the number issue #20 exists to
    surface, and this asserts the real run reports it.
    """
    monkeypatch.setenv("JMACAT_CACHE_DIR", str(tmp_path / "cache"))
    destination = tmp_path / "h1919.csv"

    result = fetch(
        year=PUBLISHED_YEAR,
        output=destination,
        output_format=OutputFormat.CSV,
        min_magnitude=3.0,
    )

    assert result.records_read == TOTAL_RECORDS
    assert result.records_written == SELECTED
    assert result.records_rejected == 0
    (magnitude,) = result.filter_outcomes
    assert magnitude.excluded_by_comparison == EXCLUDED_BY_COMPARISON
    assert magnitude.excluded_missing_value == EXCLUDED_MISSING_MAGNITUDE
    assert result.reconciles()

    # The file really holds what was reported: a count that agreed with itself
    # but not with the destination would be the silent wrong answer the whole
    # project is built to avoid.
    written = destination.read_text(encoding="utf-8").splitlines()
    assert len(written) == SELECTED + 1  # + the header row
