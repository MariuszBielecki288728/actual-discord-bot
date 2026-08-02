"""Discord lifecycle, commands, and routing."""

import asyncio
import calendar
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from cogwatch import Watcher  # type: ignore[import-untyped]
from discord.ext import commands

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.channel_handlers.notifications import NotificationChannelHandler
from actual_discord_bot.channel_handlers.receipts import ReceiptChannelHandler
from actual_discord_bot.config import ActualConfig, DiscordConfig
from actual_discord_bot.receipts.ocr_provider import OCRConfig, create_ocr_provider
from actual_discord_bot.receipts.processor import ReceiptProcessor

if TYPE_CHECKING:
    from actual_discord_bot.channel_handlers.base import BaseChannelHandler

LOGGER = logging.getLogger(__name__)

CATCH_UP_TIME_DELTA_ERROR = (
    "Error: Invalid time delta. Use X hour(s), X day(s), or X month(s)."
)
_CATCH_UP_TIME_DELTA_PATTERN = re.compile(
    r"(?P<count>[1-9]\d*)\s+(?P<unit>hours?|days?|months?)",
    re.IGNORECASE,
)


class CatchUpTimeDeltaError(ValueError):
    """Raised when a catch-up time delta does not use a supported format."""


class ActualDiscordBot(commands.Bot):
    """Route Discord events to independently owned channel workflows."""

    def __init__(
        self,
        notification_handler: NotificationChannelHandler,
        receipt_handler: ReceiptChannelHandler | None = None,
        *,
        hot_reload: bool = False,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.notification_handler = notification_handler
        self.receipt_handler = receipt_handler
        self.hot_reload = hot_reload

        async def catch_up_command(
            ctx: commands.Context, *, time_delta: str = ""
        ) -> None:
            await self._catch_up(ctx, time_delta)

        async def help_command(ctx: commands.Context) -> None:
            await self._help(ctx)

        self.add_command(commands.Command(catch_up_command, name="catch_up"))
        self.add_command(commands.Command(help_command, name="help"))
        self.handlers: tuple[BaseChannelHandler, ...] = tuple(
            handler
            for handler in (receipt_handler, notification_handler)
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
        """Retry notification messages that have not yet been imported."""
        try:
            after = parse_catch_up_after(time_delta, discord.utils.utcnow())
        except CatchUpTimeDeltaError:
            await ctx.send(CATCH_UP_TIME_DELTA_ERROR)
            return

        if after is None:
            await self.notification_handler.catch_up(ctx)
            return
        await self.notification_handler.catch_up(ctx, after=after)

    async def _help(self, ctx: commands.Context) -> None:
        """Show the guide or guides for the current channel."""
        matching_handlers = [
            handler for handler in self.handlers if handler.matches(ctx.channel)
        ]
        if not matching_handlers:
            matching_handlers = [self.notification_handler]
        for handler in matching_handlers:
            await ctx.send(handler.help_message)


def parse_catch_up_after(time_delta: str, now: datetime) -> datetime | None:
    """
    Return the earliest message time for a catch-up time delta.

    An empty argument means to process the full channel history. Months are
    calendar months, clamped to the last valid day of the target month.
    """
    if not time_delta.strip():
        return None

    match = _CATCH_UP_TIME_DELTA_PATTERN.fullmatch(time_delta.strip())
    if match is None:
        raise CatchUpTimeDeltaError

    count = int(match["count"])
    unit = match["unit"].lower()
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
    actual_config = ActualConfig.from_environ()  # type: ignore[attr-defined]
    actual_connector = ActualConnector(actual_config)
    actual_write_lock = asyncio.Lock()
    notification_handler = NotificationChannelHandler(
        discord_config.bank_notification_channel,
        actual_connector,
        actual_write_lock=actual_write_lock,
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
        )
    client = ActualDiscordBot(
        notification_handler,
        receipt_handler,
        hot_reload=discord_config.hot_reload,
    )
    await client.start(discord_config.token)


if __name__ == "__main__":
    asyncio.run(main())
