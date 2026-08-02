from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from actual_discord_bot.actual_connector import (
    ActualConnector,
    generate_bank_imported_id,
)
from actual_discord_bot.bank_imports.models import BankImportTransaction
from actual_discord_bot.config import ActualConfig


@pytest.fixture
def actual_manager():
    value = MagicMock()
    value.__enter__.return_value = value
    value.__exit__.return_value = False
    account = MagicMock()
    account.name = "Pekao"
    account.closed = False
    account.tombstone = False
    account.offbudget = False
    value.session.exec.return_value.all.return_value = [account]
    return value


@pytest.fixture
def connector(actual_manager):
    instance = ActualConnector(ActualConfig(url="http://test", password="test", file="budget"))
    with patch.object(instance, "_create_actual_manager", return_value=actual_manager):
        yield instance


def _row(identifier="YNAB:-12340:2026-08-01:1"):
    return BankImportTransaction(
        date=date(2026, 8, 1),
        amount=Decimal("-12.34"),
        payee="Synthetic Shop",
        memo="Synthetic memo",
        upstream_import_id=identifier,
    )


def test_import_bank_transactions_creates_cleared_row_with_namespaced_id(connector, actual_manager):
    with (
        patch("actual_discord_bot.actual_connector.get_transactions", return_value=[]),
        patch("actual_discord_bot.actual_connector.create_transaction") as create,
    ):
        result = connector.import_bank_transactions("Pekao", "PL Bank Pekao", [_row()])

    assert result.created_count == 1
    assert result.duplicate_count == 0
    assert create.call_args.kwargs["cleared"] is True
    assert create.call_args.kwargs["imported_id"] == generate_bank_imported_id(
        "PL Bank Pekao", _row().upstream_import_id
    )
    actual_manager.commit.assert_called_once()


def test_import_bank_transactions_skips_existing_deterministic_id(connector, actual_manager):
    existing = MagicMock()
    existing.financial_id = generate_bank_imported_id("PL Bank Pekao", _row().upstream_import_id)
    with patch("actual_discord_bot.actual_connector.get_transactions", return_value=[existing]):
        result = connector.import_bank_transactions("Pekao", "PL Bank Pekao", [_row()])

    assert result.created_count == 0
    assert result.duplicate_count == 1
    actual_manager.commit.assert_not_called()


def test_fallback_candidate_is_consumed_so_identical_statement_rows_are_preserved(
    connector, actual_manager
):
    existing = MagicMock()
    existing.financial_id = None
    existing.is_child = False
    existing.amount = Decimal("-12.34")
    existing.date = date(2026, 8, 1)
    existing.imported_description = "Synthetic Shop"
    existing.notes = ""
    existing.payee = None
    second_row = _row("YNAB:-12340:2026-08-01:2")
    with (
        patch("actual_discord_bot.actual_connector.get_transactions", return_value=[existing]),
        patch("actual_discord_bot.actual_connector.create_transaction") as create,
    ):
        result = connector.import_bank_transactions(
            "Pekao", "PL Bank Pekao", [_row(), second_row]
        )

    assert (result.created_count, result.duplicate_count) == (1, 1)
    create.assert_called_once()
    actual_manager.commit.assert_called_once()


def test_list_import_accounts_excludes_closed_and_tombstoned_accounts(connector, actual_manager):
    open_account = actual_manager.session.exec.return_value.all.return_value[0]
    closed_account = MagicMock(name="Old account", closed=True, tombstone=False)
    removed_account = MagicMock(name="Removed", closed=False, tombstone=True)
    actual_manager.session.exec.return_value.all.return_value = [
        open_account,
        closed_account,
        removed_account,
    ]

    assert tuple(account.name for account in connector.list_import_accounts()) == ("Pekao",)
