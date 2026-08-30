"""Pure filter predicates over hypocenter events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol


class FilterError(ValueError):
    """A filter was constructed with arguments it cannot honour."""


class NaiveDatetimeError(FilterError):
    """A time bound was given without a time zone.

    JMA origin times are Japan Standard Time (UTC+9); see
    `docs/jma-hypocenter-format.md`, *Time zone*. Comparing a JST origin time
    against a naive bound would either shift the window by 9 hours (if the
    caller meant UTC) or raise `TypeError` deep inside the predicate, once per
    record. Refusing the bound at construction time turns a silent 9-hour
    error into a loud one, before any record is read.
    """


class FilterableEvent(Protocol):
    """The attributes a filter reads off an event."""

    @property
    def origin_time(self) -> datetime: ...


def _require_aware(value: datetime | None, *, name: str) -> None:
    """Reject a naive datetime bound.

    `utcoffset() is None` is the documented test for awareness and is correct
    for zones whose offset is zero, where a truthiness check on the offset
    would wrongly call an aware UTC datetime naive.
    """
    if value is not None and value.utcoffset() is None:
        raise NaiveDatetimeError(
            f"{name} must be timezone-aware; JMA origin times are JST (UTC+9), "
            f"so a naive bound would shift the window silently. Got {value!r}."
        )


def time_range(
    *, start: datetime | None = None, end: datetime | None = None
) -> Callable[[FilterableEvent], bool]:
    """Accept events whose origin time lies in the closed interval [start, end].

    Both bounds are **inclusive**: a record whose origin time equals `start` or
    `end` is admitted. Either may be `None`, leaving that side unbounded.

    Both bounds must be **timezone-aware**; a naive one raises
    `NaiveDatetimeError`. Bounds need not be JST — comparison is by absolute
    instant, so an aware UTC bound works and means what it says.
    """
    _require_aware(start, name="start")
    _require_aware(end, name="end")

    def predicate(event: FilterableEvent) -> bool:
        origin = event.origin_time
        _require_aware(origin, name="origin_time")
        if start is not None and origin < start:
            return False
        return not (end is not None and origin > end)

    return predicate
