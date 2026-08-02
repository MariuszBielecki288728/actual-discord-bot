from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import actual_discord_bot.bot as bot_module
from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.channel_handlers.notifications import (
    NOTIFICATION_HELP_MESSAGE,
    NotificationChannelHandler,
)
from actual_discord_bot.channel_handlers.receipts import (
    RECEIPT_HELP_MESSAGE,
    ReceiptChannelHandler,
)


def _channel(identifier: int, name: str):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = identifier
    channel.name = name
    return channel


@pytest.mark.asyncio
async def test_on_ready_binds_all_handlers_across_guilds_and_announces(bot):
    receipt_handler = ReceiptChannelHandler("receipts", MagicMock(), MagicMock())
    bot = ActualDiscordBot(bot.notification_handler, receipt_handler)
    notification_channel = _channel(1, "bank-notifications")
    receipt_channel = _channel(2, "receipts")
    first_guild = MagicMock(channels=[notification_channel])
    second_guild = MagicMock(channels=[receipt_channel])

    with (
        patch.object(
            type(bot),
            "guilds",
            new_callable=lambda: property(lambda _: [first_guild, second_guild]),
        ),
        patch.object(type(bot), "user", new_callable=lambda: property(lambda _: None)),
    ):
        await bot.on_ready()

    assert bot.notification_handler.channel is notification_channel
    assert receipt_handler.channel is receipt_channel


def test_registers_commands(bot):
    assert bot.get_command("catch_up") is bot.catch_up
    assert bot.get_command("help") is bot.help


@pytest.mark.asyncio
async def test_on_message_invokes_valid_command_before_handlers(bot):
    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    context = MagicMock(valid=True)
    with (
        patch.object(type(bot), "user", new_callable=lambda: property(lambda _: None)),
        patch.object(bot, "get_context", new=AsyncMock(return_value=context)),
        patch.object(bot, "invoke", new=AsyncMock()) as invoke,
        patch.object(bot.notification_handler, "handle", new=AsyncMock()) as handle,
    ):
        await bot.on_message(message)
    invoke.assert_awaited_once_with(context)
    handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_prefers_receipts_in_a_shared_channel():
    notification_handler = NotificationChannelHandler("shared", MagicMock())
    receipt_handler = ReceiptChannelHandler("shared", MagicMock(), MagicMock())
    bot = ActualDiscordBot(notification_handler, receipt_handler)
    channel = _channel(1, "shared")
    notification_handler.channel = channel
    receipt_handler.channel = channel
    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    message.channel = channel
    attachment = MagicMock(spec=discord.Attachment, filename="receipt.jpg")
    message.attachments = [attachment]
    message.content = "a notification"
    with (
        patch.object(type(bot), "user", new_callable=lambda: property(lambda _: None)),
        patch.object(
            bot, "get_context", new=AsyncMock(return_value=MagicMock(valid=False))
        ),
        patch.object(receipt_handler, "handle", new=AsyncMock()) as receipt_handle,
        patch.object(
            notification_handler, "handle", new=AsyncMock()
        ) as notification_handle,
    ):
        await bot.on_message(message)
    receipt_handle.assert_awaited_once_with(message)
    notification_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_routes_shared_non_receipt_to_notifications():
    notification_handler = NotificationChannelHandler("shared", MagicMock())
    receipt_handler = ReceiptChannelHandler("shared", MagicMock(), MagicMock())
    bot = ActualDiscordBot(notification_handler, receipt_handler)
    channel = _channel(1, "shared")
    notification_handler.channel = channel
    receipt_handler.channel = channel
    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    message.channel = channel
    message.attachments = []
    message.content = "a notification"
    with (
        patch.object(type(bot), "user", new_callable=lambda: property(lambda _: None)),
        patch.object(
            bot, "get_context", new=AsyncMock(return_value=MagicMock(valid=False))
        ),
        patch.object(
            notification_handler, "handle", new=AsyncMock()
        ) as notification_handle,
    ):
        await bot.on_message(message)
    notification_handle.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_help_sends_both_shared_channel_guides():
    notification_handler = NotificationChannelHandler("shared", MagicMock())
    receipt_handler = ReceiptChannelHandler("shared", MagicMock(), MagicMock())
    bot = ActualDiscordBot(notification_handler, receipt_handler)
    channel = _channel(1, "shared")
    notification_handler.channel = channel
    receipt_handler.channel = channel
    ctx = AsyncMock()
    ctx.channel = channel
    await bot.help.callback(bot, ctx)
    assert ctx.send.await_args_list == [
        ((RECEIPT_HELP_MESSAGE,), {}),
        ((NOTIFICATION_HELP_MESSAGE,), {}),
    ]


@pytest.mark.asyncio
async def test_catch_up_delegates_to_notification_handler(bot):
    ctx = AsyncMock()
    with patch.object(
        bot.notification_handler, "catch_up", new=AsyncMock()
    ) as catch_up:
        await bot.catch_up.callback(bot, ctx)
    catch_up.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_channel", ["", "receipts"])
async def test_main_configures_optional_receipt_stack(receipt_channel):
    discord_config = MagicMock(
        receipt_channel=receipt_channel, bank_notification_channel="bank", token="token"
    )
    client = MagicMock(start=AsyncMock())
    with (
        patch.object(
            bot_module.DiscordConfig, "from_environ", return_value=discord_config
        ),
        patch.object(bot_module.ActualConfig, "from_environ", return_value=MagicMock()),
        patch.object(bot_module, "ActualConnector"),
        patch.object(bot_module, "OCRConfig"),
        patch.object(bot_module, "create_ocr_provider"),
        patch.object(bot_module, "ReceiptProcessor") as processor,
        patch.object(
            bot_module, "ActualDiscordBot", return_value=client
        ) as discord_bot,
    ):
        await bot_module.main()
    client.start.assert_awaited_once_with("token")
    if receipt_channel:
        processor.assert_called_once()
        assert discord_bot.call_args.args[1] is not None
    else:
        processor.assert_not_called()
        assert discord_bot.call_args.args[1] is None
