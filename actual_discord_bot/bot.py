"""Discord lifecycle, commands, and routing."""

import asyncio
import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from cogwatch import Watcher  # type: ignore[import-untyped]
from discord.ext import commands

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.channel_handlers.bank_imports import BankImportChannelHandler
from actual_discord_bot.channel_handlers.notifications import NotificationChannelHandler
from actual_discord_bot.channel_handlers.receipts import ReceiptChannelHandler
from actual_discord_bot.config import (
    ActualConfig,
    BankImportConfig,
    BankNotificationConfig,
    DiscordConfig,
)
from actual_discord_bot.receipts.ocr_provider import OCRConfig, create_ocr_provider
from actual_discord_bot.receipts.processor import ReceiptProcessor
from actual_discord_bot.schedules import (
    TimeDeltaError,
    parse_schedule_recurrence,
    parse_time_delta,
)

if TYPE_CHECKING:
    from actual_discord_bot.channel_handlers.base import BaseChannelHandler

LOGGER = logging.getLogger(__name__)

CATCH_UP_TIME_DELTA_ERROR = (
    "Error: Invalid time delta. Use X hour(s), X day(s), or X month(s)."
)
CATCH_UP_CHANNEL_ERROR = (
    "Error: This command can only be used in a configured watched channel."
)
BULK_DELETE_SAFE_AGE = timedelta(days=13, hours=23)
MAX_BULK_DELETE_MESSAGES = 100


@dataclass(frozen=True)
class ClearChannelResult:
    """Outcome of a watched-channel history deletion."""

    deleted_count: int
    incomplete: bool


class CatchUpTimeDeltaError(TimeDeltaError):
    """Raised when a catch-up time delta does not use a supported format."""


