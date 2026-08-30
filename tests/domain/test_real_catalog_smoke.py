"""Parse a whole published catalog file, if one is available locally.

The JMA catalog must not be committed (JMA terms: fetch at run time, do not
redistribute; `.gitignore` excludes `*.zip` and `h[0-9][0-9][0-9][0-9]`). So
these tests read a file named by an environment variable and skip when it is
absent, which is what CI does:

    JMACAT_HYPOCENTER_FILE=/path/to/h2023 uv run pytest

The point of a smoke test over 257,020 real records is different from the
verbatim-record tests: those pin known values, this one asserts that nothing in
the corpus makes the parser raise, and that the population-level invariants the
format doc derives hold across every record - which is how a wrong byte offset
shows up when no single hand-picked line happens to catch it.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from jmacat.domain.hypocenter import RECORD_LENGTH, Hypocenter, parse_record

ENVIRONMENT_VARIABLE = "JMACAT_HYPOCENTER_FILE"


def catalog_lines() -> list[str]:
    """Every record of the catalog file named by the environment, or skip."""
    location = os.environ.get(ENVIRONMENT_VARIABLE)
    if not location:
        pytest.skip(f"set {ENVIRONMENT_VARIABLE} to a JMA hypocenter file to run")
    path = Path(location)
    if not path.is_file():
        pytest.skip(f"{ENVIRONMENT_VARIABLE} is {location!r}, which is not a file")
    return path.read_text(encoding="ascii").splitlines()


@pytest.fixture(scope="module")
def events() -> list[Hypocenter]:
    """Every record in the catalog, parsed.

    Parsing is the assertion: `parse_record` raises on anything it cannot
    decode, so a corpus-wide parse that completes is itself the result.
    """
    return [parse_record(line) for line in catalog_lines()]


def test_every_line_in_the_catalog_is_96_bytes() -> None:
    """Format doc, Record width is stable across eras."""
    lengths = {len(line) for line in catalog_lines()}
    assert lengths == {RECORD_LENGTH}


def test_every_record_in_the_catalog_parses(events: list[Hypocenter]) -> None:
    """No real record may raise. The corpus is the specification's own data."""
    assert len(events) > 0


def test_no_latitude_leaves_the_globe(events: list[Hypocenter]) -> None:
    """A latitude outside +/-90 deg would mean the coordinate decoding is wrong.

    This is the population-level form of the format doc's Traps 4 check: a
    shifted slice produces well-formed numbers, so only an invariant over the
    whole corpus catches it.
    """
    assert all(Decimal(-90) <= event.latitude <= Decimal(90) for event in events)


def test_no_longitude_leaves_the_globe(events: list[Hypocenter]) -> None:
    assert all(Decimal(-180) <= event.longitude <= Decimal(180) for event in events)


def test_no_depth_is_deeper_than_the_deepest_earthquakes(
    events: list[Hypocenter],
) -> None:
    """Earthquakes stop at the base of the mantle, near 700 km.

    This is what settles the depth field's `F5.2`-with-blank-decimal case: over
    the 297 h1919 records with one trailing blank, the fixed-point reading tops
    out at 540 km while reading four whole-kilometre digits reaches 5400 km,
    deeper than the Earth's radius. Bounded generously at 800 km so the test
    states a physical impossibility rather than a tight empirical maximum.
    """
    depths = [event.depth_km for event in events if event.depth_km is not None]
    assert depths
    assert max(depths) < Decimal(800)


def test_no_magnitude_exceeds_the_largest_earthquake_ever_recorded(
    events: list[Hypocenter],
) -> None:
    """The 1960 Valdivia earthquake, MW 9.5, is the largest instrumentally
    recorded. A decoded magnitude above 10 would mean the field is misread.
    """
    magnitudes = [event.magnitude for event in events if event.magnitude is not None]
    assert magnitudes
    assert max(magnitudes) < Decimal(10)


def test_the_corpus_exercises_negative_magnitudes(events: list[Hypocenter]) -> None:
    """Format doc, Traps 3: 24,882 h2023 records carry a negative magnitude 1.

    Asserted as a property of the corpus rather than a count, so the test holds
    for whichever year's file is supplied. A parser that dropped the sign would
    make this set empty.
    """
    assert any(
        event.magnitude is not None and event.magnitude < 0 for event in events
    )


def test_every_origin_time_is_aware(events: list[Hypocenter]) -> None:
    """Format doc, Time zone: JST is carried explicitly on every record."""
    assert all(event.origin_time.utcoffset() is not None for event in events)


def test_a_blank_field_never_decodes_to_zero(events: list[Hypocenter]) -> None:
    """Traps 6, over the whole corpus: absent is None, not 0.

    A station count of 0 would mean no station contributed, which cannot be
    true of a record that exists; if the blank handling ever collapsed to a
    fallback `0`, the blank station counts would show up here.
    """
    assert all(
        event.station_count is None or event.station_count > 0 for event in events
    )
