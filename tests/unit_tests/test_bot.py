import asyncio
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import discord
import pytest

import actual_discord_bot.bot as bot_module
from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.bot import (
    BULK_DELETE_SAFE_AGE,
    CATCH_UP_TIME_DELTA_ERROR,
    CatchUpTimeDeltaError,
    ClearChannelResult,
    delete_channel_history,
    parse_catch_up_after,
)
from actual_discord_bot.channel_handlers.bank_imports import BankImportChannelHandler
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


def _history(messages):
    async def iterator():
        for message in messages:
            yield message

    return iterator()


def _message(identifier: int, created_at: datetime, *, deletable: bool = True):
    message = MagicMock(spec=discord.Message)
    message.id = identifier
    message.created_at = created_at
    message.type.is_deletable.return_value = deletable
    message.delete = AsyncMock()
    return message


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
    for name in ("catch_up", "clear_channel", "help", "make_schedule"):
        command = bot.get_command(name)
        assert command is not None
        assert "self" not in command.params

    catch_up = bot.get_command("catch_up")
    assert catch_up is not None
    assert "time_delta" in catch_up.params
    make_schedule = bot.get_command("make_schedule")
    assert make_schedule is not None
    assert "time_delta" in make_schedule.params


@pytest.mark.asyncio
async def test_clear_channel_rejects_an_unwatched_channel(bot):
    ctx = AsyncMock()
    ctx.channel = _channel(10, "unwatched")

    command = bot.get_command("clear_channel")
    assert command is not None
    await command.callback(ctx)

    ctx.send.assert_awaited_once_with(
        "Error: This command can only be used in a configured watched channel."
    )


@pytest.mark.asyncio
async def test_clear_channel_requires_caller_manage_messages_permission(bot):
    channel = _channel(1, "bank-notifications")
    bot.notification_handler.channel = channel
    ctx = AsyncMock()
    ctx.channel = channel
    ctx.author = MagicMock(spec=discord.Member)
    channel.permissions_for.return_value.manage_messages = False

    command = bot.get_command("clear_channel")
    assert command is not None
    await command.callback(ctx)

    ctx.send.assert_awaited_once_with(
        "Error: You need the Manage Messages permission to clear this channel."
    )


@pytest.mark.asyncio
async def test_clear_channel_rejects_a_non_text_watched_channel(bot):
    channel = MagicMock()
    channel.id = 1
    bot.notification_handler.channel = channel
    ctx = AsyncMock()
    ctx.channel = channel
    ctx.author = MagicMock(spec=discord.Member)

    command = bot.get_command("clear_channel")
    assert command is not None
    await command.callback(ctx)

    ctx.send.assert_awaited_once_with(
        "Error: This command can only be used in a server text channel."
    )


@pytest.mark.asyncio
async def test_clear_channel_deletes_watched_history_and_reports_count(bot):
    channel = _channel(1, "bank-notifications")
    bot.notification_handler.channel = channel
    ctx = AsyncMock()
    ctx.channel = channel
    ctx.author = MagicMock(spec=discord.Member)
    channel.permissions_for.return_value.manage_messages = True

    with patch.object(
        bot_module,
        "delete_channel_history",
        new=AsyncMock(return_value=ClearChannelResult(3, incomplete=False)),
    ) as delete_history:
        command = bot.get_command("clear_channel")
        assert command is not None
        await command.callback(ctx)

    delete_history.assert_awaited_once_with(channel)
    ctx.send.assert_awaited_once_with("Channel cleared. Deleted 3 messages.")


@pytest.mark.asyncio
async def test_clear_channel_reports_a_partial_result(bot):
    channel = _channel(1, "bank-notifications")
    bot.notification_handler.channel = channel
    ctx = AsyncMock()
    ctx.channel = channel
    ctx.author = MagicMock(spec=discord.Member)
    channel.permissions_for.return_value.manage_messages = True

    with patch.object(
        bot_module,
        "delete_channel_history",
        new=AsyncMock(return_value=ClearChannelResult(2, incomplete=True)),
    ):
        command = bot.get_command("clear_channel")
        assert command is not None
        await command.callback(ctx)

    ctx.send.assert_awaited_once_with("Channel clear incomplete. Deleted 2 messages.")


@pytest.mark.asyncio
async def test_clear_channel_serializes_deletion_in_one_channel(bot):
    channel = _channel(1, "bank-notifications")
    bot.notification_handler.channel = channel
    first_deletion_started = asyncio.Event()
    release_first_deletion = asyncio.Event()
    calls = 0

    async def delete_history(_channel):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_deletion_started.set()
            await release_first_deletion.wait()
        return ClearChannelResult(0, incomplete=False)

    def context():
        ctx = AsyncMock()
        ctx.channel = channel
        ctx.author = MagicMock(spec=discord.Member)
        return ctx

    channel.permissions_for.return_value.manage_messages = True
    first_context = context()
    second_context = context()
    command = bot.get_command("clear_channel")
    assert command is not None

    with patch.object(bot_module, "delete_channel_history", new=delete_history):
        first_task = asyncio.create_task(command.callback(first_context))
        await first_deletion_started.wait()
        second_task = asyncio.create_task(command.callback(second_context))
        await asyncio.sleep(0)
        assert calls == 1
        release_first_deletion.set()
        await asyncio.gather(first_task, second_task)

    assert calls == 2


