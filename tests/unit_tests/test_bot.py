from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.config import DiscordConfig
from actual_discord_bot.errors import ParseNotificationError


@pytest.fixture
def mock_channel():
    channel = AsyncMock(spec=discord.TextChannel)
    channel.name = "bank-notifications"
    return channel


class AsyncContextManagerMock:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


@pytest.fixture
def ctx():
    context = AsyncMock(spec=discord.ext.commands.Context)
    context.typing.return_value = AsyncContextManagerMock()
    return context


@pytest.mark.asyncio
async def test_catch_up_processes_unreacted_messages(bot, mock_channel, ctx):
    bot.target_channel = mock_channel

    unreacted_message = AsyncMock(spec=discord.Message)
    unreacted_message.reactions = []

    reacted_message = AsyncMock(spec=discord.Message)
    reaction = AsyncMock(spec=discord.Reaction)
    reaction.emoji = "✅"
    reaction.me = True
    reacted_message.reactions = [reaction]

    mock_channel.history.return_value.__aiter__.return_value = [
        unreacted_message,
        reacted_message,
    ]

    with patch.object(bot, "handle_message") as mock_handle:
        await bot.catch_up.callback(bot, ctx)

        mock_handle.assert_called_once_with(unreacted_message)
        ctx.send.assert_called_once_with("Catch-up complete. Processed 1 messages.")


@pytest.mark.asyncio
async def test_catch_up_handles_missing_channel(bot, ctx):
    bot.target_channel = None

    await bot.catch_up.callback(bot, ctx)

    ctx.send.assert_called_once_with("Error: Channel 'bank-notifications' not found.")


@pytest.mark.asyncio
async def test_catch_up_handles_empty_channel(bot, mock_channel, ctx):
    bot.target_channel = mock_channel
    mock_channel.history.return_value.__aiter__.return_value = []

    await bot.catch_up.callback(bot, ctx)

    ctx.send.assert_called_once_with("Catch-up complete. Processed 0 messages.")


@pytest.mark.asyncio
async def test_catch_up_ignores_already_reacted_messages(bot, mock_channel, ctx):
    bot.target_channel = mock_channel

    # Create a message that already has our reaction
    reacted_message = AsyncMock(spec=discord.Message)
    reaction = AsyncMock(spec=discord.Reaction)
    reaction.emoji = "✅"
    reaction.me = True
    reacted_message.reactions = [reaction]

    mock_channel.history.return_value.__aiter__.return_value = [reacted_message]

    with patch.object(bot, "handle_message") as mock_handle:
        await bot.catch_up.callback(bot, ctx)

        mock_handle.assert_not_called()
        ctx.send.assert_called_once_with("Catch-up complete. Processed 0 messages.")


@pytest.mark.asyncio
async def test_catch_up_processes_message_with_different_reaction(
    bot,
    mock_channel,
    ctx,
):
    # Arrange
    bot.target_channel = mock_channel

    # Create a message that has a different reaction
    message_with_different_reaction = AsyncMock(spec=discord.Message)
    different_reaction = AsyncMock(spec=discord.Reaction)
    different_reaction.emoji = "👍"  # Different emoji
    different_reaction.me = True
    message_with_different_reaction.reactions = [different_reaction]

    # Set up the history to return the message
    mock_channel.history.return_value.__aiter__.return_value = [
        message_with_different_reaction,
    ]

    # Act
    with patch.object(bot, "handle_message") as mock_handle:
        await bot.catch_up.callback(bot, ctx)

        # Assert
        mock_handle.assert_called_once_with(message_with_different_reaction)
        ctx.send.assert_called_once_with("Catch-up complete. Processed 1 messages.")


@pytest.mark.asyncio
async def test_create_actual_transaction_success(bot):
    message = AsyncMock(spec=discord.Message)
    message.content = """Title: Transakcja kartą
Text: Zapłacono kwotę 90,45 PLN kartą *1000 dnia 23-09-2024 godz. 19:12:27 w TEST. Bank Pekao S.A.
Timestamp: 1.727111551661E9"""

    mock_notification = MagicMock()
    mock_transaction_data = MagicMock()
    mock_notification.to_transaction.return_value = mock_transaction_data

    with patch("actual_discord_bot.bot.PekaoNotification") as mock_pekao_class:
        mock_pekao_class.from_message.return_value = mock_notification
        with patch.object(bot.actual_connector, "save_transaction") as mock_save:
            result = await bot.create_actual_transaction(message)

            assert result is True
            mock_pekao_class.from_message.assert_called_once_with(message.content)
            mock_notification.to_transaction.assert_called_once()
            mock_save.assert_called_once_with(mock_transaction_data)


