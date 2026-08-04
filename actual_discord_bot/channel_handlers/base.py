"""Common lifecycle behavior for configured Discord channels."""

import logging
import traceback
from abc import ABC, abstractmethod
from collections.abc import Iterable

import discord

LOGGER = logging.getLogger(__name__)
SUCCESS_REACTION = "✅"
MAX_DISCORD_MESSAGE_LENGTH = 2_000


class BaseChannelHandler(ABC):
    """Base class for a Discord feature attached to one configured text channel."""

    def __init__(self, channel_name: str, help_message: str) -> None:
        self.channel_name = channel_name
        self.help_message = help_message
        self.channel: discord.TextChannel | None = None
        self._startup_help_sent = False

    def bind(self, guilds: Iterable[discord.Guild]) -> None:
        """Bind to the first matching text channel across all available guilds."""
        self.channel = next(
            (
                channel
                for guild in guilds
                for channel in guild.channels
                if isinstance(channel, discord.TextChannel)
                and channel.name == self.channel_name
            ),
            None,
        )
        if self.channel is None:
            LOGGER.warning(
                "Could not find configured %s channel '%s'",
                type(self).__name__,
                self.channel_name,
            )

    def matches(self, channel: object) -> bool:
        """Return whether a Discord channel is this handler's bound channel."""
        return (
            self.channel is not None and getattr(channel, "id", None) == self.channel.id
        )

    async def announce_help(self, bot_user: discord.ClientUser | None) -> None:
        """Post this handler's guide once unless it was posted recently."""
        if self._startup_help_sent:
            return
        self._startup_help_sent = True
        if self.channel is None:
            return

        try:
            if await self._has_recent_guide(bot_user):
                return
            await self.channel.send(self.help_message)
        except (discord.Forbidden, discord.HTTPException) as error:
            LOGGER.warning(
                "Could not send startup help to '%s': %s",
                self.channel_name,
                error,
            )

    async def _has_recent_guide(self, bot_user: discord.ClientUser | None) -> bool:
        if self.channel is None:
            return False
        async for message in self.channel.history(limit=10):
            if message.author == bot_user and message.content == self.help_message:
                return True
        return False

    @abstractmethod
    def accepts(self, message: discord.Message) -> bool:
        """Return whether this handler should process a message in its channel."""

    @abstractmethod
    async def handle(self, message: discord.Message) -> object:
        """Handle a message accepted by this channel workflow."""


def format_unexpected_error(
    message: str, error: BaseException, *, show_traceback: bool
) -> str:
    """Return a Discord-safe unexpected-error message, optionally with its traceback."""
    if not show_traceback:
        return f"{message} The error has been logged."

    prefix = f"{message}\n**Traceback**\n```py\n"
    suffix = "\n```"
    formatted_traceback = (
        "".join(traceback.format_exception(error)).strip().replace("```", "``\u200b`")
    )
    max_traceback_length = MAX_DISCORD_MESSAGE_LENGTH - len(prefix) - len(suffix)
    if len(formatted_traceback) > max_traceback_length:
        truncation_notice = "\n... traceback truncated"
        formatted_traceback = (
            formatted_traceback[
                : max_traceback_length - len(truncation_notice)
            ].rstrip()
            + truncation_notice
        )
    return f"{prefix}{formatted_traceback}{suffix}"
