"""Discord workflow for forwarded bank notifications."""

import asyncio
import logging
from enum import StrEnum

import discord
from discord.ext import commands

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.bank_notifications import PekaoNotification
from actual_discord_bot.bank_notifications.base_notification import BaseNotification
from actual_discord_bot.channel_handlers.base import (
    SUCCESS_REACTION,
    BaseChannelHandler,
)
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.errors import ParseNotificationError

LOGGER = logging.getLogger(__name__)

NOTIFICATION_HELP_MESSAGE = """👋 **Hello! I am your Actual Budget notification assistant.**

I watch this channel for bank notifications and turn them into transactions in Actual Budget. Currently I understand Bank Pekao card payments, incoming and outgoing transfers, and phone top-ups forwarded in this format:
```
Title: <notification title>
Text: <notification text>
Timestamp: <timestamp>
```
A ✅ means the transaction was saved. A message without ✅ was not imported; check the bot logs, correct the cause if needed, and run `!catch_up`.

**How notifications reach this channel**
An administrator can create a Discord webhook for this channel in **Edit Channel → Integrations → Webhooks**. Its webhook URL is the special link that can post messages here—keep it private. On Android, an Automate flow can listen only for notifications from your bank app and send an HTTP POST to that URL, using `application/json` and the format above in the JSON `content` field. Never put your Discord bot token or Actual password in the flow or channel.

**Commands**
`!help` — show this notification guide
`!catch_up` — retry messages in this channel that do not already have my ✅"""


class MessageHandlingResult(StrEnum):
    """The outcome of handling one notification message."""

    IMPORTED = "imported"
    FAILED = "failed"


class NotificationChannelHandler(BaseChannelHandler):
    """Parse and persist forwarded bank notifications."""

    def __init__(
        self,
        channel_name: str,
        actual_connector: ActualConnector,
        notification_type: type[BaseNotification] = PekaoNotification,
        actual_write_lock: asyncio.Lock | None = None,
    ) -> None:
        super().__init__(channel_name, NOTIFICATION_HELP_MESSAGE)
        self.actual_connector = actual_connector
        self.notification_type = notification_type
        self.actual_write_lock = actual_write_lock

    def accepts(self, message: discord.Message) -> bool:
        return bool(message.content)

    async def handle(self, message: discord.Message) -> MessageHandlingResult:
        try:
            notification = self.notification_type.from_message(message.content)
            transaction_data = notification.to_transaction()
            await self._save_transaction(transaction_data)
        except ParseNotificationError:
            LOGGER.info("Could not parse bank notification message %s", message.id)
            return MessageHandlingResult.FAILED
        except Exception:
            LOGGER.exception("Error importing bank notification message %s", message.id)
            return MessageHandlingResult.FAILED

        await message.add_reaction(SUCCESS_REACTION)
        return MessageHandlingResult.IMPORTED

    async def _save_transaction(self, transaction_data: ActualTransactionData) -> None:
        if self.actual_write_lock is None:
            await asyncio.to_thread(
                self.actual_connector.save_transaction, transaction_data
            )
            return
        async with self.actual_write_lock:
            await asyncio.to_thread(
                self.actual_connector.save_transaction, transaction_data
            )

    async def catch_up(self, ctx: commands.Context) -> None:
        """Retry all messages that do not already have this bot's success reaction."""
        if self.channel is None:
            await ctx.send(f"Error: Channel '{self.channel_name}' not found.")
            return

        processed_count = 0
        async with ctx.typing():
            async for message in self.channel.history(limit=None):
                if self._has_success_reaction(message):
                    continue
                await self.handle(message)
                processed_count += 1

        await ctx.send(f"Catch-up complete. Processed {processed_count} messages.")

    @staticmethod
    def _has_success_reaction(message: discord.Message) -> bool:
        return any(
            reaction.emoji == SUCCESS_REACTION and reaction.me
            for reaction in message.reactions
        )
