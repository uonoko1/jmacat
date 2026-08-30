"""Pure filter predicates over hypocenter events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol


class FilterableEvent(Protocol):
    """The attributes a filter reads off an event."""

    @property
    def origin_time(self) -> datetime: ...


def time_range(
    *, start: datetime | None = None, end: datetime | None = None
) -> Callable[[FilterableEvent], bool]:
    """Accept events whose origin time lies in the closed interval [start, end]."""

    def predicate(event: FilterableEvent) -> bool:
        origin = event.origin_time
        if start is not None and origin < start:
            return False
        return not (end is not None and origin > end)

    return predicate
