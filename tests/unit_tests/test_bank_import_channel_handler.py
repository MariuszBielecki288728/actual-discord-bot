from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest

from actual_discord_bot.bank_imports.models import (
    BankImportResult,
    BankImportTransaction,
    ConvertedBankStatement,
    ImportableActualAccount,
)
from actual_discord_bot.channel_handlers.bank_imports import (
    ACCOUNTS_PER_PAGE,
    AccountSelectionView,
    BankImportChannelHandler,
)


@pytest.fixture
def message():
    value = AsyncMock(spec=discord.Message)
    value.id = 9
    value.content = ""
    value.author.id = 3
    value.guild.me = MagicMock()
    attachment = MagicMock(spec=discord.Attachment, filename="Lista_operacji_20260802_021721.csv")
    attachment.read = AsyncMock(return_value=b"synthetic")
    attachment.size = len(b"synthetic")
    value.attachments = [attachment]
    return value


@pytest.fixture
def handler():
    connector = MagicMock()
    converter = MagicMock()
    converter.convert = AsyncMock(
        return_value=ConvertedBankStatement(
            "PL Bank Pekao",
            "Lista_operacji_20260802_021721.csv",
            (
                BankImportTransaction(
                    datetime.now(ZoneInfo("Europe/Warsaw")).date(),
                    Decimal("-12.34"),
                    "Synthetic Shop",
                    None,
                    "YNAB:-12340:2026-08-01:1",
                ),
            ),
        )
    )
    return BankImportChannelHandler(
        "bank-imports", connector, ZoneInfo("Europe/Warsaw"), converter
    )


@pytest.mark.asyncio
async def test_handler_imports_one_csv_and_reports_only_aggregate_data(handler, message):
    handler.actual_connector.list_import_accounts.return_value = (
        ImportableActualAccount("Pekao", False),
    )
    handler.actual_connector.import_bank_transactions.return_value = BankImportResult(1, 0)

    await handler.handle(message)

    handler.actual_connector.import_bank_transactions.assert_called_once()
    message.remove_reaction.assert_awaited_once()
    assert message.add_reaction.await_args_list[-1].args == ("✅",)
    reply = message.reply.await_args.args[0]
    assert "created: 1" in reply
    assert "Synthetic Shop" not in reply


@pytest.mark.asyncio
async def test_handler_rejects_multiple_attachments_without_downloading(handler, message):
    message.attachments.append(MagicMock(spec=discord.Attachment, filename="other.txt"))

    await handler.handle(message)

    handler.converter.convert.assert_not_awaited()
    assert message.add_reaction.await_args_list[-1].args == ("❌",)
    assert "exactly one CSV" in message.reply.await_args.args[0]


@pytest.mark.asyncio
async def test_handler_warns_when_all_converted_rows_are_outside_date_window(handler, message):
    handler.converter.convert.return_value = ConvertedBankStatement(
        "PL Bank Pekao",
        "Lista_operacji_20260802_021721.csv",
        (
            BankImportTransaction(
                date(2000, 1, 1), Decimal("-12.34"), "Synthetic Shop", None, "id"
            ),
        ),
    )

    await handler.handle(message)

    handler.actual_connector.list_import_accounts.assert_not_called()
    assert message.add_reaction.await_args_list[-1].args == ("⚠️",)


@pytest.mark.asyncio
async def test_account_selector_restricts_interactions_to_the_uploader():
    view = AccountSelectionView(3, (ImportableActualAccount("Pekao", False),))
    interaction = MagicMock()
    interaction.user.id = 4
    interaction.response.send_message = AsyncMock()

    assert await view.interaction_check(interaction) is False
    interaction.response.send_message.assert_awaited_once_with(
        "Only the uploader can select an import account.", ephemeral=True
    )


def test_account_selector_paginates_at_discord_option_limit():
    accounts = tuple(
        ImportableActualAccount(f"Synthetic account {index}", False)
        for index in range(ACCOUNTS_PER_PAGE + 1)
    )
    view = AccountSelectionView(3, accounts)

    selector = next(item for item in view.children if isinstance(item, discord.ui.Select))
    assert len(selector.options) == ACCOUNTS_PER_PAGE
    view.page = 1
    view._render_page()  # noqa: SLF001 - assert the second-page component limit
    selector = next(item for item in view.children if isinstance(item, discord.ui.Select))
    assert len(selector.options) == 1
