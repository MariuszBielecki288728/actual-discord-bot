from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from actual_discord_bot.channel_handlers.notifications import (
    ERROR_REACTION,
    MessageHandlingResult,
    NotificationChannelHandler,
)
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
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
    notification.to_transaction.return_value = ActualTransactionData(
        date=date(2026, 8, 2),
        account="Pekao",
        amount=Decimal("-12.34"),
        imported_payee="Shop",
    )
    handler.actual_connector.config.file = "Household"
    handler.notification_type.from_message.return_value = notification
    result = await handler.handle(message)
    assert result is MessageHandlingResult.IMPORTED
    handler.actual_connector.save_transaction.assert_called_once_with(
        notification.to_transaction.return_value
    )
    message.add_reaction.assert_awaited_once_with("✅")
    message.reply.assert_awaited_once_with(
        "Created transaction: **Shop**, 12.34 PLN\n"
        "Budget: **Household** · Account: **Pekao** · Category: *Uncategorized*"
    )


@pytest.mark.asyncio
async def test_parse_error_is_marked_and_explained(handler):
    message = AsyncMock(spec=discord.Message)
    message.id = 1
    message.content = "invalid"
    handler.notification_type.from_message.side_effect = ParseNotificationError(
        "invalid"
    )
    result = await handler.handle(message)
    assert result is MessageHandlingResult.FAILED
    message.add_reaction.assert_awaited_once_with(ERROR_REACTION)
    message.reply.assert_awaited_once_with(
        "Could not import notification: its format is not supported. "
        "Check that it was forwarded in the expected format."
    )


@pytest.mark.asyncio
async def test_unexpected_error_is_logged_and_translated_to_a_discord_reply(handler):
    message = AsyncMock(spec=discord.Message)
    message.id = 1
    message.content = "notification"
    handler.notification_type.from_message.side_effect = RuntimeError("connection lost")

    result = await handler.handle(message)

    assert result is MessageHandlingResult.FAILED
    message.add_reaction.assert_awaited_once_with(ERROR_REACTION)
    message.reply.assert_awaited_once_with(
        "An unexpected error occurred while importing the notification. "
        "The error has been logged."
    )


@pytest.mark.asyncio
async def test_catch_up_skips_bot_status_reactions_and_retries_unmarked_messages(handler):
    channel = AsyncMock(spec=discord.TextChannel)
    handler.channel = channel
    already_imported = AsyncMock(spec=discord.Message)
    already_imported.reactions = [MagicMock(emoji="✅", me=True)]
    failed_import = AsyncMock(spec=discord.Message)
    failed_import.reactions = [MagicMock(emoji="❌", me=True)]
    needs_import = AsyncMock(spec=discord.Message)
    needs_import.reactions = []
    channel.history.return_value.__aiter__.return_value = [
        already_imported,
        failed_import,
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


@pytest.mark.asyncio
async def test_catch_up_retries_user_marked_messages_and_removes_the_marker(handler):
    channel = AsyncMock(spec=discord.TextChannel)
    handler.channel = channel
    user = MagicMock(bot=False)
    retry_marker = MagicMock(emoji="🔄", me=False, count=1)
    retry_marker.users.return_value.__aiter__.return_value = [user]
    failed_import = AsyncMock(spec=discord.Message)
    failed_import.id = 1
    failed_import.reactions = [
        MagicMock(emoji="❌", me=True, count=1),
        retry_marker,
    ]
    channel.history.return_value.__aiter__.return_value = [failed_import]
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.typing.return_value.__aenter__ = AsyncMock(return_value=None)
    ctx.typing.return_value.__aexit__ = AsyncMock(return_value=None)
    handler.handle = AsyncMock()

    await handler.catch_up(ctx)

    handler.handle.assert_awaited_once_with(failed_import)
    failed_import.remove_reaction.assert_awaited_once_with("🔄", user)
