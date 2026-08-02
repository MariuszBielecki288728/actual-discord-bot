"""Discord workflow for forwarded bank notifications."""

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from actual_discord_bot.actual_connector import (
    ActualConnector,
    ActualScheduleData,
    ScheduleCreationStatus,
)
from actual_discord_bot.bank_notifications import PekaoNotification
from actual_discord_bot.bank_notifications.base_notification import BaseNotification
from actual_discord_bot.channel_handlers.base import (
    SUCCESS_REACTION,
    BaseChannelHandler,
)
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.errors import ParseNotificationError, ScheduleSourceNotFound
from actual_discord_bot.schedules import ScheduleRecurrence

LOGGER = logging.getLogger(__name__)
ERROR_REACTION = "❌"
DEFAULT_NOTIFICATION_TIMEZONE = ZoneInfo("Europe/Warsaw")

NOTIFICATION_HELP_MESSAGE = """👋 **Hello! I am your Actual Budget notification assistant.**

I watch this channel for bank notifications and turn them into transactions in Actual Budget. Currently I understand Bank Pekao card payments, incoming and outgoing transfers, and phone top-ups forwarded in this format:
```
Title: <notification title>
Text: <notification text>
Timestamp: <timestamp>
```
I react with ✅ and reply with a summary when a transaction is created. If a notification cannot be read or imported, I react with ❌ and reply with the reason. Unexpected import errors are logged for troubleshooting.

`!catch_up` skips messages marked with my ✅ or ❌. Add a lookback such as `!catch_up 2 days` to process only recent messages. To request a retry, add any reaction to the message; I will try it again and remove that reaction afterwards, whether the retry succeeds or fails.

**How notifications reach this channel**
An administrator can create a Discord webhook for this channel in **Edit Channel → Integrations → Webhooks**. Its webhook URL is the special link that can post messages here—keep it private. On Android, an Automate flow can listen only for notifications from your bank app and send an HTTP POST to that URL, using `application/json` and the format above in the JSON `content` field. Never put your Discord bot token or Actual password in the flow or channel.

**Commands**
`!help` — show this notification guide
`!catch_up [X hour(s)|X day(s)|X month(s)]` — retry messages in this channel that do not already have my ✅
`!make_schedule [X day(s)|X week(s)|X month(s)|X year(s)]` — reply to a notification I marked ✅ to create a manual-approval recurring schedule. It defaults to monthly.
`!clear_channel` — permanently delete all deletable messages in this watched channel. Requires your Manage Messages permission."""


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
        timezone: ZoneInfo = DEFAULT_NOTIFICATION_TIMEZONE,
        actual_write_lock: asyncio.Lock | None = None,
    ) -> None:
        super().__init__(channel_name, NOTIFICATION_HELP_MESSAGE)
        self.actual_connector = actual_connector
        self.timezone = timezone
        self.notification_type = notification_type
        self.actual_write_lock = actual_write_lock

    def accepts(self, message: discord.Message) -> bool:
        return bool(message.content)

    async def handle(self, message: discord.Message) -> MessageHandlingResult:
        try:
            transaction_data = self._transaction_data_from_message(message)
            await self._save_transaction(transaction_data)
        except ParseNotificationError:
            LOGGER.info("Could not parse bank notification message %s", message.id)
            await message.add_reaction(ERROR_REACTION)
            await message.reply(
                "Could not import notification: its format is not supported. "
                "Check that it was forwarded in the expected format."
            )
            return MessageHandlingResult.FAILED
        except Exception:
            LOGGER.exception("Error importing bank notification message %s", message.id)
            await message.add_reaction(ERROR_REACTION)
            await message.reply(
                "An unexpected error occurred while importing the notification. "
                "The error has been logged."
            )
            return MessageHandlingResult.FAILED

        await message.add_reaction(SUCCESS_REACTION)
        await message.reply(
            _format_transaction_summary(transaction_data, self.actual_connector)
        )
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

    def _transaction_data_from_message(
        self, message: discord.Message
    ) -> ActualTransactionData:
        """Apply one source-date policy to imports and schedule creation."""
        notification = self.notification_type.from_message(message.content)
        created_at = message.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        fallback_date = created_at.astimezone(self.timezone).date()
        return notification.to_transaction(
            timezone=self.timezone,
            fallback_date=fallback_date,
        )

    async def make_schedule(
        self, ctx: commands.Context, recurrence: ScheduleRecurrence
    ) -> None:
        """Create an Actual schedule from the successfully imported reply target."""
        if self.channel is None or not _same_channel(ctx.channel, self.channel):
            await ctx.reply(
                "Error: This command can only be used in the bank notification channel."
            )
            return

        source_message = await self._referenced_notification(ctx)
        if source_message is None:
            return
        if not _has_success_reaction(source_message):
            await ctx.reply(
                "Error: Reply to a notification that I imported successfully (✅)."
            )
            return

        try:
            transaction_data = self._transaction_data_from_message(source_message)
        except ParseNotificationError:
            LOGGER.info(
                "Schedule source notification %s could not be parsed", source_message.id
            )
            await ctx.reply(
                "Error: The replied-to message is not a supported bank notification."
            )
            return

        payee = (transaction_data.imported_payee or "").strip()
        if not payee:
            await ctx.reply(
                "Error: The replied-to notification does not contain a payee."
            )
            return

        schedule_data = ActualScheduleData(
            start=transaction_data.date,
            account=transaction_data.account,
            amount=Decimal(str(transaction_data.amount)),
            payee=payee,
            name=payee,
            recurrence=recurrence,
        )
        try:
            status = await self._save_schedule(schedule_data)
        except ScheduleSourceNotFound:
            LOGGER.warning(
                "Schedule source account or payee was not found for message %s",
                source_message.id,
            )
            await ctx.reply(
                "Error: The notification's account or payee no longer exists in Actual. Nothing was changed."
            )
            return
        except Exception:
            LOGGER.exception(
                "Schedule creation failed for notification message %s",
                source_message.id,
            )
            await ctx.reply(
                "An unexpected error occurred while creating the schedule. The error has been logged."
            )
            return

        if status is ScheduleCreationStatus.ALREADY_EXISTS:
            LOGGER.info(
                "Schedule already exists for notification message %s", source_message.id
            )
            await ctx.reply(
                f"Schedule **{payee}** already exists. Nothing was changed."
            )
            return

        LOGGER.info("Created schedule for notification message %s", source_message.id)
        await ctx.reply(_format_schedule_summary(schedule_data))

    async def _referenced_notification(
        self, ctx: commands.Context
    ) -> discord.Message | None:
        """Resolve a reply target without allowing another channel's message."""
        reference = ctx.message.reference
        if reference is None or reference.message_id is None:
            await ctx.reply(
                "Error: Reply to a successfully imported bank notification first."
            )
            return None
        if reference.channel_id is not None and not _same_channel_id(
            reference.channel_id, self.channel
        ):
            await ctx.reply(
                "Error: Reply to a notification in this bank notification channel."
            )
            return None

        resolved = reference.resolved
        if resolved is not None and not isinstance(
            resolved, discord.DeletedReferencedMessage
        ):
            source_message = resolved
        else:
            try:
                source_message = await self.channel.fetch_message(reference.message_id)  # type: ignore[union-attr]
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                LOGGER.warning(
                    "Could not fetch schedule source notification %s",
                    reference.message_id,
                )
                await ctx.reply("Error: The replied-to notification is unavailable.")
                return None
        if not _same_channel(source_message.channel, self.channel):
            await ctx.reply(
                "Error: Reply to a notification in this bank notification channel."
            )
            return None
        return source_message

    async def _save_schedule(
        self, schedule_data: ActualScheduleData
    ) -> ScheduleCreationStatus:
        if self.actual_write_lock is None:
            return await asyncio.to_thread(
                self.actual_connector.create_schedule, schedule_data
            )
        async with self.actual_write_lock:
            return await asyncio.to_thread(
                self.actual_connector.create_schedule, schedule_data
            )

    async def catch_up(
        self, ctx: commands.Context, *, after: datetime | None = None
    ) -> None:
        """Retry unmarked messages and messages explicitly marked by a user."""
        if self.channel is None:
            await ctx.send(f"Error: Channel '{self.channel_name}' not found.")
            return

        processed_count = 0
        async with ctx.typing():
            history = (
                self.channel.history(limit=None, after=after)
                if after is not None
                else self.channel.history(limit=None)
            )
            async for message in history:
                if not self._should_retry(message):
                    continue
                try:
                    await self.handle(message)
                finally:
                    await self._remove_external_reactions(message)
                processed_count += 1

        await ctx.send(f"Catch-up complete. Processed {processed_count} messages.")

    @staticmethod
    def _should_retry(message: discord.Message) -> bool:
        """Return whether a message has no bot status or has a user retry marker."""
        has_bot_status = any(
            reaction.emoji in {SUCCESS_REACTION, ERROR_REACTION} and reaction.me
            for reaction in message.reactions
        )
        has_external_reaction = any(
            not reaction.me or (isinstance(reaction.count, int) and reaction.count > 1)
            for reaction in message.reactions
        )
        return not has_bot_status or has_external_reaction

    @staticmethod
    async def _remove_external_reactions(message: discord.Message) -> None:
        """Remove user retry markers without clearing this bot's status reactions."""
        for reaction in message.reactions:
            async for user in reaction.users():
                if user.bot:
                    continue
                try:
                    await message.remove_reaction(reaction.emoji, user)
                except discord.HTTPException:
                    LOGGER.warning(
                        "Could not remove retry reaction from bank notification message %s",
                        message.id,
                    )


