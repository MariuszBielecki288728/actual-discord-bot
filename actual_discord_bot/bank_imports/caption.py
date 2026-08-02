"""Strict bank-import caption parsing and calendar date-window arithmetic."""

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

MONTH_CAPTION_PATTERN = re.compile(r"(?P<months>[1-9]\d*)\s+months?", re.IGNORECASE)
DEFAULT_MONTHS = 1
MAX_MONTHS = 24
INVALID_MONTHS_ERROR = "months must be between 1 and 24"


class BankImportCaptionError(ValueError):
    """Raised when a caption is not an accepted bank-import request."""


def parse_month_caption(caption: str) -> int:
    """Return the requested inclusive calendar-month count."""
    normalized_caption = caption.strip()
    if not normalized_caption:
        return DEFAULT_MONTHS
    match = MONTH_CAPTION_PATTERN.fullmatch(normalized_caption)
    if match is None:
        raise BankImportCaptionError
    months = int(match["months"])
    if not 1 <= months <= MAX_MONTHS:
        raise BankImportCaptionError
    return months


def calendar_month_window(months: int, timezone: ZoneInfo, now: datetime | None = None) -> tuple[date, date]:
    """Return the inclusive date range containing today and prior calendar months."""
    if not 1 <= months <= MAX_MONTHS:
        raise ValueError(INVALID_MONTHS_ERROR)
    local_today = (now.astimezone(timezone) if now else datetime.now(timezone)).date()
    month_index = local_today.year * 12 + local_today.month - 1 - (months - 1)
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1), local_today
