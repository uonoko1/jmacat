# Recorded fixtures for the JMA catalog adapter

Everything here was recorded from the live JMA site so that unit tests never
touch the network. Both files are deliberately tiny; the full archives are
megabytes and must not be committed (see `.gitignore` and the licensing note
below).

## `h1919_sample.zip` (651 bytes)

The first **12 record lines** of `h1919`, the file inside
`https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h1919.zip`
(the archive covering 1919-1950; 799,597 bytes as retrieved 2026-08-30).

Repacked, not the original archive: a single deflated member named `h1919`,
with a fixed 1980-01-01 timestamp so the fixture is byte-stable in git. The
member name matters — the adapter reads the archive's single member whatever
it is called, and a name that does not match the requested year is exactly the
case a test needs.

Every line is exactly 96 bytes, matching the published fixed-width layout
(`docs/jma-hypocenter-format.md`).

## `h2024_404.html` (2,203 bytes)

The **verbatim** body returned by
`https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h2024.zip`,
retrieved 2026-08-30: HTTP 404, `Content-Type: text/html`, 2,203 bytes.

This is the case the adapter must never mistake for a ZIP. Kept verbatim rather
than reduced to `<html></html>` so the magic-byte check is tested against the
real thing, including its leading `<!DOCTYPE html>`.

## Licensing and attribution

`h1919_sample.zip` contains data from the Japan Meteorological Agency's
hypocenter catalog, published under the **Public Data License (Version 1.0)**
(公共データ利用規約（第1.0版）, "PDL1.0"), which permits redistribution with
attribution. See JMA's terms page,
<https://www.jma.go.jp/jma/kishou/info/coment.html>, and the licence text at
<https://www.digital.go.jp/resources/open_data/public_data_license_v1.0>.

The terms require both a source citation and, where the content has been
edited or processed, a separate statement that it was — so both are given:

    Source: Japan Meteorological Agency, Seismological Bulletin of Japan,
    hypocenter catalog
    (https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h1919.zip)

    Processed by the jmacat project: excerpted to the first 12 record lines
    and repacked as a single deflated member with a fixed timestamp. The
    record lines themselves are byte-for-byte as published; nothing in them
    was altered.

Twelve lines is the smallest excerpt that still exercises the streaming path
over more than one buffer boundary while keeping the committed excerpt minimal.

`h2024_404.html` is JMA's HTTP 404 error page. It carries no catalog data, but
it is JMA site content and is reproduced verbatim under the same terms:

    Source: Japan Meteorological Agency
    (https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h2024.zip)
    Reproduced unmodified.

See the "Data provenance and attribution" section of the top-level `README.md`
for what these obligations mean for a user publishing results.
