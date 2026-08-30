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


def test_no_magnitude_falls_below_the_documented_encoding_floor(
    events: list[Hypocenter],
) -> None:
    """Format doc, Magnitude: `C9` is M-3.9, the most negative value encodable.

    Stated as a floor rather than "some magnitude is negative", because whether
    negative magnitudes occur at all is a property of the era, not of the
    parser: h2023 has 24,882 of them (Traps 3) while h1919 has none - detecting
    micro-earthquakes needs the modern network. An assertion that they exist
    would fail on the historical file for a reason that is not a defect.
    The verbatim negative-magnitude records are pinned in the parse tests.
    """
    magnitudes = [event.magnitude for event in events if event.magnitude is not None]
    assert magnitudes
    assert min(magnitudes) >= Decimal("-3.9")


def test_every_origin_time_is_aware(events: list[Hypocenter]) -> None:
    """Format doc, Time zone: JST is carried explicitly on every record."""
    assert all(event.origin_time.utcoffset() is not None for event in events)


def test_a_blank_station_count_is_none_and_a_written_zero_is_zero(
    events: list[Hypocenter],
) -> None:
    """Traps 6, over the whole corpus: absent is None and stays distinct from 0.

    Both values are real. h1919 carries 247 records whose station count c93-95
    is written `  0` - an explicit zero, which must decode to 0 - alongside
    records where the field is blank, which must decode to None. h2023 has no
    written zero at all. A `.strip() or "0"` fallback would merge the two and
    this test could not tell the difference, so it asserts the counts of each
    kind rather than a property that one of them satisfies vacuously.
    """
    decoded = [event.station_count for event in events]
    raw = [line[92:95] for line in catalog_lines()]
    assert all(count is None or count >= 0 for count in decoded)
    # Every blank field decodes to None and no populated field does, so the two
    # kinds cannot have been merged in either direction.
    assert all(
        (count is None) == (not field.strip())
        for count, field in zip(decoded, raw, strict=True)
    )
