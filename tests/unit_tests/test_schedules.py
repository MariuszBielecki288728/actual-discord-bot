from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from actual_discord_bot.actual_connector import (
    ActualConnector,
    ActualScheduleData,
    ScheduleCreationStatus,
)
from actual_discord_bot.channel_handlers.notifications import (
    NotificationChannelHandler,
)
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.errors import ScheduleSourceNotFound
from actual_discord_bot.schedules import (
    RecurrenceFrequency,
    ScheduleRecurrence,
    TimeDeltaError,
    parse_schedule_recurrence,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ScheduleRecurrence()),
        ("  1 DAY  ", ScheduleRecurrence(1, RecurrenceFrequency.DAILY)),
        ("2 weeks", ScheduleRecurrence(2, RecurrenceFrequency.WEEKLY)),
        ("12 Months", ScheduleRecurrence(12, RecurrenceFrequency.MONTHLY)),
        ("3 year", ScheduleRecurrence(3, RecurrenceFrequency.YEARLY)),
    ],
)
def test_parse_schedule_recurrence(value, expected):
    assert parse_schedule_recurrence(value) == expected


@pytest.mark.parametrize(
    "value", ["0 months", "1hour", "2.5 weeks", "two days", "1 day now", "1 hours"]
)
def test_parse_schedule_recurrence_rejects_invalid_values(value):
    with pytest.raises(TimeDeltaError):
        parse_schedule_recurrence(value)


def _schedule_data():
    return ActualScheduleData(
        start=date(2024, 9, 23),
        account="Pekao",
        amount=Decimal("-90.45"),
        payee="CARREFOUR POL",
        name="CARREFOUR POL",
        recurrence=ScheduleRecurrence(2, RecurrenceFrequency.MONTHLY),
    )


def _connector_with_actual():
    connector = ActualConnector(MagicMock())
    actual = MagicMock()
    manager = MagicMock()
    manager.__enter__.return_value = actual
    connector._create_actual_manager = MagicMock(return_value=manager)  # noqa: SLF001
    return connector, actual


def test_connector_creates_an_exact_manual_never_ending_schedule():
    connector, actual = _connector_with_actual()
    account = MagicMock()
    payee = MagicMock()
    recurrence = MagicMock()
    with (
        patch("actual_discord_bot.actual_connector.get_schedules", return_value=[]),
        patch("actual_discord_bot.actual_connector.get_account", return_value=account),
        patch("actual_discord_bot.actual_connector.get_payee", return_value=payee),
        patch(
            "actual_discord_bot.actual_connector.create_schedule_config",
            return_value=recurrence,
        ) as create_config,
        patch(
            "actual_discord_bot.actual_connector.create_actual_schedule"
        ) as create_schedule,
    ):
        status = connector.create_schedule(_schedule_data())

    assert status is ScheduleCreationStatus.CREATED
    create_config.assert_called_once_with(
        start=date(2024, 9, 23),
        interval=2,
        frequency="monthly",
        end_mode="never",
        skip_weekend=False,
    )
    create_schedule.assert_called_once_with(
        actual.session,
        date=recurrence,
        amount=Decimal("-90.45"),
        amount_operation="is",
        name="CARREFOUR POL",
        payee=payee,
        account=account,
        posts_transaction=False,
    )
    actual.commit.assert_called_once_with()


def test_connector_returns_existing_case_insensitive_schedule_without_writing():
    connector, actual = _connector_with_actual()
    existing = MagicMock(name="carrefour pol")
    existing.name = "carrefour pol"
    with patch(
        "actual_discord_bot.actual_connector.get_schedules", return_value=[existing]
    ):
        status = connector.create_schedule(_schedule_data())

    assert status is ScheduleCreationStatus.ALREADY_EXISTS
    actual.commit.assert_not_called()


@pytest.mark.parametrize(
    ("account", "payee"), [(None, MagicMock()), (MagicMock(), None)]
)
def test_connector_rejects_missing_source_objects_before_creation(account, payee):
    connector, _ = _connector_with_actual()
    with (
        patch("actual_discord_bot.actual_connector.get_schedules", return_value=[]),
        patch("actual_discord_bot.actual_connector.get_account", return_value=account),
        patch("actual_discord_bot.actual_connector.get_payee", return_value=payee),
        patch(
            "actual_discord_bot.actual_connector.create_actual_schedule"
        ) as create_schedule,
    ):
        with pytest.raises(ScheduleSourceNotFound):
            connector.create_schedule(_schedule_data())
    create_schedule.assert_not_called()


def _message(channel):
    message = MagicMock()
    message.id = 101
    message.channel = channel
    message.content = "notification"
    message.created_at = datetime(2024, 9, 23, 12, tzinfo=UTC)
    message.reactions = [MagicMock(emoji="✅", me=True)]
    return message


