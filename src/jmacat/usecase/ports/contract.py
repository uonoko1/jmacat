"""Executable conformance checks for the use case output ports.

A `typing.Protocol` constrains *shape*: method names, parameter types, return
types. Some of what a port promises is not shape, and mypy cannot see it. This
module holds those promises as functions an implementation can run against
itself, so a rule that would otherwise be prose in a docstring becomes a check
that fails.

Why this lives in the package rather than under `tests/`
--------------------------------------------------------

`tests/` is not shipped, so an adapter in `infrastructure/` — or any out-of-tree
implementation of these ports — could not import it. The promise belongs to the
port, which is the thing making it, so the executable form of the promise travels
with the port.

It costs nothing to ship: standard library only, no pytest import, and the checks
raise a plain exception rather than calling any assertion helper. A test suite
runs them by calling them; a failure surfaces as `EagerAvailabilityViolation`.
"""

from __future__ import annotations

import inspect
from typing import Protocol

from jmacat.usecase.errors import CatalogYearUnavailableError


class PortContractViolation(AssertionError):  # noqa: N818
    """An implementation satisfies a port's types but breaks its contract.

    Derives from `AssertionError` so a failure reads as a failed test rather than
    an error, in whatever runner an implementer happens to use.

    N818 wants an `Error` suffix, which is right for the operational failures in
    `jmacat.usecase.errors` but wrong here: the suffix would assert the opposite
    of the base class. This is a failed assertion about an implementation, in the
    same family as `AssertionError` itself, which carries no suffix either.
    """


class EagerAvailabilityViolation(PortContractViolation):
    """`CatalogSource.record_lines` deferred an unavailable year past its call."""


class _SupportsRecordLines(Protocol):
    def record_lines(self, year: int) -> object: ...


def check_unavailable_year_fails_eagerly(
    source: _SupportsRecordLines,
    *,
    unavailable_year: int,
) -> None:
    """Assert that `source` reports an unavailable year at call time.

    `unavailable_year` must be a year this source cannot serve — for the JMA
    adapter, a year the finalized catalog has not reached (2024 today); for a
    fake, any year it was not given.

    Two ways an implementation fails this, both of which type check:

    1. `record_lines` is a **generator function**. Calling it then executes no
       body at all — it returns a generator and raises nothing, deferring the
       failure to the first `next()`. This is the natural spelling and the
       reason this check exists.
    2. `record_lines` returns an empty iterator instead of raising, letting a
       year JMA has not published read as a year with no earthquakes.

    Raises:
        EagerAvailabilityViolation: the failure did not surface at the call.
    """
    # Checked before calling, so the diagnosis names the cause rather than the
    # symptom: a generator function cannot be eager about anything, whatever its
    # body says.
    if inspect.isgeneratorfunction(source.record_lines):
        raise EagerAvailabilityViolation(
            f"{_name(source)}.record_lines is a generator function, so calling it "
            f"runs none of its body and raises nothing for year "
            f"{unavailable_year}; the failure would surface only at the first "
            f"next(). Resolve availability in a plain function, then return a "
            f"separate generator for the lines."
        )

    try:
        source.record_lines(unavailable_year)
    except CatalogYearUnavailableError:
        return

    raise EagerAvailabilityViolation(
        f"{_name(source)}.record_lines({unavailable_year}) returned without "
        f"raising CatalogYearUnavailableError. An unavailable year must fail at "
        f"the call site; an empty stream is indistinguishable from a year with "
        f"no earthquakes."
    )


def _name(source: object) -> str:
    return type(source).__name__
