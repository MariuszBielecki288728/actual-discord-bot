from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from actual_discord_bot.channel_handlers.base import BaseChannelHandler


class SampleHandler(BaseChannelHandler):
    def __init__(self):
        super().__init__("target", "guide")

    def accepts(self, message):
        return True

    async def handle(self, message):
        return None


def test_binding_scans_later_guilds():
    handler = SampleHandler()
    target = MagicMock(spec=discord.TextChannel)
    target.name = "target"
    first = MagicMock(channels=[])
    second = MagicMock(channels=[target])
    handler.bind([first, second])
    assert handler.channel is target


@pytest.mark.asyncio
async def test_guide_is_sent_once_and_skips_recent_bot_guide():
    handler = SampleHandler()
    channel = AsyncMock(spec=discord.TextChannel)
    channel.name = "target"
    handler.channel = channel
    bot_user = MagicMock()
    channel.history.return_value.__aiter__.return_value = [
        MagicMock(author=bot_user, content="guide")
    ]
    await handler.announce_help(bot_user)
    await handler.announce_help(bot_user)
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_catch_up_reprocesses_accepted_non_bot_messages():
    handler = SampleHandler()
    channel = AsyncMock(spec=discord.TextChannel)
    handler.channel = channel
    bot_user = MagicMock()
    bot_message = MagicMock(author=bot_user)
    user_message = MagicMock(author=MagicMock())
    channel.history.return_value.__aiter__.return_value = [bot_message, user_message]
    handler.handle = AsyncMock()
    ctx = MagicMock()
    ctx.bot.user = bot_user
    ctx.send = AsyncMock()
    ctx.typing.return_value.__aenter__ = AsyncMock(return_value=None)
    ctx.typing.return_value.__aexit__ = AsyncMock(return_value=None)

    await handler.catch_up(ctx)

    handler.handle.assert_awaited_once_with(user_message)
    ctx.send.assert_awaited_once_with("Catch-up complete. Processed 1 messages.")