@pytest.mark.asyncio
async def test_delete_channel_history_batches_recent_messages_and_deletes_old_ones(bot):
    now = datetime(2026, 8, 2, 15, 30, tzinfo=UTC)
    channel = _channel(1, "bank-notifications")
    recent_messages = [
        _message(1, now - timedelta(days=1)),
        _message(2, now - timedelta(days=2)),
    ]
    old_message = _message(3, now - timedelta(days=15))
    channel.history.return_value = _history([*recent_messages, old_message])

    with patch.object(bot_module.discord.utils, "utcnow", return_value=now):
        result = await delete_channel_history(channel)

    assert result == ClearChannelResult(3, incomplete=False)
    channel.delete_messages.assert_awaited_once_with(recent_messages)
    old_message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_channel_history_splits_batches_at_one_hundred_messages(bot):
    now = datetime(2026, 8, 2, 15, 30, tzinfo=UTC)
    channel = _channel(1, "bank-notifications")
    messages = [_message(index, now) for index in range(101)]
    channel.history.return_value = _history(messages)

    with patch.object(bot_module.discord.utils, "utcnow", return_value=now):
        result = await delete_channel_history(channel)

    assert result == ClearChannelResult(101, incomplete=False)
    assert len(channel.delete_messages.await_args.args[0]) == 100
    messages[-1].delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_channel_history_reports_non_deletable_messages_as_incomplete(bot):
    now = datetime(2026, 8, 2, 15, 30, tzinfo=UTC)
    channel = _channel(1, "bank-notifications")
    deletable = _message(1, now)
    non_deletable = _message(2, now, deletable=False)
    channel.history.return_value = _history([deletable, non_deletable])

    with patch.object(bot_module.discord.utils, "utcnow", return_value=now):
        result = await delete_channel_history(channel)

    assert result == ClearChannelResult(1, incomplete=True)
    deletable.delete.assert_awaited_once()
    non_deletable.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_channel_history_reports_successful_deletions_before_an_api_error(bot):
    now = datetime(2026, 8, 2, 15, 30, tzinfo=UTC)
    channel = _channel(1, "bank-notifications")
    old_message = _message(1, now - BULK_DELETE_SAFE_AGE - timedelta(days=1))
    failing_message = _message(2, now - BULK_DELETE_SAFE_AGE - timedelta(days=2))
    failing_message.delete.side_effect = discord.HTTPException(
        MagicMock(status=500, reason="server error"), "server error"
    )
    channel.history.return_value = _history([old_message, failing_message])

    with patch.object(bot_module.discord.utils, "utcnow", return_value=now):
        result = await delete_channel_history(channel)

    assert result == ClearChannelResult(1, incomplete=True)
    old_message.delete.assert_awaited_once()


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
async def test_on_message_prioritizes_bank_csv_imports_in_a_shared_channel():
    notification_handler = NotificationChannelHandler("shared", MagicMock())
    bank_handler = BankImportChannelHandler(
        "shared", MagicMock(), ZoneInfo("Europe/Warsaw")
    )
    bot = ActualDiscordBot(notification_handler, bank_import_handler=bank_handler)
    channel = _channel(1, "shared")
    notification_handler.channel = channel
    bank_handler.channel = channel
    message = AsyncMock(spec=discord.Message)
    message.author = MagicMock()
    message.channel = channel
    message.content = ""
    message.attachments = [MagicMock(spec=discord.Attachment, filename="statement.csv")]
    with (
        patch.object(type(bot), "user", new_callable=lambda: property(lambda _: None)),
        patch.object(
            bot, "get_context", new=AsyncMock(return_value=MagicMock(valid=False))
        ),
        patch.object(bank_handler, "handle", new=AsyncMock()) as bank_handle,
        patch.object(
            notification_handler, "handle", new=AsyncMock()
        ) as notification_handle,
    ):
        await bot.on_message(message)
    bank_handle.assert_awaited_once_with(message)
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


@pytest.mark.asyncio
async def test_make_schedule_delegates_a_valid_recurrence(bot):
    ctx = AsyncMock()
    with patch.object(
        bot.notification_handler, "make_schedule", new=AsyncMock()
    ) as make_schedule:
        command = bot.get_command("make_schedule")
        assert command is not None
        await command.callback(ctx, time_delta="2 weeks")

    make_schedule.assert_awaited_once()
    assert make_schedule.await_args.args[0] is ctx
    recurrence = make_schedule.await_args.args[1]
    assert recurrence.interval == 2
    assert recurrence.frequency.value == "weekly"


@pytest.mark.asyncio
async def test_make_schedule_rejects_invalid_recurrence_without_delegating(bot):
    ctx = AsyncMock()
    with patch.object(
        bot.notification_handler, "make_schedule", new=AsyncMock()
    ) as make_schedule:
        command = bot.get_command("make_schedule")
        assert command is not None
        await command.callback(ctx, time_delta="1 hour")

    ctx.reply.assert_awaited_once_with(
        "Error: Invalid recurrence. Use X day(s), X week(s), X month(s), or X year(s)."
    )
    make_schedule.assert_not_awaited()


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
        show_error_tracebacks=False,
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
    assert discord_bot.call_args.args[0].show_error_tracebacks is False
    if receipt_channel:
        processor.assert_called_once()
        assert discord_bot.call_args.args[1] is not None
    else:
        processor.assert_not_called()
        assert discord_bot.call_args.args[1] is None
