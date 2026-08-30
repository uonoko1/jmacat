"""Tests for the reusable eager-availability contract check.

The check itself is the deliverable: issue #6's adapter imports it and runs it
against the real HTTP implementation. So the check needs its own tests, and in
particular a *negative* one — a check that cannot fail is worth nothing.

The failure it exists to catch is subtle and type-checks cleanly. Writing

    def record_lines(self, year: int) -> Iterator[str]:
        if unavailable:
            raise CatalogYearUnavailableError(year)
        yield from lines

makes `record_lines` a generator function, so calling it runs no body at all: it
returns a generator and raises nothing. The error surfaces on first `next()`,
escaping a caller's `try`/`except` around the call site — which is exactly the
"failed download published as an empty catalog" outcome the port forbids.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from jmacat.usecase.errors import CatalogYearUnavailableError
from jmacat.usecase.ports.contract import (
    EagerAvailabilityViolation,
    check_unavailable_year_fails_eagerly,
)


class LazyCatalogSource:
    """The natural-but-wrong spelling: a generator function, so nothing is eager."""

    def record_lines(self, year: int) -> Iterator[str]:
        if year == UNAVAILABLE_YEAR:
            raise CatalogYearUnavailableError(year)
        yield "line"


class EagerCatalogSource:
    """The correct spelling: resolve availability, then return a generator."""

    def record_lines(self, year: int) -> Iterator[str]:
        if year == UNAVAILABLE_YEAR:
            raise CatalogYearUnavailableError(year)
        return self._generate()

    def _generate(self) -> Iterator[str]:
        yield "line"


class SilentCatalogSource:
    """Does not raise at all — an unavailable year read as an empty catalog."""

    def record_lines(self, year: int) -> Iterator[str]:
        return iter(())


UNAVAILABLE_YEAR = 2024


class TestEagerAvailabilityContract:
    def test_a_lazy_generator_implementation_is_rejected(self) -> None:
        """The whole point: the spelling that type-checks but defers the 404."""
        with pytest.raises(EagerAvailabilityViolation) as excinfo:
            check_unavailable_year_fails_eagerly(
                LazyCatalogSource(), unavailable_year=UNAVAILABLE_YEAR
            )

        assert "generator" in str(excinfo.value)

    def test_an_eager_implementation_passes(self) -> None:
        check_unavailable_year_fails_eagerly(
            EagerCatalogSource(), unavailable_year=UNAVAILABLE_YEAR
        )

    def test_an_implementation_that_never_raises_is_rejected(self) -> None:
        """An empty stream must never stand in for an unavailable year."""
        with pytest.raises(EagerAvailabilityViolation):
            check_unavailable_year_fails_eagerly(
                SilentCatalogSource(), unavailable_year=UNAVAILABLE_YEAR
            )
