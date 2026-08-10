import re
from dataclasses import dataclass

from actual_discord_bot.bank_notifications.base_notification import (
    BaseNotification,
    NotificationTemplate,
)
from actual_discord_bot.enums import TransactionType


@dataclass
class RevolutNotification(BaseNotification):
    bank: str = "Revolut"

    _notification_regexes = (
        NotificationTemplate(
            re.compile(
                r"Zapłacono (?P<amount>\d{1,3}(?:[ .]\d{3})*,\d{2}) zł w: "
                r"(?P<payee>.+?)\."
            ),
            TransactionType.PAYMENT,
        ),
    )
