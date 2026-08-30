# The catalog cache

`JmaCatalogSource` downloads one archive per year from

    https://www.data.jma.go.jp/eqev/data/bulletin/data/hypo/h{year}.zip

and keeps it on disk so a re-run does not fetch it again. A single year is
~7 MB compressed and a multi-decade run is gigabytes, so re-downloading on
every run is slow for the user and impolite to a free public service.

## Where the cache lives

The first of these that is set wins:

1. the `cache_dir` argument to `JmaCatalogSource(...)`;
2. the `JMACAT_CACHE_DIR` environment variable;
3. `$XDG_CACHE_HOME/jmacat`;
4. `~/.cache/jmacat`.

The environment variable exists for shared machines and HPC nodes, where a home
directory is often small or on a slow network filesystem and scratch space is
the right place for tens of gigabytes:

    export JMACAT_CACHE_DIR=/scratch/$USER/jmacat

Each year is stored under its published name, `h{year}.zip`, byte for byte as
JMA served it. Nothing is rewritten or re-compressed, so a cached file can be
compared against a fresh download or handed to any other tool.

The cache is safe to delete at any time: it is a copy of published data, and
the next run re-downloads whatever is missing.

## What happens when a cached file is damaged

A cache is only useful if a damaged entry is self-correcting. A run killed with
Ctrl-C, a full disk, or a dropped connection must not leave behind a file that
every later run trips over and that re-running never clears.

Two mechanisms, at the two moments damage can occur.

**On write, the download is atomic.** Bytes go to a temporary file in the cache
directory, that file is opened as a ZIP to confirm it is complete, and only
then is it renamed onto `h{year}.zip`. The rename is atomic within a
filesystem, and the temporary file is created in the same directory so the
rename never crosses one. A partial download is therefore never visible under
the cache path — an interrupted run leaves the cache exactly as it found it,
with not even a stray temporary file behind.

The post-download ZIP check matters more than it looks. A connection can close
*cleanly* after delivering only part of the body: no error is raised, and the
bytes that did arrive start with a real ZIP header, so a magic-byte check
passes. What catches it is that a ZIP's central directory lives at the **end**
of the file, so a truncated archive fails to open. Without that check the
truncated file would be cached and every later run would fail on it.

**On read, a cache entry is verified before it is trusted.** Before serving a
cached archive, it is opened and required to contain at least one member. If it
does not — truncated by an older version, corrupted on disk, or clobbered by
something else — it is discarded and re-downloaded, with a warning logged. The
user does not have to know the cache exists, let alone find and delete it.

The check reads only the central directory, not the 25 MB of records, so it
costs a seek rather than a decompression.

## What is *not* cached

A failed request never becomes a cache entry. In particular the 404 HTML body
that JMA returns for an unpublished year is recognised before anything is
written, so it cannot be stored and mistaken for an archive on a later run.

## Licensing

Cached files are JMA's published data, redistributed under the Japan Public
Data License 1.0, which requires attribution. They live in the user's own
environment and are never committed to this repository; `.gitignore` excludes
`*.zip` and `h[0-9][0-9][0-9][0-9]` for that reason.

    Source: Japan Meteorological Agency, seismic hypocenter catalog
    https://www.data.jma.go.jp/eqev/data/bulletin/hypo.html
