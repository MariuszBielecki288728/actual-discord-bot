import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import actual_discord_bot.bot as bot_module
from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.bot import (
    CATCH_UP_TIME_DELTA_ERROR,
    CatchUpTimeDeltaError,
    parse_catch_up_after,
)
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


@pytest.mark.asyncio
async def test_setup_hook_skips_hot_reload_by_default(bot):
    with patch.object(bot_module, "Watcher") as watcher:
        await bot.setup_hook()

    watcher.assert_not_called()


@pytest.mark.asyncio
async def test_setup_hook_warns_and_continues_when_source_tree_is_missing(
    notification_handler, monkeypatch, tmp_path, caplog
):
    bot = ActualDiscordBot(notification_handler, hot_reload=True)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger=bot_module.LOGGER.name):
        await bot.setup_hook()

    assert "continuing without it" in caplog.text


@pytest.mark.asyncio
async def test_setup_hook_starts_hot_reload_when_source_tree_exists(
    notification_handler, monkeypatch, tmp_path
):
    (tmp_path / "actual_discord_bot").mkdir()
    bot = ActualDiscordBot(notification_handler, hot_reload=True)
    monkeypatch.chdir(tmp_path)
    watcher = MagicMock(start=AsyncMock())

    with patch.object(bot_module, "Watcher", return_value=watcher) as watcher_factory:
        await bot.setup_hook()

    watcher_factory.assert_called_once_with(bot, path="actual_discord_bot")
    watcher.start.assert_awaited_once()


def test_registers_commands_without_self_parameter(bot):
    for name in ("catch_up", "help"):
        command = bot.get_command(name)
        assert command is not None
        assert "self" not in command.params

    catch_up = bot.get_command("catch_up")
    assert catch_up is not None
    assert "time_delta" in catch_up.params


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
    command = bot.get_command("help")
    assert command is not None
    await command.callback(ctx)
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
        command = bot.get_command("catch_up")
        assert command is not None
        await command.callback(ctx)
    catch_up.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_catch_up_passes_valid_lookback_to_notification_handler(bot):
    ctx = AsyncMock()
    now = datetime(2026, 8, 2, 15, 30, tzinfo=UTC)
    with (
        patch.object(bot_module.discord.utils, "utcnow", return_value=now),
        patch.object(bot.notification_handler, "catch_up", new=AsyncMock()) as catch_up,
    ):
        command = bot.get_command("catch_up")
        assert command is not None
        await command.callback(ctx, time_delta="2 days")

    catch_up.assert_awaited_once_with(
        ctx, after=datetime(2026, 7, 31, 15, 30, tzinfo=UTC)
    )


@pytest.mark.asyncio
async def test_catch_up_rejects_invalid_lookback_without_processing(bot):
    ctx = AsyncMock()
    with patch.object(
        bot.notification_handler, "catch_up", new=AsyncMock()
    ) as catch_up:
        command = bot.get_command("catch_up")
        assert command is not None
        await command.callback(ctx, time_delta="a few days")

    ctx.send.assert_awaited_once_with(CATCH_UP_TIME_DELTA_ERROR)
    catch_up.assert_not_awaited()


@pytest.mark.parametrize(
    ("time_delta", "now", "expected"),
    [
        (
            "1 hour",
            datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
            datetime(2026, 8, 2, 14, 30, tzinfo=UTC),
        ),
        (
            "12 DAYS",
            datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
            datetime(2026, 7, 21, 15, 30, tzinfo=UTC),
        ),
        (
            "6 months",
            datetime(2026, 8, 31, 15, 30, tzinfo=UTC),
            datetime(2026, 2, 28, 15, 30, tzinfo=UTC),
        ),
    ],
)
def test_parse_catch_up_after_supports_hours_days_and_calendar_months(
    time_delta, now, expected
):
    assert parse_catch_up_after(time_delta, now) == expected


@pytest.mark.parametrize("time_delta", ["0 hours", "two days", "1 week", "1day"])
def test_parse_catch_up_after_rejects_invalid_time_deltas(time_delta):
    with pytest.raises(CatchUpTimeDeltaError):
        parse_catch_up_after(time_delta, datetime(2026, 8, 2, tzinfo=UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_channel", ["", "receipts"])
async def test_main_configures_optional_receipt_stack(receipt_channel):
    discord_config = MagicMock(
        receipt_channel=receipt_channel,
        bank_notification_channel="bank",
        token="token",
        hot_reload=False,
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
    assert discord_bot.call_args.kwargs["hot_reload"] is False
    if receipt_channel:
        processor.assert_called_once()
        assert discord_bot.call_args.args[1] is not None
    else:
        processor.assert_not_called()
        assert discord_bot.call_args.args[1] is None
