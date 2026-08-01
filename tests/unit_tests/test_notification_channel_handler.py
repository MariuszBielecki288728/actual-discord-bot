from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from actual_discord_bot.channel_handlers.notifications import (
    MessageHandlingResult,
    NotificationChannelHandler,
)
from actual_discord_bot.errors import ParseNotificationError


@pytest.fixture
def handler():
    return NotificationChannelHandler("bank", MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_successful_notification_is_saved_in_a_worker_and_reacted(handler):
    message = AsyncMock(spec=discord.Message)
    message.id = 1
    message.content = "notification"
    notification = MagicMock()
    handler.notification_type.from_message.return_value = notification
    result = await handler.handle(message)
    assert result is MessageHandlingResult.IMPORTED
    handler.actual_connector.save_transaction.assert_called_once_with(
        notification.to_transaction.return_value
    )
    message.add_reaction.assert_awaited_once_with("✅")


@pytest.mark.asyncio
async def test_parse_error_does_not_add_success_reaction(handler):
    message = AsyncMock(spec=discord.Message)
    message.id = 1
    message.content = "invalid"
    handler.notification_type.from_message.side_effect = ParseNotificationError(
        "invalid"
    )
    result = await handler.handle(message)
    assert result is MessageHandlingResult.FAILED
    message.add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_catch_up_skips_only_own_success_reactions(handler):
    channel = AsyncMock(spec=discord.TextChannel)
    handler.channel = channel
    already_imported = AsyncMock(spec=discord.Message)
    already_imported.reactions = [MagicMock(emoji="✅", me=True)]
    needs_import = AsyncMock(spec=discord.Message)
    needs_import.reactions = [MagicMock(emoji="👍", me=True)]
    channel.history.return_value.__aiter__.return_value = [
        already_imported,
        needs_import,
    ]
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.typing.return_value.__aenter__ = AsyncMock(return_value=None)
    ctx.typing.return_value.__aexit__ = AsyncMock(return_value=None)
    handler.handle = AsyncMock()
    await handler.catch_up(ctx)
    handler.handle.assert_awaited_once_with(needs_import)
    ctx.send.assert_awaited_once_with("Catch-up complete. Processed 1 messages.")
