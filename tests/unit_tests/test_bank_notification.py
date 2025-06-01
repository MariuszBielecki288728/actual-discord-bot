from datetime import UTC, datetime
from decimal import Decimal

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
                date=datetime.now(tz=UTC).date(),
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
                date=datetime.now(tz=UTC).date(),
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
                date=datetime.now(tz=UTC).date(),
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
                date=datetime.now(tz=UTC).date(),
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
                date=datetime.now(tz=UTC).date(),
                account="Pekao",
                amount=-Decimal("30.00"),
                imported_payee="ATT",
            ),
        ),
    ],
)
def test_to_transaction(
    notification: PekaoNotification,
    expected_transaction_data: ActualTransactionData,
):
    assert notification.to_transaction() == expected_transaction_data