def _format_transaction_summary(
    transaction_data: ActualTransactionData, actual_connector: ActualConnector
) -> str:
    """Format the details that Actual assigns to notification transactions."""
    payee = transaction_data.imported_payee or "Unknown payee"
    budget = actual_connector.config.file
    return (
        f"Created transaction: **{payee}**, {abs(transaction_data.amount)} PLN\n"
        f"Budget: **{budget}** · Account: **{transaction_data.account}** · "
        "Category: *Uncategorized*"
    )


def _same_channel(left: object, right: object) -> bool:
    """Compare Discord channels by identity or stable ID."""
    return left is right or _same_channel_id(getattr(left, "id", None), right)


def _same_channel_id(channel_id: object, channel: object) -> bool:
    return isinstance(channel_id, int) and channel_id == getattr(channel, "id", None)


def _has_success_reaction(message: discord.Message) -> bool:
    return any(
        reaction.emoji == SUCCESS_REACTION and reaction.me
        for reaction in message.reactions
    )


def _format_schedule_summary(schedule_data: ActualScheduleData) -> str:
    frequency = schedule_data.recurrence.frequency.value.removesuffix("ly")
    interval = schedule_data.recurrence.interval
    unit = frequency if interval == 1 else f"{frequency}s"
    return (
        f"Created schedule: **{schedule_data.name}**\n"
        f"Every {interval} {unit} from {schedule_data.start.isoformat()} · "
        f"{abs(schedule_data.amount)} PLN · Account: **{schedule_data.account}**\n"
        "Transactions require manual approval."
    )
