from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from actual_discord_bot.bank_imports.caption import (
    BankImportCaptionError,
    calendar_month_window,
    parse_month_caption,
)


@pytest.mark.parametrize(
    ("caption", "expected"),
    [("", 1), (" 1 month ", 1), ("24 MONTHS", 24), ("2 months", 2)],
)
def test_parse_month_caption_accepts_only_the_documented_grammar(caption, expected):
    assert parse_month_caption(caption) == expected


@pytest.mark.parametrize(
    "caption", ["0 months", "25 months", "-1 month", "1.5 months", "two months", "2 months please"]
)
def test_parse_month_caption_rejects_invalid_requests(caption):
    with pytest.raises(BankImportCaptionError):
        parse_month_caption(caption)


def test_calendar_month_window_crosses_year_boundary_in_configured_timezone():
    now = datetime(2026, 1, 2, 0, 30, tzinfo=ZoneInfo("Europe/Warsaw"))

    assert calendar_month_window(3, ZoneInfo("Europe/Warsaw"), now) == (
        date(2025, 11, 1),
        date(2026, 1, 2),
    )


def test_calendar_month_window_uses_local_date_not_utc_date():
    now = datetime(2026, 7, 31, 22, 30, tzinfo=ZoneInfo("UTC"))

    assert calendar_month_window(1, ZoneInfo("Europe/Warsaw"), now) == (
        date(2026, 8, 1),
        date(2026, 8, 1),
    )
