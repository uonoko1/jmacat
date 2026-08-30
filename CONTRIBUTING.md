# Contributing to jmacat

## Architecture: dependencies point inward

    controller/  ->  infrastructure/  ->  usecase/  ->  domain/
                 \------------------->  usecase/ports/   (dependency inversion)

Every arrow points inward, and the exact rule is the matrix below.

- `domain/` — the JMA record layout, coordinate/time/magnitude conversion, filter
  predicates. **Standard library only.** No pandas, pyarrow, typer, httpx.
- `usecase/` — interactors that orchestrate a task. `usecase/ports/` holds the
  output ports (`CatalogSource`, `EventWriter`) as `typing.Protocol`.
  Repository and gateway interfaces belong here, not in `domain/`.
- `infrastructure/` — implements the ports: HTTP, ZIP, Parquet, CSV, cache.
- `controller/` — the CLI. Thin: parse arguments, call an interactor, format output.

Why: JMA can change its URL scheme or file layout at any time. Keeping that churn
in `infrastructure/` leaves the scientifically sensitive conversion logic stable
and testable without a network.

### The dependency matrix

The four layers are **totally ordered**, innermost first:

    domain  <-  usecase  <-  infrastructure  <-  controller

A module may import its own layer and anything **inward** of it. Importing
outward is a violation.

| may import →<br>layer ↓ | `domain/` | `usecase/` | `infrastructure/` | `controller/` | third-party |
| --- | --- | --- | --- | --- | --- |
| `domain/`         | yes | no  | no  | no  | **no** |
| `usecase/`        | yes | yes | no  | no  | **no** |
| `infrastructure/` | yes | yes | yes | no  | yes |
| `controller/`     | yes | yes | yes | yes | yes |

Two things about this table are worth stating explicitly, because both are
choices rather than consequences of the picture above.

**`controller/` may import `infrastructure/`.** Something has to choose a
concrete `ParquetEventWriter` over a `CsvEventWriter` and hand it to an
interactor, and in Clean Architecture that composition happens at the outermost
layer. Routing the wiring through `usecase/` would mean the use case layer
naming its own adapters, which is the dependency inversion pointing backwards.
So the CLI is the composition root: it is the one place allowed to know every
layer. This is why `infrastructure/` and `controller/` are ordered rather than
treated as peer adapters.

**`infrastructure/` may not import `controller/`.** There is no legitimate form
of this. An adapter that reaches for the CLI cannot be exercised without it,
and it makes the output format depend on the thing that chose the output
format. This direction is the one issue #21 found unenforced.

**`infrastructure/` and `controller/` may import `domain/` directly**, not only
through `usecase/ports/`. An adapter that serialises a `Hypocenter` has to know
what a `Hypocenter` is; forbidding it would only push the layer into
re-declaring the domain's own types. (`infrastructure/event_protocol.py`
mirrors the domain with a `Protocol` for a different reason — it was written on
a branch where `domain/` did not exist yet — not because the import is barred.)

**Only `domain/` and `usecase/` are standard-library-only.** That restriction is
about keeping the conversion logic installable and testable with nothing
present; it is not a statement about direction. `infrastructure/` needs pyarrow
and `controller/` needs an argument parser, and both are expected to have them.

`tests/test_architecture.py` enforces exactly this table by walking the AST of
every module under `src/jmacat/`; it is not a matter of discipline. If you
change the table, change the guard in the same commit — and add the violating
case that proves the new rule can fail.

## TDD is mandatory

Red, green, refactor — one cycle at a time.

1. Write a failing test and **observe it fail**. A test that has never failed
   proves nothing.
2. Write the least code that makes it pass. Faking a return value first is fine.
3. Generalise by triangulation: add a second case that the fake cannot satisfy.
4. Refactor with the tests green.

Do not write the implementation first and add tests afterwards.

Name tests so they read as specifications:

    def test_southern_hemisphere_latitude_is_negative() -> None:

## Test expectations must be traceable

This project converts numbers that affect scientific results. An epicentre that is
27 km off does not raise an error — it simply publishes a wrong map.

Therefore:

- **Every numeric expectation must be traceable** to the official JMA format
  specification or to a real, cited record from the published catalog. Put the
  source in the test docstring or an adjacent comment.
- **Never invent an expected value.** If you cannot derive it from the spec or from
  real data, stop and say so in the pull request rather than guessing.
- Prefer verbatim real record lines over synthetic ones for parser tests.

Anything a language model produced is a draft until it is checked against the
specification or the data.

## Commits

- English, imperative mood: `Add southern-hemisphere latitude case`.
- Small and frequent. One reason to change per commit.
- Keep red-to-green visible: committing the failing test and then the fix is
  encouraged.

## Pull requests

- English title and description.
- State what changed, why, and how it was verified.
- Reference the issue: `Closes #3`.
- CI (ruff, mypy --strict, pytest) must be green.
- **A pull request is merged only after review has no outstanding findings.**

## Code comments

English. Explain why, not what. A comment earns its place by recording a
constraint that the code cannot state on its own — a byte offset from the spec, a
unit, a JMA quirk.

## Safety scope

This is a research and education preprocessing tool. It is not a substitute for
official disaster information, and must not be used for evacuation decisions or
real-time alerting. Prefer failing loudly over returning a value that might be wrong.

## Two failure modes this project has already hit

Both were found in review, not by the developer who wrote the code, and both
passed every gate at the time. They are recorded here because the next instance
will look just as green.

### A test that passes for a reason unrelated to correctness

Three examples from sprint 2:

- A memory test asserting `peak < 200 MiB` passed with batching **disabled** — a
  buffered year lands right at the threshold, so the assertion could never fail.
  Fixed by comparing two runs that differ in one thing, and proving the comparison
  fails under mutation.
- A README-sync test compared units by substring, so changing `kilometres` to
  `metres` — a hundredfold error — passed. `"metres"` is a substring of
  `"kilometres"`.
- A filter measurement used `minimum=3.0`, one of the few magnitudes where a float
  bound happens to compare correctly. At `minimum=3.1` the same code silently drops
  every record sitting exactly on the bound.

Before trusting a test, mutate the thing it claims to check and watch it fail. An
absolute threshold, a substring match, and a single sampled value are the three
shapes most likely to hide this.

### A type guessed rather than agreed

`domain/` uses `Decimal` for coordinates, depth and magnitude, because a coordinate
is degrees + minutes/100/60 and **6,666 of the 10,000 possible minute values** do
not terminate in binary. `float` rounds the published value.

While the parser was still being written, two other layers each independently
guessed `float` for the same fields, and two reviews missed it because neither
probed `Decimal` specifically. Nothing forced the types to meet until someone tried
to compose them.

When you build against a type that does not exist yet, write the conformance
assignment first — `probe: TheProtocol = the_real_thing(...)` — even if it does not
compile yet. A protocol nothing has ever been checked against is a guess.
