"""Output ports of the use case layer.

`infrastructure/` implements these; `usecase/` depends only on them. Importing
from this package rather than the individual modules keeps call sites stable if
a port is later split across files.

`contract` holds the executable conformance checks for promises a `Protocol`
cannot express — see `jmacat.usecase.ports.contract`.
"""

from jmacat.usecase.ports.catalog_source import CatalogSource
from jmacat.usecase.ports.contract import (
    EagerAvailabilityViolation,
    PortContractViolation,
    check_unavailable_year_fails_eagerly,
)
from jmacat.usecase.ports.event_writer import EventWriter

__all__ = [
    "CatalogSource",
    "EagerAvailabilityViolation",
    "EventWriter",
    "PortContractViolation",
    "check_unavailable_year_fails_eagerly",
]