@pytest.mark.asyncio
async def test_create_actual_transaction_parse_error(bot):
    message = AsyncMock(spec=discord.Message)
    message.content = "Invalid message format"

    with patch("actual_discord_bot.bot.PekaoNotification") as mock_pekao_class:
        mock_pekao_class.from_message.side_effect = ParseNotificationError("test error")

        result = await bot.create_actual_transaction(message)

        assert result is False
        mock_pekao_class.from_message.assert_called_once_with(message.content)


@pytest.mark.asyncio
async def test_create_actual_transaction_save_error(bot):
    message = AsyncMock(spec=discord.Message)
    message.content = """Title: Transakcja kartą
Text: Zapłacono kwotę 90,45 PLN kartą *1000 dnia 23-09-2024 godz. 19:12:27 w TEST. Bank Pekao S.A.
Timestamp: 1.727111551661E9"""

    mock_notification = MagicMock()
    mock_transaction_data = MagicMock()
    mock_notification.to_transaction.return_value = mock_transaction_data

    with patch("actual_discord_bot.bot.PekaoNotification") as mock_pekao_class:
        mock_pekao_class.from_message.return_value = mock_notification
        with patch.object(bot.actual_connector, "save_transaction") as mock_save:
            mock_save.side_effect = Exception("Database error")

            result = await bot.create_actual_transaction(message)

            assert result is False
            mock_save.assert_called_once_with(mock_transaction_data)


@pytest.mark.asyncio
async def test_handle_message_adds_reaction_on_success(bot):
    message = AsyncMock(spec=discord.Message)

    with patch.object(
        bot,
        "create_actual_transaction",
        new=AsyncMock(return_value=True),
    ):
        await bot.handle_message(message)

        message.add_reaction.assert_called_once_with("✅")


@pytest.mark.asyncio
async def test_handle_message_no_reaction_on_failure(bot):
    message = AsyncMock(spec=discord.Message)

    with patch.object(bot, "create_actual_transaction", return_value=False):
        await bot.handle_message(message)

        message.add_reaction.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_routes_to_receipt_channel():
    """Test that messages in the receipt channel are routed to handle_receipt_message."""
    config = DiscordConfig(
        token="token",
        bank_notification_channel="bank-notifications",
        receipt_channel="receipts",
    )
    mock_actual_connector = MagicMock()
    bot = ActualDiscordBot(config, mock_actual_connector)

    mock_user = MagicMock()
    mock_user.id = 123

    # Set up receipt channel
    receipt_channel = MagicMock(spec=discord.TextChannel)
    receipt_channel.id = 999
    bot.receipt_target_channel = receipt_channel

    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.id = 456
    message.channel = MagicMock()
    message.channel.id = 999

    with (
        patch.object(
            type(bot), "user", new_callable=lambda: property(lambda self: mock_user)
        ),
        patch.object(bot, "handle_receipt_message") as mock_receipt,
    ):
        await bot.on_message(message)
        mock_receipt.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_on_message_routes_to_bank_channel():
    """Test that messages in the bank channel are routed to handle_message."""
    config = DiscordConfig(
        token="token",
        bank_notification_channel="bank-notifications",
        receipt_channel="receipts",
    )
    mock_actual_connector = MagicMock()
    bot = ActualDiscordBot(config, mock_actual_connector)

    mock_user = MagicMock()
    mock_user.id = 123

    # Set up bank channel
    bank_channel = MagicMock(spec=discord.TextChannel)
    bank_channel.id = 888
    bot.target_channel = bank_channel

    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.id = 456
    message.channel = MagicMock()
    message.channel.id = 888

    with (
        patch.object(
            type(bot), "user", new_callable=lambda: property(lambda self: mock_user)
        ),
        patch.object(bot, "handle_message") as mock_bank,
    ):
        await bot.on_message(message)
        mock_bank.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_on_message_ignores_own_messages():
    """Test that bot ignores its own messages."""
    config = DiscordConfig(
        token="token",
        bank_notification_channel="bank-notifications",
    )
    mock_actual_connector = MagicMock()
    bot = ActualDiscordBot(config, mock_actual_connector)

    mock_user = MagicMock()

    message = AsyncMock(spec=discord.Message)
    message.author = mock_user  # Bot's own message

    with (
        patch.object(
            type(bot), "user", new_callable=lambda: property(lambda self: mock_user)
        ),
        patch.object(bot, "handle_message") as mock_bank,
        patch.object(bot, "handle_receipt_message") as mock_receipt,
    ):
        await bot.on_message(message)
        mock_bank.assert_not_called()
        mock_receipt.assert_not_called()
