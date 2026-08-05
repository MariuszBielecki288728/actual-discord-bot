from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from actual_discord_bot.bank_notifications import PekaoNotification
from actual_discord_bot.dataclasses_definitions import ActualTransactionData


@pytest.mark.parametrize(
    ("message", "expected_notification"),
    [
        (
            """Title: Transakcja kartą
Text: Zapłacono kwotę 90,45 PLN kartą *1000 dnia 23-09-2024 godz. 19:12:27 w CARREFOUR PLA536 CARREFOUR PLA536 WROCLAW POL. Bank Pekao S.A.
Timestamp: 1.727111551661E9""",
            PekaoNotification(
                title="Transakcja kartą",
                text="Zapłacono kwotę 90,45 PLN kartą *1000 dnia 23-09-2024 godz. 19:12:27 w CARREFOUR PLA536 CARREFOUR PLA536 WROCLAW POL. Bank Pekao S.A.",
                bank="Pekao",
                occurred_at=datetime(2024, 9, 23, 17, 12, 31, 661000, tzinfo=UTC),
            ),
        ),
        (
            """Title: Wpływ
Text: Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.
Timestamp: 1.727063157021E9""",
            PekaoNotification(
                title="Wpływ",
                text="Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.",
                bank="Pekao",
                occurred_at=datetime(2024, 9, 23, 3, 45, 57, 21000, tzinfo=UTC),
            ),
        ),
        (
            """Title: Wpływ
Text: Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.
Bank: Pekao""",
            PekaoNotification(
                title="Wpływ",
                text="Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.",
                bank="Pekao",
            ),
        ),
        (
            """Title: Wykonano operację BLIK
Text: Zapłacono BLIK-iem na kwotę 266,33 PLN z konta [redacted] w PAYPRO S.A.. Bank Pekao S.A.
Bank: Pekao""",
            PekaoNotification(
                title="Wykonano operację BLIK",
                text="Zapłacono BLIK-iem na kwotę 266,33 PLN z konta [redacted] w PAYPRO S.A.. Bank Pekao S.A.",
                bank="Pekao",
            ),
        ),
    ],
)
def test_from_message(message: str, expected_notification: PekaoNotification):
    assert PekaoNotification.from_message(message) == expected_notification


@pytest.mark.parametrize(
    ("notification", "expected_transaction_data"),
    [
        (
            PekaoNotification(
                title="Transakcja kartą",
                text="Zapłacono kwotę 90,45 PLN kartą *1000 dnia 23-09-2024 godz. 19:12:27 w CARREFOUR POL. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 23),
                account="Pekao",
                amount=-Decimal("90.45"),
                imported_payee="CARREFOUR POL",
            ),
        ),
        (
            PekaoNotification(
                title="Wpływ",
                text="Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 20),
                account="Pekao",
                amount=Decimal("30.99"),
                imported_payee="BANK PEKAO S.A.",
            ),
        ),
        (
            PekaoNotification(
                title="Wykonano Przelew",
                text="Wykonano przelew na kwotę 2100,00 PLN z konta 0111 na konto9398, odbiorca: JANUSZ KORWIN-MIKKE. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 20),
                account="Pekao",
                amount=-Decimal(2100),
                imported_payee="JANUSZ KORWIN-MIKKE",
            ),
        ),
        (
            PekaoNotification(
                title="Wykonano Przelew",
                text="Wykonano doładowanie telefonu 000 na kwotę 30,00 PLN z konta0000, operator: ATT. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 20),
                account="Pekao",
                amount=-Decimal("30.00"),
                imported_payee="ATT",
            ),
        ),
        (
            PekaoNotification(
                title="Wykonano Przelew",
                text=" Wykonano doładowanie telefonu 000 na kwotę 30,00 PLN z konta0000, operator: ATT. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 20),
                account="Pekao",
                amount=-Decimal("30.00"),
                imported_payee="ATT",
            ),
        ),
        (
            PekaoNotification(
                title="Wykonano operację BLIK",
                text="Zapłacono BLIK-iem na kwotę 266,33 PLN z konta [redacted] w PAYPRO S.A.. Bank Pekao S.A.",
                bank="Pekao",
            ),
            ActualTransactionData(
                date=date(2024, 9, 20),
                account="Pekao",
                amount=-Decimal("266.33"),
                imported_payee="PAYPRO S.A.",
            ),
        ),
    ],
)
def test_to_transaction(
    notification: PekaoNotification,
    expected_transaction_data: ActualTransactionData,
):
    assert (
        notification.to_transaction(
            timezone=ZoneInfo("Europe/Warsaw"), fallback_date=date(2024, 9, 20)
        )
        == expected_transaction_data
    )


def test_malformed_timestamp_falls_back_to_the_discord_message_date(caplog):
    notification = PekaoNotification.from_message(
        "Title: Wpływ\n"
        "Text: Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.\n"
        "Timestamp: not-a-timestamp"
    )

    transaction = notification.to_transaction(
        timezone=ZoneInfo("Europe/Warsaw"), fallback_date=date(2024, 9, 22)
    )

    assert transaction.date == date(2024, 9, 22)
    assert "Could not parse forwarded notification timestamp" in caplog.text


def test_forwarded_timestamp_uses_the_configured_timezone():
    notification = PekaoNotification.from_message(
        "Title: Wpływ\n"
        "Text: Wpłynęło 30,99 PLN na konto *0111 od BANK PEKAO S.A.. Bank Pekao S.A.\n"
        "Timestamp: 1727047800"
    )

    transaction = notification.to_transaction(
        timezone=ZoneInfo("Europe/Warsaw"), fallback_date=date(2024, 9, 1)
    )

    assert transaction.date == date(2024, 9, 23)
