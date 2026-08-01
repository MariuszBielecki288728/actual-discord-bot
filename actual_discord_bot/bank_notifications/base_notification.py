import decimal
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Self, cast

from babel.numbers import parse_decimal

from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.enums import TransactionType
from actual_discord_bot.errors import ParseNotificationError


@dataclass
class NotificationTemplate:
    regexp: re.Pattern
    type_: TransactionType


@dataclass
class BaseNotification:
    title: str
    text: str
    bank: str

    _message_regexes: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"Title: (?P<title>.+)\nText: (?P<text>.+)\nTimestamp: .+"),
        re.compile(r"Title: (?P<title>.+)\nText: (?P<text>.+)\nBank: (?P<bank>.+)"),
    )
    _notification_regexes: ClassVar[Sequence[NotificationTemplate]]

    @classmethod
    def from_message(cls, message: str) -> Self:
        matched, _ = cls._match_any_regex(message, cls._message_regexes)

        return cls(
            title=matched["title"],
            text=matched["text"],
            bank=cast("str", matched.get("bank") or getattr(cls, "bank", "")),
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

    def to_transaction(self) -> ActualTransactionData:
        matched, match_index = self._match_any_regex(
            self.text,
            [notif_tpl.regexp for notif_tpl in self._notification_regexes],
        )
        notification_type = self._notification_regexes[match_index].type_

        return ActualTransactionData(
            date=datetime.now(tz=UTC).date(),
            account=self.bank,
            amount=notification_type.get_signed_amount(
                self._parse_amount(matched["amount"]),
            ),
            imported_payee=matched["payee"],
        )

    @staticmethod
    def _parse_amount(amount: str) -> decimal.Decimal:
        return parse_decimal(amount, locale="pl")
