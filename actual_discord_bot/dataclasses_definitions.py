import decimal
from dataclasses import dataclass
from datetime import date


@dataclass
class ActualTransactionData:
    date: date
    account: str
    amount: decimal.Decimal | float | int

    imported_payee: str | None = None
    notes: str = ""


def notification_transaction_note(message_id: int) -> str:
    """Return the stable Actual note used to find a Discord notification later."""
    return f"Discord notification: {message_id}"
