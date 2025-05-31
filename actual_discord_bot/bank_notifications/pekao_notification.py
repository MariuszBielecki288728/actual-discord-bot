import re
from dataclasses import dataclass

from actual_discord_bot.bank_notifications.base_notification import (
    BaseNotification,
    NotificationTemplate,
)
from actual_discord_bot.enums import TransactionType


@dataclass
class PekaoNotification(BaseNotification):
    bank: str = "Pekao"

    _notification_regexes = (
        NotificationTemplate(
            re.compile(
                r"Wpłynęło (?P<amount>.+) PLN na konto .* "
                r"od (?P<payee>.+)\. Bank Pekao S\.A\.",
            ),
            TransactionType.DEPOSIT,
        ),
        NotificationTemplate(
            re.compile(
                r"Wykonano przelew na kwotę (?P<amount>.+) PLN z konta .+ "
                r"na konto.+, odbiorca: (?P<payee>.+)\. Bank Pekao S\.A\.",
            ),
            TransactionType.PAYMENT,
        ),
        NotificationTemplate(
            re.compile(
                r"Zapłacono kwotę (?P<amount>.+) PLN kartą .+ dnia .+ w (?P<payee>.+)\. Bank Pekao S\.A\.",
            ),
            TransactionType.PAYMENT,
        ),
        NotificationTemplate(
            re.compile(
                r" Wykonano doładowanie telefonu .+ na kwotę (?P<amount>.+) PLN z konta.+, operator: (?P<payee>.+)\. Bank Pekao S\.A\.",
            ),
            TransactionType.PAYMENT,
        ),
    )
