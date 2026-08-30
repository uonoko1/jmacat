# Contributing to jmacat

## Architecture: dependencies point inward

    controller/  ->  usecase/  ->  domain/
    infrastructure/  ->  usecase/ports/     (dependency inversion)

- `domain/` — the JMA record layout, coordinate/time/magnitude conversion, filter
  predicates. **Standard library only.** No pandas, pyarrow, typer, httpx.
- `usecase/` — interactors that orchestrate a task. `usecase/ports/` holds the
  output ports (`CatalogSource`, `EventWriter`) as `typing.Protocol`.
  Repository and gateway interfaces belong here, not in `domain/`.
- `infrastructure/` — implements the ports: HTTP, ZIP, Parquet, CSV, cache.
- `controller/` — the CLI. Thin: parse arguments, call an interactor, format output.

`domain/` and `usecase/` must never import `infrastructure/` or `controller/`.
A test enforces this by walking the AST; it is not a matter of discipline.

Why: JMA can change its URL scheme or file layout at any time. Keeping that churn
in `infrastructure/` leaves the scientifically sensitive conversion logic stable
and testable without a network.

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