class ActualDiscordBot(commands.Bot):
    """Route Discord events to independently owned channel workflows."""

    def __init__(
        self,
        notification_handler: NotificationChannelHandler,
        receipt_handler: ReceiptChannelHandler | None = None,
        bank_import_handler: BankImportChannelHandler | None = None,
        *,
        hot_reload: bool = False,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.notification_handler = notification_handler
        self.receipt_handler = receipt_handler
        self.bank_import_handler = bank_import_handler
        self.hot_reload = hot_reload
        self._clear_channel_locks: dict[int, asyncio.Lock] = {}

        async def catch_up_command(
            ctx: commands.Context, *, time_delta: str = ""
        ) -> None:
            await self._catch_up(ctx, time_delta)

        async def help_command(ctx: commands.Context) -> None:
            await self._help(ctx)

        async def clear_channel_command(ctx: commands.Context) -> None:
            await self._clear_channel(ctx)

        async def make_schedule_command(
            ctx: commands.Context, *, time_delta: str = ""
        ) -> None:
            await self._make_schedule(ctx, time_delta)

        self.add_command(commands.Command(catch_up_command, name="catch_up"))
        self.add_command(commands.Command(clear_channel_command, name="clear_channel"))
        self.add_command(commands.Command(help_command, name="help"))
        self.add_command(commands.Command(make_schedule_command, name="make_schedule"))
        self.handlers: tuple[BaseChannelHandler, ...] = tuple(
            handler
            for handler in (bank_import_handler, receipt_handler, notification_handler)
            if handler is not None
        )

    async def setup_hook(self) -> None:
        """Start development hot reload only when its watched source tree exists."""
        if not self.hot_reload:
            return

        source_path = Path("actual_discord_bot")
        if not source_path.is_dir():
            LOGGER.warning(
                "Discord hot reload is enabled but %s does not exist; continuing without it",
                source_path.resolve(),
            )
            return

        await Watcher(self, path=str(source_path)).start()

    async def on_ready(self) -> None:
        for handler in self.handlers:
            handler.bind(self.guilds)
        for handler in self.handlers:
            await handler.announce_help(self.user)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        context = await self.get_context(message)
        if context.valid:
            await self.invoke(context)
            return
        for handler in self.handlers:
            if handler.matches(message.channel) and handler.accepts(message):
                try:
                    await handler.handle(message)
                except Exception:
                    LOGGER.exception(
                        "Channel handler failed for message %s", message.id
                    )
                return

    async def _catch_up(self, ctx: commands.Context, time_delta: str = "") -> None:
        """Reprocess eligible history in the invoking watched channel."""
        handler = next(
            (handler for handler in self.handlers if handler.matches(ctx.channel)), None
        )
        if handler is None:
            await ctx.send(CATCH_UP_CHANNEL_ERROR)
            return

        try:
            after = parse_catch_up_after(time_delta, discord.utils.utcnow())
        except CatchUpTimeDeltaError:
            await ctx.send(CATCH_UP_TIME_DELTA_ERROR)
            return

        if after is None:
            await handler.catch_up(ctx)
            return
        await handler.catch_up(ctx, after=after)

    async def _help(self, ctx: commands.Context) -> None:
        """Show the guide or guides for the current channel."""
        matching_handlers = [
            handler for handler in self.handlers if handler.matches(ctx.channel)
        ]
        if not matching_handlers:
            matching_handlers = [self.notification_handler]
        for handler in matching_handlers:
            await ctx.send(handler.help_message)

    async def _clear_channel(self, ctx: commands.Context) -> None:
        """Delete every deletable message in the invoking watched channel."""
        if not any(handler.matches(ctx.channel) for handler in self.handlers):
            await ctx.send(
                "Error: This command can only be used in a configured watched channel."
            )
            return

        if not isinstance(ctx.channel, discord.TextChannel) or not isinstance(
            ctx.author, discord.Member
        ):
            await ctx.send("Error: This command can only be used in a server text channel.")
            return

        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            await ctx.send(
                "Error: You need the Manage Messages permission to clear this channel."
            )
            return

        lock = self._clear_channel_locks.setdefault(ctx.channel.id, asyncio.Lock())
        async with lock:
            result = await delete_channel_history(ctx.channel)

        if result.incomplete:
            await ctx.send(
                f"Channel clear incomplete. Deleted {result.deleted_count} messages."
            )
            return
        await ctx.send(f"Channel cleared. Deleted {result.deleted_count} messages.")

    async def _make_schedule(self, ctx: commands.Context, time_delta: str = "") -> None:
        """Create a recurring schedule from a successfully imported reply target."""
        try:
            recurrence = parse_schedule_recurrence(time_delta)
        except TimeDeltaError:
            await ctx.reply(
                "Error: Invalid recurrence. Use X day(s), X week(s), X month(s), or X year(s)."
            )
            return
        await self.notification_handler.make_schedule(ctx, recurrence)


async def delete_channel_history(channel: discord.TextChannel) -> ClearChannelResult:
    """Delete channel history while retaining an accurate success count."""
    deleted_count = 0
    skipped_message = False
    recent_messages: list[discord.Message] = []
    bulk_delete_after = discord.utils.utcnow() - BULK_DELETE_SAFE_AGE

    async def delete_recent_messages() -> None:
        nonlocal deleted_count
        if not recent_messages:
            return
        if len(recent_messages) == 1:
            await recent_messages[0].delete()
        else:
            await channel.delete_messages(list(recent_messages))
        deleted_count += len(recent_messages)
        recent_messages.clear()

    try:
        async for message in channel.history(limit=None):
            if not message.type.is_deletable():
                skipped_message = True
                continue

            if message.created_at <= bulk_delete_after:
                await delete_recent_messages()
                await message.delete()
                deleted_count += 1
                continue

            recent_messages.append(message)
            if len(recent_messages) == MAX_BULK_DELETE_MESSAGES:
                await delete_recent_messages()

        await delete_recent_messages()
    except (discord.Forbidden, discord.HTTPException):
        LOGGER.exception("Could not completely clear Discord channel %s", channel.id)
        return ClearChannelResult(deleted_count, incomplete=True)

    return ClearChannelResult(deleted_count, incomplete=skipped_message)


def parse_catch_up_after(time_delta: str, now: datetime) -> datetime | None:
    """
    Return the earliest message time for a catch-up time delta.

    An empty argument means to process the full channel history. Months are
    calendar months, clamped to the last valid day of the target month.
    """
    if not time_delta.strip():
        return None

    try:
        count, unit = parse_time_delta(
            time_delta,
            allowed_units={"hour", "day", "month"},
        )
    except TimeDeltaError as error:
        raise CatchUpTimeDeltaError from error
    if unit.startswith("hour"):
        return now - timedelta(hours=count)
    if unit.startswith("day"):
        return now - timedelta(days=count)

    target_month_index = now.year * 12 + now.month - 1 - count
    target_year, target_month_index = divmod(target_month_index, 12)
    target_month = target_month_index + 1
    target_day = min(now.day, calendar.monthrange(target_year, target_month)[1])
    return now.replace(year=target_year, month=target_month, day=target_day)


async def main() -> None:
    discord_config = DiscordConfig.from_environ()  # type: ignore[attr-defined]
    bank_import_config = BankImportConfig.from_environ()  # type: ignore[attr-defined]
    bank_notification_config = BankNotificationConfig.from_environ()  # type: ignore[attr-defined]
    actual_config = ActualConfig.from_environ()  # type: ignore[attr-defined]
    actual_connector = ActualConnector(actual_config)
    actual_write_lock = asyncio.Lock()
    notification_handler = NotificationChannelHandler(
        discord_config.bank_notification_channel,
        actual_connector,
        timezone=bank_notification_config.timezone,
        actual_write_lock=actual_write_lock,
        show_error_tracebacks=discord_config.show_error_tracebacks,
    )
    receipt_handler = None
    if discord_config.receipt_channel:
        ocr_provider = create_ocr_provider(
            OCRConfig.from_environ()  # type: ignore[attr-defined]
        )
        receipt_processor = ReceiptProcessor(ocr_provider=ocr_provider)
        receipt_handler = ReceiptChannelHandler(
            discord_config.receipt_channel,
            actual_connector,
            receipt_processor,
            actual_write_lock=actual_write_lock,
            show_error_tracebacks=discord_config.show_error_tracebacks,
        )
    bank_import_handler = None
    bank_import_channel = getattr(discord_config, "bank_import_channel", "")
    if isinstance(bank_import_channel, str) and bank_import_channel:
        bank_import_handler = BankImportChannelHandler(
            bank_import_channel,
            actual_connector,
            bank_import_config.timezone,
            actual_write_lock=actual_write_lock,
        )
    client = ActualDiscordBot(
        notification_handler,
        receipt_handler,
        bank_import_handler,
        hot_reload=discord_config.hot_reload,
    )
    await client.start(discord_config.token)


if __name__ == "__main__":
    asyncio.run(main())
