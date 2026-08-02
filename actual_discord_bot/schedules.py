"""Project-owned schedule values and strict duration parsing."""

import re
from dataclasses import dataclass
from enum import StrEnum


class TimeDeltaError(ValueError):
    """Raised when a command duration does not use the supported grammar."""


class RecurrenceFrequency(StrEnum):
    """Frequencies supported by Actual recurring schedules."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass(frozen=True)
class ScheduleRecurrence:
    """A calendar recurrence independent of ActualPy's public types."""

    interval: int = 1
    frequency: RecurrenceFrequency = RecurrenceFrequency.MONTHLY


_TIME_DELTA_PATTERN = re.compile(
    r"(?P<count>[1-9]\d*)\s+(?P<unit>[a-zA-Z]+)", re.IGNORECASE
)


def parse_time_delta(value: str, *, allowed_units: set[str]) -> tuple[int, str]:
    """Parse a positive ``X unit(s)`` duration and return its singular unit."""
    match = _TIME_DELTA_PATTERN.fullmatch(value.strip())
    if match is None:
        raise TimeDeltaError

    count = int(match["count"])
    unit = match["unit"].casefold()
    singular_unit = unit.removesuffix("s")
    if singular_unit not in allowed_units or unit not in {
        singular_unit,
        f"{singular_unit}s",
    }:
        raise TimeDeltaError
    return count, singular_unit


def parse_schedule_recurrence(value: str) -> ScheduleRecurrence:
    """Parse a schedule recurrence, defaulting an empty argument to monthly."""
    if not value.strip():
        return ScheduleRecurrence()

    count, unit = parse_time_delta(
        value,
        allowed_units={"day", "week", "month", "year"},
    )
    frequency = {
        "day": RecurrenceFrequency.DAILY,
        "week": RecurrenceFrequency.WEEKLY,
        "month": RecurrenceFrequency.MONTHLY,
        "year": RecurrenceFrequency.YEARLY,
    }[unit]
    return ScheduleRecurrence(count, frequency)