@pytest.mark.asyncio
async def test_make_schedule_uses_reply_target_and_reports_created_schedule():
    channel = MagicMock(id=10)
    resolved_source = _message(channel)
    resolved_source.reactions = []
    source = _message(channel)
    channel.fetch_message = AsyncMock(return_value=source)
    reference = MagicMock(message_id=101, channel_id=10, resolved=resolved_source)
    ctx = MagicMock()
    ctx.channel = channel
    ctx.message.reference = reference
    ctx.reply = AsyncMock()
    connector = MagicMock()
    connector.create_schedule.return_value = ScheduleCreationStatus.CREATED
    handler = NotificationChannelHandler(
        "bank", connector, timezone=ZoneInfo("Europe/Warsaw")
    )
    handler.channel = channel
    transaction = ActualTransactionData(
        date=date(2024, 9, 23),
        account="Pekao",
        amount=Decimal("-90.45"),
        imported_payee=" CARREFOUR POL ",
    )
    with patch.object(
        handler, "_transaction_data_from_message", return_value=transaction
    ):
        await handler.make_schedule(
            handler_ctx := ctx, ScheduleRecurrence(2, RecurrenceFrequency.MONTHLY)
        )

    channel.fetch_message.assert_awaited_once_with(101)
    connector.create_schedule.assert_called_once_with(
        ActualScheduleData(
            start=date(2024, 9, 23),
            account="Pekao",
            amount=Decimal("-90.45"),
            payee="CARREFOUR POL",
            name="CARREFOUR POL",
            recurrence=ScheduleRecurrence(2, RecurrenceFrequency.MONTHLY),
        )
    )
    handler_ctx.reply.assert_awaited_once_with(
        "Created schedule: **CARREFOUR POL**\n"
        "Every 2 months from 2024-09-23 · 90.45 PLN · Account: **Pekao**\n"
        "Transactions require manual approval."
    )


@pytest.mark.asyncio
async def test_make_schedule_fetches_an_unresolved_reference_and_preserves_existing_schedule():
    channel = MagicMock(id=10)
    source = _message(channel)
    channel.fetch_message = AsyncMock(return_value=source)
    reference = MagicMock(message_id=101, channel_id=10, resolved=None)
    ctx = MagicMock(channel=channel, reply=AsyncMock())
    ctx.message.reference = reference
    connector = MagicMock()
    connector.create_schedule.return_value = ScheduleCreationStatus.ALREADY_EXISTS
    handler = NotificationChannelHandler("bank", connector)
    handler.channel = channel
    with patch.object(
        handler,
        "_transaction_data_from_message",
        return_value=ActualTransactionData(
            date(2024, 9, 23), "Pekao", Decimal("-1"), "Shop"
        ),
    ):
        await handler.make_schedule(ctx, ScheduleRecurrence())

    channel.fetch_message.assert_awaited_once_with(101)
    ctx.reply.assert_awaited_once_with(
        "Schedule **Shop** already exists. Nothing was changed."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reference", "reactions", "expected"),
    [
        (None, [], "Error: Reply to a successfully imported bank notification first."),
        (
            MagicMock(message_id=101, channel_id=99, resolved=None),
            [],
            "Error: Reply to a notification in this bank notification channel.",
        ),
        (
            MagicMock(message_id=101, channel_id=10, resolved=None),
            [],
            "Error: Reply to a notification that I imported successfully (✅).",
        ),
    ],
)
async def test_make_schedule_rejects_invalid_reply_states(
    reference, reactions, expected
):
    channel = MagicMock(id=10)
    source = _message(channel)
    source.reactions = reactions
    channel.fetch_message = AsyncMock(return_value=source)
    ctx = MagicMock(channel=channel, reply=AsyncMock())
    ctx.message.reference = reference
    handler = NotificationChannelHandler("bank", MagicMock())
    handler.channel = channel

    await handler.make_schedule(ctx, ScheduleRecurrence())

    ctx.reply.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_make_schedule_translates_missing_actual_sources():
    channel = MagicMock(id=10)
    source = _message(channel)
    channel.fetch_message = AsyncMock(return_value=source)
    ctx = MagicMock(channel=channel, reply=AsyncMock())
    ctx.message.reference = MagicMock(message_id=101, channel_id=10, resolved=source)
    connector = MagicMock()
    connector.create_schedule.side_effect = ScheduleSourceNotFound
    handler = NotificationChannelHandler("bank", connector)
    handler.channel = channel
    with patch.object(
        handler,
        "_transaction_data_from_message",
        return_value=ActualTransactionData(
            date(2024, 9, 23), "Pekao", Decimal("-1"), "Shop"
        ),
    ):
        await handler.make_schedule(ctx, ScheduleRecurrence())

    ctx.reply.assert_awaited_once_with(
        "Error: The notification's account or payee no longer exists in Actual. Nothing was changed."
    )


@pytest.mark.asyncio
async def test_make_schedule_includes_a_markdown_traceback_for_unexpected_errors():
    channel = MagicMock(id=10)
    source = _message(channel)
    channel.fetch_message = AsyncMock(return_value=source)
    ctx = MagicMock(channel=channel, reply=AsyncMock())
    ctx.message.reference = MagicMock(message_id=101, channel_id=10, resolved=source)
    connector = MagicMock()
    connector.create_schedule.side_effect = RuntimeError("connection lost")
    handler = NotificationChannelHandler("bank", connector)
    handler.channel = channel
    with patch.object(
        handler,
        "_transaction_data_from_message",
        return_value=ActualTransactionData(
            date(2024, 9, 23), "Pekao", Decimal("-1"), "Shop"
        ),
    ):
        await handler.make_schedule(ctx, ScheduleRecurrence())

    reply = ctx.reply.await_args.args[0]
    assert reply.startswith(
        "An unexpected error occurred while creating the schedule.\n"
        "**Traceback**\n```py\nTraceback (most recent call last):"
    )
    assert "RuntimeError: connection lost" in reply
    assert reply.endswith("\n```")
