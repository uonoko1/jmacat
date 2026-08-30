#!/usr/bin/env python3
"""Generate the JMA epicentre region-name table from Appendix 1.A.3.

The hypocenter record carries a district number (c65) and a region number
(c66-68) whose meanings are published only as HTML tables in JMA's bulletin
appendix, not in the record format specification:

    index: https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix/appendixj.html#REGION
    data:  https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix/regname1.html
           ... regname8.html   (one page per district)

Each page is a plain <table> with three columns: 大地域区分番号 (district),
小地域区分番号 (region) and 震央地名 (region name). The district number is
written once per district in a rowspan cell, so it must be carried down.

This script is deliberately the only copy of that mapping: the table is a JMA
dataset that can change when JMA revises the appendix, so it is regenerated
rather than hand-maintained in a document. Output is JSON, keyed "district:region",
for use as a parser test fixture (issues #3/#4).

Standard library only, per CONTRIBUTING.md. Usage:

    python3 tools/build_region_names.py > region_names.json

Verified 2026-08-30: 269 entries across districts 1-8. Compared against the
region name field (c69-92) of the published catalog, this mapping reproduces
256,868 of 257,020 records in h2023 with zero mismatches (87 U-records carry a
blank region number; 65 are the sentinel district 8 / region 400 = FAR FIELD).
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request

BASE = "https://www.data.jma.go.jp/eqev/data/bulletin/catalog/appendix"
DISTRICTS = range(1, 9)

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<(t[dh])[^>]*>(.*?)</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    """Strip markup and entities from one table cell."""
    return html.unescape(_TAG.sub("", fragment)).strip()


def parse_page(source: str) -> dict[tuple[int, int], str]:
    """Extract {(district, region): name} from one regname*.html page.

    The district number appears once per block in a rowspan cell, so a row with
    three cells opens a new district and rows with two cells inherit it.
    """
    mapping: dict[tuple[int, int], str] = {}
    for table in _TABLE.findall(source):
        district: int | None = None
        for row in _ROW.findall(table):
            cells = _CELL.findall(row)
            # Header rows use <th>; skip them.
            if not cells or cells[0][0].lower() == "th":
                continue
            values = [_text(body) for _, body in cells]
            if len(values) == 3:
                district, region, name = int(values[0]), values[1], values[2]
            elif len(values) == 2:
                region, name = values
            else:
                continue
            if district is None or not region:
                continue
            key = (district, int(region))
            previous = mapping.get(key)
            if previous is not None and previous != name:
                raise ValueError(f"conflicting names for {key}: {previous!r} vs {name!r}")
            mapping[key] = name
    return mapping


def build() -> dict[tuple[int, int], str]:
    mapping: dict[tuple[int, int], str] = {}
    for district in DISTRICTS:
        url = f"{BASE}/regname{district}.html"
        with urllib.request.urlopen(url) as response:
            source = response.read().decode("utf-8")
        page = parse_page(source)
        if not page:
            raise ValueError(f"no rows parsed from {url}")
        mapping.update(page)
    return mapping


def main() -> int:
    mapping = build()
    json.dump(
        {f"{d}:{r}": name for (d, r), name in sorted(mapping.items())},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    print(f"{len(mapping)} entries", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
