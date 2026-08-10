import decimal
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import ClassVar, Self, cast
from zoneinfo import ZoneInfo

from babel.numbers import parse_decimal

from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.enums import TransactionType
from actual_discord_bot.errors import ParseNotificationError

LOGGER = logging.getLogger(__name__)


@dataclass
class NotificationTemplate:
    regexp: re.Pattern
    type_: TransactionType


@dataclass
class BaseNotification:
    title: str
    text: str
    bank: str
    occurred_at: datetime | None = None

    _message_regexes: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(
            r"^Title: (?P<title>[^\n]+)\nText: (?P<text>.+)\nTimestamp: "
            r"(?P<timestamp>[^\n]+)$",
            re.DOTALL,
        ),
        re.compile(
            r"^Title: (?P<title>[^\n]+)\nText: (?P<text>.+)\nBank: "
            r"(?P<bank>[^\n]+)$",
            re.DOTALL,
        ),
    )
    _notification_regexes: ClassVar[Sequence[NotificationTemplate]]

    @classmethod
    def from_message(cls, message: str) -> Self:
        matched, _ = cls._match_any_regex(message, cls._message_regexes)

        return cls(
            title=matched["title"],
            text=matched["text"],
            bank=cast("str", matched.get("bank") or getattr(cls, "bank", "")),
            occurred_at=cls._parse_occurred_at(matched.get("timestamp")),
        )

    @classmethod
    def _match_any_regex(
        cls,
        text: str,
        regexes: Sequence[re.Pattern[str]],
    ) -> tuple[dict[str, str], int]:
        for index, regex in enumerate(regexes):
            if matched := regex.match(text):
                return matched.groupdict(), index

        raise ParseNotificationError(text)

    def to_transaction(
        self,
        *,
        timezone: ZoneInfo,
        fallback_date: date,
    ) -> ActualTransactionData:
        """Convert this notification using its body, envelope, then Discord date."""
        matched, match_index = self._match_any_regex(
            self.text,
            [notif_tpl.regexp for notif_tpl in self._notification_regexes],
        )
        notification_type = self._notification_regexes[match_index].type_
        raw_date = matched.get("transaction_date")
        if raw_date:
            transaction_date = (
                datetime.strptime(raw_date, "%d-%m-%Y").replace(tzinfo=timezone).date()
            )
        elif self.occurred_at is not None:
            transaction_date = self.occurred_at.astimezone(timezone).date()
        else:
            transaction_date = fallback_date

        return ActualTransactionData(
            date=transaction_date,
            account=self.bank,
            amount=notification_type.get_signed_amount(
                self._parse_amount(matched["amount"]),
            ),
            imported_payee=matched["payee"].strip(),
        )

    @staticmethod
    def _parse_occurred_at(timestamp: str | None) -> datetime | None:
        if timestamp is None:
            return None
        try:
            seconds = decimal.Decimal(timestamp.strip())
            if not seconds.is_finite():
                LOGGER.warning("Could not parse forwarded notification timestamp")
                return None
            return datetime.fromtimestamp(float(seconds), tz=UTC)
        except (decimal.InvalidOperation, OSError, OverflowError, ValueError):
            LOGGER.warning("Could not parse forwarded notification timestamp")
            return None

    @staticmethod
    def _parse_amount(amount: str) -> decimal.Decimal:
        return parse_decimal(amount, locale="pl")
