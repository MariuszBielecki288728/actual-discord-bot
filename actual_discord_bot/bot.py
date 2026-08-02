"""Discord lifecycle, commands, and routing."""

import asyncio
import logging
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

        async def catch_up_command(ctx: commands.Context) -> None:
            await self._catch_up(ctx)

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

    async def _catch_up(self, ctx: commands.Context) -> None:
        """Retry notification messages that have not yet been imported."""
        await self.notification_handler.catch_up(ctx)

    async def _help(self, ctx: commands.Context) -> None:
        """Show the guide or guides for the current channel."""
        matching_handlers = [
            handler for handler in self.handlers if handler.matches(ctx.channel)
        ]
        if not matching_handlers:
            matching_handlers = [self.notification_handler]
        for handler in matching_handlers:
            await ctx.send(handler.help_message)


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
